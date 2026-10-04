"""Desktop/mobile search via real webhook and DB, using a test-only Telegram viewer."""
from dataclasses import asdict, replace
from datetime import UTC, datetime, time
from uuid import uuid4
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from playwright.sync_api import expect
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.main import app
from app.models import Note, ScheduleItem, Subject, Task, User
from app.services.telegram_digest import digest_local_datetime
from app.web.routes import telegram as webhook

pytestmark = pytest.mark.e2e
NOW = datetime(2026, 10, 2, 12, tzinfo=UTC)
VIEWER = '''
<style>
body {font:16px system-ui;margin:12px;background:#eef2f6}
main {max-width:36rem;margin:auto;padding:16px;background:white;border-radius:12px}
#message {white-space:pre-wrap;overflow-wrap:anywhere}
.row {display:flex;gap:8px;margin-top:8px}button {flex:1;min-width:0;padding:12px;font:inherit;cursor:pointer}
input {box-sizing:border-box;width:100%;margin-top:16px;padding:10px;font:inherit}
</style>
<main><article id="message"></article><section id="keyboard"></section>
<form id="composer"><input aria-label="Сообщение"><button>Отправить</button></form></main>
<script>
async function telegramAction(action, text=false) {
  const response = await fetch('/__telegram_test__/callback', {
    method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action,text})
  });
  if (!response.ok) throw new Error('Test webhook failed');
  const reply = await response.json();
  document.querySelector('#message').innerHTML = reply.text;
  const keyboard = document.querySelector('#keyboard'); keyboard.replaceChildren();
  for (const row of reply.reply_markup.inline_keyboard) {
    const div = document.createElement('div'); div.className = 'row';
    for (const item of row) {
      const button = document.createElement('button'); button.textContent = item.text;
      button.onclick = () => telegramAction(item.callback_data); div.append(button);
    }
    keyboard.append(div);
  }
}
document.querySelector('#composer').onsubmit = async event => {
  event.preventDefault(); const input = document.querySelector('input');
  await telegramAction(input.value, true); input.value='';
};
</script>
'''


@pytest.mark.parametrize('width', [1440, 390])
def test_search_results_retry_empty_back_and_prefix(browser, telegram_e2e_runtime, width):
    context = browser.new_context(base_url=telegram_e2e_runtime['base_url'], viewport={'width': width, 'height': 1000})
    page = context.new_page()
    engine = create_engine(f"sqlite:///{telegram_e2e_runtime['database_path']}", connect_args={'check_same_thread': False})
    previous = dict(app.dependency_overrides)
    client = TestClient(app)
    errors = []
    page.on('pageerror', lambda error: errors.append(str(error)))
    try:
        page.goto('/')
        csrf = page.locator('input[name="csrf_token"]').first.input_value()
        name = 'Search E2E ' + uuid4().hex[:8]
        assert page.request.post('/start', form={'display_name': name, 'csrf_token': csrf}).ok
        with Session(engine) as db:
            user = db.query(User).filter_by(display_name=name).one()
            user_id, telegram_id = user.id, 120000 + user.id
            user.telegram_user_id = user.telegram_chat_id = telegram_id
            user.telegram_linked_at = NOW.replace(tzinfo=None)
            user.telegram_morning_digest_timezone = 'Europe/Moscow'
            db.add(Task(user_id=user_id, title='Тест по базам данных', deadline=datetime(2026,10,6,18)))
            db.add(Note(user_id=user_id, title='Конспект теста', content='Оконные функции баз данных'))
            subject = Subject(user_id=user_id, name='Базы данных тест')
            db.add(subject); db.flush()
            db.add(ScheduleItem(user_id=user_id, subject_id=subject.id, weekday=0, start_time=time(10,40), end_time=time(12,10), room='301'))
            db.commit()

        def database():
            with Session(engine) as db:
                yield db
        app.dependency_overrides[get_db] = database
        sent, sequence = [], 0

        def bridge(route):
            nonlocal sequence
            sequence += 1
            payload = route.request.post_data_json
            action = payload['action']
            message = {'chat': {'id':telegram_id, 'type':'private'}, 'from':{'id':telegram_id}}
            update = {'update_id':user_id * 10000 + sequence}
            if payload.get('text') or action.startswith('/'):
                update['message'] = {**message, 'text':action}
            else:
                update['callback_query'] = {'id':str(sequence), 'from':message['from'], 'data':action, 'message':message}
            response = client.post(webhook.settings.telegram_webhook_path, json=update,
                                   headers={'X-Telegram-Bot-Api-Secret-Token':'search-e2e-secret'})
            assert response.status_code == 200
            route.fulfill(status=200, json=asdict(sent[-1]))

        isolated_settings = replace(webhook.settings, telegram_use_webhook=True, telegram_bot_token='isolated-token', telegram_webhook_secret='search-e2e-secret')
        with patch.object(webhook, 'settings', isolated_settings), patch.object(webhook, 'send_telegram_message', side_effect=sent.append), patch('app.services.telegram_bot.digest_local_datetime', side_effect=lambda user: digest_local_datetime(user, NOW)):
            page.route('**/__telegram_test__/callback', bridge)
            page.set_content(VIEWER)
            page.evaluate("telegramAction('/start')")
            page.get_by_role('button', name='🔎 Поиск', exact=True).click()
            expect(page.locator('#message')).to_contain_text('Что найти?')
            page.get_by_role('textbox', name='Сообщение').fill('тест')
            page.get_by_role('button', name='Отправить', exact=True).click()
            for found in ['Тест по базам данных', 'Конспект теста', 'Базы данных тест', 'Ауд. 301']:
                expect(page.locator('#message')).to_contain_text(found)
            page.get_by_role('button', name='🔎 Искать ещё', exact=True).click()
            page.get_by_role('textbox', name='Сообщение').fill('несуществующийзапрос')
            page.get_by_role('button', name='Отправить', exact=True).click()
            expect(page.locator('#message')).to_contain_text('ничего не найдено')
            page.get_by_role('button', name='← Главное меню', exact=True).click()
            expect(page.get_by_role('button', name='🔎 Поиск', exact=True)).to_be_visible()
            page.get_by_role('textbox', name='Сообщение').fill('поиск: тест')
            page.get_by_role('button', name='Отправить', exact=True).click()
            expect(page.locator('#message')).to_contain_text('Тест по базам данных')
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        with Session(engine) as db:
            assert db.query(Task).filter_by(user_id=user_id).count() == 1
            assert db.query(Note).filter_by(user_id=user_id).count() == 1
        assert errors == []
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)
        client.close()
        context.close()
        engine.dispose()
