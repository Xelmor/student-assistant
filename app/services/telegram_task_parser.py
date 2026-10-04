"""Deterministic Russian task parsing. No IO, clock reads or external services."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import re


MONTHS = dict(zip(('января февраля марта апреля мая июня июля августа сентября октября ноября декабря').split(), range(1, 13)))
WEEKDAYS = {
    'понедельник': 0, 'понедельнику': 0, 'понедельника': 0,
    'вторник': 1, 'вторнику': 1, 'вторника': 1,
    'среду': 2, 'среде': 2, 'среды': 2,
    'четверг': 3, 'четвергу': 3, 'четверга': 3,
    'пятницу': 4, 'пятнице': 4, 'пятницы': 4,
    'субботу': 5, 'субботе': 5, 'субботы': 5,
    'воскресенье': 6, 'воскресенью': 6, 'воскресенья': 6,
}
DATE_RE = re.compile(
    r'(?<![\w.\d-])(?:(?:до|к|на)\s+)?(?:'
    r'(?P<relative>послезавтра|завтра|сегодня)'
    r'|(?:во|в|к|до|на)\s+(?P<weekday>' + '|'.join(sorted(WEEKDAYS, key=len, reverse=True)) + r')'
    r'|(?P<iso>\d{4}-\d{2}-\d{2})'
    r'|(?P<numeric>\d{1,2}\.\d{1,2}(?:\.\d{4})?)'
    r'|(?P<day>\d{1,2})\s+(?P<month>' + '|'.join(MONTHS) + r')(?:\s+(?P<year>\d{4}))?'
    r')(?![\w\d-]|\.\d)', re.I,
)
TIME_RE = re.compile(r'(?<![\w\d])(?:(?:в|до)\s+(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?|(?P<barehour>\d{1,2}):(?P<bareminute>\d{2}))(?![\w\d:])', re.I)
PRIORITY_RE = re.compile(r'\b(?:(?P<urgent>срочно|важно)|(?P<level>высокий|средний|низкий)(?:\s+приоритет|(?=\s*[,!.]?\s*$)))\b', re.I)
PRIORITIES = {'высокий': 'high', 'средний': 'medium', 'низкий': 'low'}


@dataclass(frozen=True)
class ParsedTask:
    title: str
    deadline: datetime | None = None
    priority: str = 'medium'
    subject_ids: tuple[int, ...] = ()
    subject_title: str | None = None
    warning: str | None = None
    time_explicit: bool = False


def normalize(text: str) -> str:
    return ' '.join(text.casefold().replace('ё', 'е').split())


def conversational_intent(text: str) -> str | None:
    value = normalize(text).strip(' !?.…,')
    groups = {
        'greeting': {'привет', 'здравствуй', 'здравствуйте', 'хай', 'добрый день', 'доброе утро', 'добрый вечер'},
        'thanks': {'спасибо', 'спасибо большое', 'благодарю'},
        'help': {'помощь', 'помоги', 'что умеешь', 'что ты умеешь'},
        'cancel': {'отмена', 'отменить'},
    }
    return next((intent for intent, values in groups.items() if value in values), None)


def _clean_title(value: str) -> str:
    value = ' '.join(value.split()).strip(' ,;:—-.!')
    return value[:1].upper() + value[1:]


def _subject_word(word: str) -> str:
    if word in {'python', 'питон', 'питона', 'питону', 'питоне'}:
        return 'python'
    if word in {'прога', 'проге', 'прогу', 'проги'}:
        return 'программирование'
    return word


def _stem(word: str) -> str:
    word = _subject_word(word)
    for suffix in ('ому', 'ему', 'ого', 'его', 'ии', 'ия', 'ий', 'ый', 'ая', 'ой', 'ые', 'ых', 'ам', 'ям', 'а', 'ы', 'и'):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[:-len(suffix)]
    return word


def _subject_match(phrase: str, name: str) -> bool:
    words = re.findall(r'[\w]+', normalize(name))
    supplied = re.findall(r'[\w]+', normalize(phrase))
    if not words or not supplied:
        return False
    acronym = ''.join(word[0] for word in words if word not in {'и', 'по', 'в', 'на'})
    if len(acronym) >= 2 and ''.join(supplied) == acronym:
        return True
    # Full names and inflected first words (e.g. «по философии»). Ambiguity is
    # resolved against the complete caller-supplied subject list, never globally.
    return len(supplied) <= len(words) and all(_stem(a) == _stem(b) for a, b in zip(supplied, words))


def parse_task(text: str, *, now: datetime, subjects: list[tuple[int, str]] = ()) -> ParsedTask | None:
    """`now` is explicitly supplied user-local time; stored deadlines are local naive values.

    A date without a year belongs to the current year; past dates are warned
    about, never silently shifted. Date-only deadlines use 23:59.
    """
    text = ' '.join(text.split())
    if not text or len(text) > 500:
        raise ValueError('Напиши задачу короче — до 500 символов.')
    if conversational_intent(text):
        return None
    lowered = normalize(text)
    if '?' in text or re.match(r'^(как|почему|кто|где|зачем|когда|что|ты|ок|ага|да|нет)\b', lowered):
        return None
    local_now = now.replace(tzinfo=None)
    work = text
    priorities = list(PRIORITY_RE.finditer(work))
    values = {('high' if match['urgent'] else PRIORITIES[match['level'].lower()]) for match in priorities}
    if len(values) > 1:
        return ParsedTask(_clean_title(text), warning='Укажи один приоритет задачи.')
    priority = next(iter(values), 'medium')
    work = PRIORITY_RE.sub(' ', work)
    date_tail = None
    matches = list(DATE_RE.finditer(work))
    warning = None
    target = None
    if len(matches) > 1:
        return ParsedTask(_clean_title(text), warning='Укажи один дедлайн — в сообщении несколько дат.')
    if matches:
        match = matches[0]
        try:
            if match['relative']:
                target = local_now.date() + timedelta(days={'сегодня': 0, 'завтра': 1, 'послезавтра': 2}[match['relative'].lower()])
            elif match['weekday']:
                delta = (WEEKDAYS[match['weekday'].lower()] - local_now.weekday()) % 7 or 7
                target = local_now.date() + timedelta(days=delta)
            elif match['iso']:
                target = datetime.strptime(match['iso'], '%Y-%m-%d').date()
            elif match['numeric']:
                parts = [int(part) for part in match['numeric'].split('.')]
                target = datetime(parts[2] if len(parts) == 3 else local_now.year, parts[1], parts[0]).date()
            else:
                target = datetime(int(match['year'] or local_now.year), MONTHS[match['month'].lower()], int(match['day'])).date()
        except ValueError:
            return ParsedTask(_clean_title(text), warning='Такой даты нет. Измени дедлайн.')
        date_tail = work[match.end():]
        work = work[:match.start()] + ' ' + work[match.end():]
    times = list(TIME_RE.finditer(work))
    if not times and target and date_tail and re.fullmatch(r'\s*\d{1,2}\s*[.!]?\s*', date_tail):
        # Bare hours are only unambiguous next to an explicit date and at the
        # end. Preserve numbers in task names such as «решить задачу 18».
        bare = re.search(r'(?<![\w№])\b(?P<hour>\d{1,2})\s*[.!]?\s*$', work)
        if bare:
            times = [bare]
    if len(times) > 1:
        return ParsedTask(_clean_title(text), warning='Укажи одно время дедлайна.')
    hour, minute = 23, 59
    if times:
        match = times[0]
        groups = match.groupdict()
        hour = int(groups.get('hour') or groups.get('barehour'))
        minute = int(groups.get('minute') or groups.get('bareminute') or 0)
        if hour > 23 or minute > 59:
            return ParsedTask(_clean_title(text), warning='Время должно быть от 00:00 до 23:59.')
        target = target or local_now.date()
        work = work[:match.start()] + ' ' + work[match.end():]
    deadline = datetime.combine(target, time(hour, minute)) if target else None
    if deadline and deadline < local_now:
        warning = 'Это время сегодня уже прошло.' if deadline.date() == local_now.date() else 'Эта дата уже прошла. Измени дедлайн.'
    subject_ids, subject_title = (), None
    # Remove only an explicit, recognized «по …» phrase. Unknown subjects stay
    # in the title rather than losing user-provided meaning.
    for marker in re.finditer(r'\b(?:по|для)\s+', work, re.I):
        tail = work[marker.end():]
        words = list(re.finditer(r'[\w]+', tail))[:8]
        for count in range(len(words), 0, -1):
            end = marker.end() + words[count - 1].end()
            phrase = work[marker.end():end]
            found = tuple(sid for sid, name in subjects if _subject_match(phrase, name))
            if found:
                subject_ids = found
                subject_title = _clean_title(work[:marker.start()] + ' ' + work[end:])
                if len(found) == 1:
                    work = subject_title
                break
        if subject_ids:
            break
    if not subject_ids:
        # Implicit mentions only attach a complete subject name. Keep every
        # word in the title; broad prefixes/acronyms require «по» or «для».
        tokens = [_subject_word(word) for word in re.findall(r'[\w]+', normalize(work))]
        found = []
        for sid, name in subjects:
            name_tokens = [_subject_word(word) for word in re.findall(r'[\w]+', normalize(name))]
            if name_tokens and any(tokens[start:start + len(name_tokens)] == name_tokens for start in range(len(tokens))):
                found.append(sid)
        subject_ids = tuple(found)
    title = _clean_title(work)
    if not title or not re.search(r'[а-яa-z]', title, re.I):
        raise ValueError('Добавь название задачи — что нужно сделать?')
    if len(title) > 150:
        raise ValueError('Название задачи должно быть не длиннее 150 символов.')
    if not deadline and not values and not subject_ids and len(title.split()) < 2:
        return None
    return ParsedTask(title, deadline, priority, subject_ids, subject_title, warning, bool(times))
