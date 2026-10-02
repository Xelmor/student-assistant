"""Desktop/mobile callback journey through real webhook + DB, with fake Telegram transport.

The HTML is a test-only inline-keyboard viewer, not the Telegram client. Browser
requests are bridged to the application's webhook; no production UI is added.
"""
from dataclasses import asdict, replace
from datetime import UTC, datetime
from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models import Task, TelegramState, User
from app.services.telegram_digest import digest_local_datetime
from app.web.routes import telegram as webhook
from telegram_bot.scheduler import process_evening_digests

pytestmark = pytest.mark.e2e
NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)  # Preview at 15:00 Moscow.

VIEWER = '''
<style>
body {font:16px system-ui;margin:12px;background:#eef2f6}
main {max-width:36rem;margin:auto;padding:16px;background:white;border-radius:12px}
#message {white-space:pre-wrap;overflow-wrap:anywhere}
.row {display:flex;gap:8px;margin-top:8px}button {flex:1;min-width:0;padding:12px;font:inherit;cursor:pointer}
</style>
<main><article id="message"></article><section id="keyboard"></section></main>
<script>
async function telegramAction(action) {
  const response = await fetch('/__telegram_test__/callback', {
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})
  });
  if (!response.ok) throw new Error('Test webhook failed');
  const reply = await response.json();
  document.querySelector('#message').innerHTML = reply.text;
  const keyboard = document.querySelector('#keyboard');
  keyboard.replaceChildren();
  for (const row of reply.reply_markup.inline_keyboard) {
    const div = document.createElement('div'); div.className = 'row';
    for (const item of row) {
      const button = document.createElement('button'); button.textContent = item.text;
      button.onclick = () => telegramAction(item.callback_data); div.append(button);
    }
    keyboard.append(div);
  }
}
</script>
'''


@pytest.mark.parametrize('width', [1440, 390])
def test_evening_settings_preview_and_back(browser, telegram_e2e_runtime, width):
    context = browser.new_context(base_url=telegram_e2e_runtime['base_url'], viewport={'width': width, 'height': 1000})
    page = context.new_page()
    engine = create_engine(f"sqlite:///{telegram_e2e_runtime['database_path']}", connect_args={'check_same_thread': False})
    previous = dict(app.dependency_overrides)
    client = TestClient(app)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        # Create a real passwordless website user before linking the test Telegram identity.
        page.goto('/')
        csrf = page.locator('input[name="csrf_token"]').first.input_value()
        name = 'Evening E2E ' + uuid4().hex[:8]
        assert page.request.post('/start', form={'display_name': name, 'csrf_token': csrf}).ok
        with Session(engine) as db:
            user = db.query(User).filter_by(display_name=name).one()
            user_id = user.id
            telegram_id = 90000 + user_id
            user.telegram_user_id = user.telegram_chat_id = telegram_id
            user.telegram_linked_at = NOW.replace(tzinfo=None)
            user.telegram_morning_digest_timezone = 'Europe/Moscow'
            db.add(Task(user_id=user_id, title='Практика E2E', deadline=datetime(2026, 10, 3, 18)))
            db.commit()

        def database():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        sent = []
        sequence = 0
        def bridge(route):
            nonlocal sequence
            sequence += 1
            action = route.request.post_data_json['action']
            message = {'chat': {'id': telegram_id, 'type': 'private'}, 'from': {'id': telegram_id}}
            update = {'update_id': user_id * 10000 + sequence}
            if action.startswith('/'):
                update['message'] = {**message, 'text': action}
            else:
                update['callback_query'] = {'id': str(sequence), 'from': message['from'], 'data': action, 'message': message}
            response = client.post(webhook.settings.telegram_webhook_path, json=update,
                                   headers={'X-Telegram-Bot-Api-Secret-Token': 'evening-e2e-secret'})
            assert response.status_code == 200
            route.fulfill(status=200, json=asdict(sent[-1]))

        isolated_settings = replace(webhook.settings, telegram_use_webhook=True, telegram_bot_token='isolated-token', telegram_webhook_secret='evening-e2e-secret')
        with patch.object(webhook, 'settings', isolated_settings), patch.object(webhook, 'send_telegram_message', side_effect=sent.append), patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, NOW)):
            page.route('**/__telegram_test__/callback', bridge)
            page.set_content(VIEWER)
            page.evaluate("telegramAction('/start')")
            page.get_by_role('button', name='⚙️ Настройки', exact=True).click()
            page.get_by_role('button', name='🌙 Вечерняя сводка', exact=True).click()
            expect(page.locator('#message')).to_contain_text('Статус: выключена')
            page.get_by_role('button', name='🔔 Включить', exact=True).click()
            expect(page.locator('#message')).to_contain_text('Статус: включена')
            page.get_by_role('button', name='🕘 Изменить время', exact=True).click()
            page.get_by_role('button', name='✅ 21:00', exact=True).click()
            page.get_by_role('button', name='← Назад', exact=True).click()
            page.get_by_role('button', name='🧪 Показать сейчас', exact=True).click()
            expect(page.locator('#message')).to_contain_text('Итоги дня')
            expect(page.locator('#message')).to_contain_text('Практика E2E · завтра до 18:00')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            page.get_by_role('button', name='← Назад', exact=True).click()
            expect(page.locator('#message')).to_contain_text('Вечерняя сводка')
            page.get_by_role('button', name='← Назад', exact=True).click()
            expect(page.locator('#message')).to_contain_text('⚙️ Настройки')

        with Session(engine) as db:
            assert db.get(TelegramState, f'evening-settings:{user_id}').data == {'enabled': True, 'hour': 21}
            assert db.get(TelegramState, f'evening-digest:{user_id}:2026-10-02') is None
            delivered = []
            assert process_evening_digests(db, now_utc=NOW.replace(hour=18), send_message=delivered.append) == 1
            assert process_evening_digests(db, now_utc=NOW.replace(hour=18, minute=2), send_message=delivered.append) == 0
            assert len(delivered) == 1
            assert len(delivered[0].reply_markup['inline_keyboard']) == 2
            # Keep the module-scoped runtime independent between viewport cases.
            row = db.get(TelegramState, f'evening-settings:{user_id}')
            row.data = {**row.data, 'enabled': False}
            db.commit()
        assert errors == []
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        client.close()
        context.close()
        engine.dispose()
