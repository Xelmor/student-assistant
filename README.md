# Student Assistant

Student Assistant - это веб-приложение на FastAPI для учебного планирования. Проект объединяет предметы, задачи, заметки, расписание, календарь и инструменты резервного копирования в одном интерфейсе.

## Что умеет проект

- регистрация, вход и выход из аккаунта
- восстановление и смена пароля по email
- личный кабинет с редактированием профиля
- управление предметами
- управление задачами с приоритетом, сложностью, дедлайнами и статусом выполнения
- повторяющиеся задачи: ежедневно, еженедельно и каждые N дней
- ведение заметок
- управление недельным расписанием
- календарь учебной нагрузки
- экспорт данных в `JSON`, `CSV` и календарь `ICS`
- импорт данных из `JSON`
- адаптивный веб-интерфейс для десктопа и смартфонов
- PWA-элементы: `manifest`, service worker, иконки

## Стек

- Python 3.12+
- FastAPI
- Jinja2
- SQLAlchemy
- SQLite для локальной разработки
- PostgreSQL для production
- Uvicorn

## Структура проекта

```text
app/
  core/        конфиг, БД, безопасность, время
  models/      SQLAlchemy-модели
  services/    бизнес-логика, экспорт, импорт, календарь, email
  web/         HTML-роуты, шаблоны и зависимости
  static/      CSS, JS, PWA-файлы, иконки
tests/         smoke-тесты
run.py         точка запуска приложения
requirements.txt
.env.example
```

## Основные сущности

- `User` - пользователь
- `Subject` - предмет
- `Task` - задача
- `ScheduleItem` - элемент расписания
- `Note` - заметка

## Локальный запуск

1. Создай виртуальное окружение:

```powershell
python -m venv venv
```

2. Активируй его:

```powershell
venv\Scripts\Activate.ps1
```

3. Установи зависимости:

```powershell
pip install -r requirements.txt
```

4. Создай `.env`:

```powershell
Copy-Item .env.example .env
```

5. Запусти приложение:

```powershell
python run.py
```

Сайт по умолчанию будет доступен по адресу `http://127.0.0.1:8000`.

## Переменные окружения

Базовый локальный набор:

```env
APP_ENV=development
SECRET_KEY=replace_with_a_unique_random_string_at_least_32_chars_long
COOKIE_SECURE=false
DATABASE_URL=sqlite:///./student_assistant.db
HOST=0.0.0.0
PORT=8000
RELOAD=false
APP_TIMEZONE=Europe/Moscow
ALLOW_LOCAL_PRIVATE_DATA=true
```

Email для восстановления пароля:

```env
SMTP_HOST=
SMTP_PORT=587
SMTP_USERNAME=
SMTP_PASSWORD=
SMTP_FROM_EMAIL=
SMTP_FROM_NAME=Student Assistant
SMTP_STARTTLS=true
SMTP_SSL=false
PASSWORD_RESET_TOKEN_TTL_SECONDS=3600
```

Дополнительные переменные, оставленные в шаблоне окружения:

```env
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5-mini
OPENAI_TIMEOUT_SECONDS=30
AI_INPUT_MAX_LENGTH=2500
```

Сейчас README фиксирует текущее состояние проекта как веб-приложения. Если эти переменные будут использованы в будущих фичах, их уже не нужно будет заново добавлять в шаблон.

## Production и Render

Для деплоя на Render рекомендуется использовать PostgreSQL. Приложение должно слушать значение из переменной `PORT`; на Render её обычно задаёт сама платформа, поэтому не стоит завязываться на фиксированное значение вроде `10000`.

Минимальный production-набор:

```env
APP_ENV=production
SECRET_KEY=replace_with_a_unique_random_string_at_least_32_chars_long
COOKIE_SECURE=true
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
HOST=0.0.0.0
PORT=8000
RELOAD=false
ALLOW_LOCAL_PRIVATE_DATA=false
```

Настройки сервиса в Render:

- `Build Command`: `pip install -r requirements.txt`
- `Start Command`: `python run.py`

Если используешь Render PostgreSQL:

1. Создай базу данных в Render.
2. Скопируй `External Database URL`.
3. Вставь её в `DATABASE_URL`.
4. Укажи production-переменные окружения.
5. Запусти redeploy.

## Экспорт и импорт данных

В профиле доступны:

- экспорт в `JSON` для полного бэкапа и последующего восстановления
- экспорт в `CSV` в виде zip-архива
- импорт из ранее выгруженного `JSON`

Поддерживаются два режима импорта:

- `merge` - добавить данные к существующим
- `replace` - полностью заменить пользовательские данные

## Календарь

Раздел календаря поддерживает:

- просмотр месяца
- компактный недельный режим
- объединение дедлайнов и расписания на одной странице
- экспорт учебного календаря в `.ics`

## Безопасность и поведение приложения

- используется session-based авторизация
- в `development` и `test` при пустом или слишком коротком `SECRET_KEY` используется локальный fallback-ключ, но для production `SECRET_KEY` обязателен и должен быть длиной не менее 32 символов
- при `APP_ENV=production` переменная `COOKIE_SECURE` должна быть `true`
- для SQLite используется локальный файл `student_assistant.db`
- в production лучше использовать PostgreSQL, чтобы не терять данные при redeploy

## Проверка проекта

Минимальная проверка:

```powershell
python -m pytest
```

Тест проверяет:

- что приложение импортируется
- что основные роуты существуют
- что шаблоны на месте
- что базовые CSS-файлы подключены

## Docker

Локальный запуск через Docker Compose:

```powershell
docker compose up --build
```

## Текущее состояние

Проект сейчас ориентирован на веб-интерфейс. Telegram-интеграция из кода удалена, и README описывает уже актуальную, очищенную версию приложения.
