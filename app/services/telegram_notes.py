"""Quick Telegram notes backed by the site's Note model and durable TelegramState."""
from datetime import timedelta
from hashlib import sha256
from html import escape
import re
import secrets

from ..core.validation import normalize_bounded_text
from ..models import Note, TelegramState
from .telegram_state import state_row, utcnow

TTL = timedelta(minutes=30)
PREFIX = re.compile(r'^заметка\s*:\s*(.*)$', re.IGNORECASE | re.DOTALL)


def button(text, action):
    return {'text': text, 'callback_data': action}


def keyboard(*rows):
    return {'inline_keyboard': list(rows)}


def binding(user):
    return [user.id, user.telegram_user_id, user.telegram_chat_id,
            user.telegram_linked_at.isoformat() if user.telegram_linked_at else None]


def prompt(token):
    return ('📝 <b>Новая заметка</b>\n\nНапиши текст одним сообщением.\n\n'
            'Например:\nНа БД повторить оконные функции',
            keyboard([button('❌ Отмена', f'note_cancel:{token}')]))


def expired():
    return '⚠️ Создание заметки устарело.', keyboard([button('📝 Новая заметка', 'note_start')])


def preview(note):
    body = note.content or ''
    # A long first line produces a short title and a complete body. Show it once.
    if body.startswith(note.title.rstrip('…')):
        text = body
    else:
        text = note.title + ('\n' + body if body else '')
    return escape(text[:200] + ('…' if len(text) > 200 else ''), quote=False)


def saved_view(note, site_url, *, heading='✅ Заметка сохранена'):
    return (f'{heading}\n\n{preview(note)}', keyboard(
        [button('🗑 Удалить', f'note_delete:{note.id}')],
        [button('📝 Ещё заметку', 'note_start')],
        [{'text': '🌐 Открыть заметки', 'url': site_url.rstrip('/') + f'/notes?note={note.id}'}],
    ))


def create_note(db, user, text):
    # Same validation and field limits as the website, preserving the full text.
    text = normalize_bounded_text(text, label='Текст заметки', max_length=10151, required=True)
    first, separator, rest = text.partition('\n')
    first = first.rstrip('\r')
    if len(first) <= 60:
        title, content = first, rest if separator else None
    else:
        title, content = first[:59] + '…', text
    title = normalize_bounded_text(title, label='Заголовок заметки', max_length=150, required=True)
    normalize_bounded_text(content, label='Текст заметки', max_length=10000)
    note = Note(user_id=user.id, title=title, content=content, subject_id=None, link=None)
    db.add(note)
    db.flush()
    return note


def revision(note):
    fields = (note.title, note.content, note.link, note.subject_id, str(note.created_at))
    return sha256(repr(fields).encode()).hexdigest()


def missing():
    return '⚠️ Заметки уже нет или она недоступна.', keyboard([button('📝 Новая заметка', 'note_start')])


def _delete_action(db, user, action, site_url):
    parts = action.split(':')
    if len(parts) not in (2, 3) or not parts[1].isascii() or not parts[1].isdigit() or len(parts[1]) > 18:
        return missing()
    note_id = int(parts[1])
    key = f'note-delete:{user.id}:{note_id}'
    confirmation = state_row(db, key)
    # Owner is checked again here on every callback, including the final delete.
    note = db.query(Note).filter(Note.id == note_id, Note.user_id == user.id).populate_existing().with_for_update().first()
    if note is None:
        confirmation.data = {}
        return missing()
    if parts[0] == 'note_keep':
        confirmation.data = {}
        return saved_view(note, site_url, heading='📝 Заметка оставлена')
    if parts[0] == 'note_delete_confirm':
        data = confirmation.data
        if (len(parts) != 3 or data.get('token') != parts[2]
                or data.get('binding') != binding(user) or confirmation.expires_at <= utcnow()):
            return '⚠️ Подтверждение устарело.', saved_view(note, site_url)[1]
        if data.get('revision') == revision(note):
            db.delete(note)
            db.flush()
            confirmation.data = {}
            return '🗑 Заметка удалена', keyboard([button('📝 Ещё заметку', 'note_start')])
        heading = 'Заметка изменилась. Удалить текущую версию?'
    else:
        heading = 'Удалить эту заметку?'
    token = secrets.token_hex(6)
    confirmation.data = {'token': token, 'binding': binding(user), 'revision': revision(note)}
    confirmation.expires_at = utcnow() + TTL
    return (f'{heading}\n\n{preview(note)}', keyboard(
        [button('🗑 Да, удалить', f'note_delete_confirm:{note.id}:{token}')],
        [button('← Оставить', f'note_keep:{note.id}')],
    ))


def handle(db, user, *, telegram_user_id, action, argument, site_url, special_active=False, defer_prefix=False):
    """Return a reply tuple when notes consumed the action; otherwise return None.

    Called only after the bot's private-chat guard and identity resolution, and
    before conversational intents / task editing / natural-language parsing.
    The outer dialog lock and existing update transaction also cover this state.
    """
    prefix = PREFIX.fullmatch(argument.strip()) if action == 'text' else None
    key = f'note-flow:{telegram_user_id}'
    state = db.get(TelegramState, key)
    waiting = bool(state and state.data)
    if defer_prefix and not waiting:
        prefix = None  # An active search consumes text before explicit prefixes.
    note_action = action == 'note_start' or action.startswith(('note_cancel:', 'note_delete:', 'note_delete_confirm:', 'note_keep:'))
    cancel = action in {'cancel', 'add_task_cancel'} or (
        action == 'text' and argument.strip().casefold() in {'отмена', 'отменить', 'cancel', '❌ отмена', '❌ отменить'})
    if not note_action and not prefix and not (waiting and (action == 'text' or cancel)):
        return None
    if not user:
        return ('Сначала подключи Telegram в профиле Student Assistant.',
                keyboard([button('🔗 Подключить Telegram', 'connect')]))
    if special_active:
        if action == 'text' or cancel:
            return None  # A deadline-reschedule flow retains priority.
        if action == 'note_start':
            return 'Сначала заверши перенос задачи или отмени его: /cancel', keyboard([button('❌ Отменить', 'add_task_cancel')])
    if action.startswith(('note_delete:', 'note_delete_confirm:', 'note_keep:')):
        return _delete_action(db, user, action, site_url)
    if action.startswith('note_cancel:'):
        if not waiting or state.data.get('token') != action.partition(':')[2]:
            return expired()
        cancel = True
    if waiting and state.data.get('binding') != binding(user):
        state.data = {}
        waiting = False
        if action != 'note_start':
            return expired()
    if cancel and waiting:
        state.data = {}
        return '❌ Создание заметки отменено.', keyboard([button('📝 Новая заметка', 'note_start')])
    if action == 'note_start':
        state = state_row(db, key)
        token = secrets.token_hex(6)
        state.data = {'token': token, 'binding': binding(user)}
        state.expires_at = utcnow() + TTL
        return prompt(token)
    if waiting and state.expires_at <= utcnow():
        state.data = {}
        return expired()
    if action == 'text' and (waiting or prefix):
        if not waiting:
            state = state_row(db, key)
            state.data = {'token': secrets.token_hex(6), 'binding': binding(user)}
            state.expires_at = utcnow() + TTL
        try:
            note = create_note(db, user, prefix[1] if prefix else argument)
        except ValueError as error:
            return f'⚠️ {escape(str(error))}\n\nНапиши текст заметки одним сообщением.', prompt(state.data['token'])[1]
        state.data = {}
        return saved_view(note, site_url)
    return None
