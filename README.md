# Student Assistant

Student Assistant это веб-приложение для учебы и личного планирования. В одном месте собраны задачи, заметки, расписание, календарь и профиль пользователя.

## Для чего нужен проект

Приложение помогает держать под контролем учебную нагрузку и не распыляться между разными сервисами. Оно подходит для локального использования и для развертывания на сервере.

## Основные возможности

- регистрация, вход и восстановление пароля
- управление задачами с дедлайнами, приоритетами и повторениями
- ведение заметок
- расписание занятий
- календарь с объединением задач и расписания
- профиль пользователя
- экспорт и импорт данных
- установка как PWA на телефон или компьютер

## Что нужно для запуска

- Python 3.12 или новее
- `pip`
- для локального запуска достаточно SQLite
- для production рекомендуется PostgreSQL

## Быстрый запуск

### Windows PowerShell

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python run.py
```

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run.py
```

После запуска приложение обычно доступно по адресу `http://127.0.0.1:8000`.

## Минимальная настройка `.env`

Основные переменные:

| Переменная | Для чего нужна | Пример |
| --- | --- | --- |
| `APP_ENV` | режим приложения | `development` |
| `SECRET_KEY` | ключ для сессий | длинная случайная строка |
| `DATABASE_URL` | подключение к базе данных | `sqlite:///./data/student_assistant.db` |
| `HOST` | адрес запуска | `0.0.0.0` |
| `ALLOWED_HOSTS` | разрешённые Host-заголовки | `localhost,127.0.0.1` |
| `PUBLIC_BASE_URL` | публичный HTTPS origin для reset-ссылок | `https://example.com` |
| `PORT` | порт запуска | `8000` |
| `RELOAD` | автоперезапуск в разработке | `false` |
| `COOKIE_SECURE` | защищенные cookie | `false` |
| `SESSION_MAX_AGE_SECONDS` | срок session-cookie в секундах | `43200` |
| `APP_TIMEZONE` | часовой пояс | `Europe/Moscow` |

Если нужен сброс пароля по email, дополнительно настраиваются SMTP-переменные в `.env`.

## Запуск через Docker

```powershell
docker compose up --build
```

## Тесты

```powershell
python -m pytest
```

## Production

Для production рекомендуется:

- использовать PostgreSQL
- задать уникальный длинный `SECRET_KEY`
- включить `COOKIE_SECURE=true`
- использовать `APP_ENV=production`
- не хардкодить порт, а брать его из `PORT`

Минимальный пример:

```env
APP_ENV=production
SECRET_KEY=replace_with_a_unique_random_string_at_least_32_chars_long
COOKIE_SECURE=true
SESSION_MAX_AGE_SECONDS=43200
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
HOST=0.0.0.0
ALLOWED_HOSTS=student-assistant.example.com
PUBLIC_BASE_URL=https://student-assistant.example.com
PORT=8000
RELOAD=false
```

## Деплой

Подробные шаги по развертыванию вынесены отдельно: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)

## Примечание

В этом `README` намеренно нет описания внутренней архитектуры, приватных настроек и служебных деталей реализации. Здесь оставлена только информация, которая нужна для запуска, использования и базового развертывания проекта.
