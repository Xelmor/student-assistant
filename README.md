# Student Assistant

Student Assistant - учебный проект на FastAPI. В проекте уже есть сайт для работы с предметами, задачами, заметками и недельным расписанием. В этом обновлении добавлен Telegram-бот как отдельный сервис, который использует те же данные пользователя через backend API сайта.

## Краткий анализ текущей архитектуры

- Сайт построен на `FastAPI + Jinja2 + SQLAlchemy`.
- Авторизация на сайте session-based: пользователь логинится через web-форму, а сервер хранит `user_id` в сессии.
- Основные сущности уже есть в БД и моделях: `User`, `Subject`, `Task`, `ScheduleItem`, `Note`.
- CRUD по этим сущностям уже реализован в HTML-роутах.
- До изменений в проекте не было полноценного JSON API для внешнего клиента, поэтому для Telegram-бота добавлен минимальный API-слой без дублирования моделей и учебных данных.

## Архитектура интеграции сайта и Telegram-бота

Используется схема `site backend <-> bot service <-> Telegram`.

- Сайт остаётся источником истины для пользователей, предметов, задач, заметок и расписания.
- Telegram-бот не хранит отдельную базу учебных сущностей.
- Бот получает данные только через API сайта.
- Для доступа к API бот использует внутренний shared token `TELEGRAM_BOT_API_TOKEN`.
- Привязка Telegram безопасная и не требует отправки пароля от сайта в бота:
  1. пользователь входит на сайт;
  2. открывает профиль;
  3. получает одноразовый 6-значный код;
  4. в Telegram вводит `/login` и отправляет код;
  5. backend связывает `telegram_chat_id` с существующим `User`.

Это безопаснее, чем логин по паролю через чат, и хорошо подходит для учебного проекта.

## Что добавлено в backend

- новые поля у `User` для Telegram-привязки и настроек уведомлений;
- автоматическое добавление недостающих колонок при старте приложения;
- API endpoints для Telegram-бота;
- генерация одноразового кода привязки в профиле;
- блок Telegram в личном кабинете.

## API endpoints для бота

### Привязка Telegram

- `GET /api/v1/telegram/link/code`
  Возвращает текущий одноразовый код привязки для авторизованного пользователя сайта.
- `POST /api/v1/telegram/link/code`
  Генерирует новый код привязки для авторизованного пользователя сайта.
- `POST /api/v1/telegram/link/confirm`
  Используется ботом. Принимает `code`, `chat_id`, `telegram_username` и привязывает Telegram к аккаунту сайта.

### Данные пользователя

- `GET /api/v1/telegram/me`

### Учебные сущности

- `GET /api/v1/telegram/subjects`
- `GET /api/v1/telegram/tasks`
- `POST /api/v1/telegram/tasks`
- `GET /api/v1/telegram/deadlines`
- `GET /api/v1/telegram/notes`
- `GET /api/v1/telegram/schedule`

### Напоминания

- `GET /api/v1/telegram/reminders`
- `PUT /api/v1/telegram/reminders`

Во все bot-to-site запросы бот передаёт:

- заголовок `X-Bot-Api-Token: <TELEGRAM_BOT_API_TOKEN>`
- query-параметр `chat_id=<telegram_chat_id>`

## Структура Telegram-бота

```text
bot/
  config.py
  api_client.py
  main.py
  webhook_app.py
  handlers/
    common.py
    login.py
    reminders.py
    tasks.py
  keyboards/
    common.py
  services/
    formatters.py
```

Слои:

- `config` - чтение настроек из `.env`;
- `api_client` - запросы к backend API сайта;
- `handlers` - команды, меню и FSM-сценарии;
- `keyboards` - reply и inline клавиатуры;
- `services` - форматирование данных и вспомогательная логика.

## Функции бота

- `/start` - приветствие и главное меню;
- `/help` - список команд;
- `/login` - привязка Telegram к аккаунту сайта по одноразовому коду;
- `Моё расписание` - расписание на сегодня и на неделю;
- `Мои задачи` - активные задачи;
- `Ближайшие дедлайны` - дедлайны по возрастанию даты;
- `Предметы` - список предметов;
- `Заметки` - последние заметки;
- `Добавить задачу` - создание задачи через FSM;
- `Напоминания` - включение и выключение настроек через inline-кнопки.

## Настройка .env

Скопируй шаблон:

```powershell
Copy-Item .env.example .env
```

Обязательные переменные:

```env
SECRET_KEY=replace_with_a_unique_random_string_at_least_32_chars_long
TELEGRAM_BOT_API_TOKEN=replace_with_internal_shared_token
TELEGRAM_BOT_TOKEN=сюда_токен_из_BotFather
TELEGRAM_BOT_API_BASE_URL=http://localhost:8000
```

## Как создать бота через BotFather

1. Открой Telegram и найди `@BotFather`.
2. Отправь команду `/newbot`.
3. Укажи имя бота.
4. Укажи username, который заканчивается на `bot`.
5. BotFather вернёт токен.
6. Вставь этот токен в `.env` в переменную `TELEGRAM_BOT_TOKEN`.

## Локальный запуск сайта

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

Сайт по умолчанию будет доступен на `http://127.0.0.1:8000`.

## Локальный запуск Telegram-бота в polling

В отдельном терминале:

```powershell
venv\Scripts\Activate.ps1
python -m bot.main
```

Для локальной разработки это основной режим.

## Запуск webhook-варианта

Нужно задать в `.env`:

```env
TELEGRAM_USE_WEBHOOK=true
TELEGRAM_WEBHOOK_BASE_URL=https://your-domain.example.com
TELEGRAM_WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=your_webhook_secret
TELEGRAM_BOT_PORT=8081
```

Запуск:

```powershell
python -m bot.webhook_app
```

Webhook URL получится таким:

```text
https://your-domain.example.com/telegram/webhook
```

Если сервер стоит за reverse proxy, нужно пробросить этот путь на сервис бота.

## Docker

### Сборка и запуск через docker compose

```powershell
docker compose up --build
```

Сервисы:

- `web` - сайт FastAPI;
- `bot` - Telegram-бот в polling-режиме.

Если нужен webhook, можно поменять команду сервиса `bot` на:

```yaml
command: python -m bot.webhook_app
```

## Что именно использует бот из сайта

Бот не создаёт отдельные таблицы для предметов, задач, заметок и расписания. Он работает с уже существующими моделями:

- `User`
- `Subject`
- `Task`
- `ScheduleItem`
- `Note`

Дополнительно в `User` хранятся только данные интеграции Telegram:

- `telegram_chat_id`
- `telegram_username`
- `telegram_link_code`
- `telegram_link_code_expires_at`
- `telegram_linked_at`
- настройки напоминаний

## Проверка

Минимальная проверка после установки зависимостей:

```powershell
python -m unittest
```

## Важные замечания

- Сейчас реализован polling для локального запуска и подготовлен отдельный webhook entrypoint для deploy.
- Напоминания в этой версии хранятся как настройки пользователя. Планировщик фактической рассылки не добавлялся, потому что в задаче требовались прежде всего API, привязка и UX управления настройками.
- Если понадобится, следующим шагом можно добавить фоновый scheduler, который будет рассылать уведомления о дедлайнах и ближайших парах.
