# Student Assistant

Student Assistant — проект для организации учебы на базе `FastAPI`, `Jinja2`, `SQLAlchemy`, `SQLite` и `aiogram`.

Проект объединяет:
- веб-приложение для управления учебными данными;
- Telegram-бота для быстрого доступа к задачам и расписанию.

Цель проекта — хранить предметы, задания, дедлайны, заметки и расписание в одном месте.

## Возможности

- регистрация и вход пользователей;
- дашборд с:
  - живыми часами;
  - календарем;
  - мотивационной цитатой;
  - обзором на сегодня;
- управление предметами;
- управление задачами;
- управление расписанием;
- управление заметками;
- Telegram-бот с базовыми командами.

## Технологии

- Python
- FastAPI
- Jinja2
- SQLAlchemy
- SQLite
- aiogram
- Bootstrap 5

## Структура проекта

```text
student_assistant_project/
├── app/
│   ├── routers/
│   ├── static/
│   ├── templates/
│   ├── auth.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   └── utils.py
├── bot/
│   └── bot.py
├── requirements.txt
├── run.py
└── README.md
```

## Требования

- Python 3.11+ (рекомендуется);
- Windows, Linux или macOS.

## Установка

### 1. Клонирование репозитория

```bash
git clone <your-repo-url>
cd student_assistant_project
```

### 2. Создание и активация виртуального окружения

#### Windows PowerShell

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
```

#### Windows CMD

```cmd
python -m venv venv
venv\Scripts\activate.bat
```

#### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Установка зависимостей

```bash
pip install -r requirements.txt
```

## Быстрый запуск (почти без настроек)

### Windows (рекомендуется)

1. Установи Python 3.11+ (при установке включи `Add python.exe to PATH`).
2. Открой папку проекта.
3. Запусти файл `start_web.bat` двойным кликом.

Скрипт сам:
- создаст `venv` (если его нет);
- установит зависимости;
- запустит сайт.

### Linux / macOS

```bash
chmod +x start_web.sh
./start_web.sh
```

## Запуск веб-приложения

```bash
python run.py
```

После запуска открой:

```text
http://127.0.0.1:8000
```

## Запуск Telegram-бота

Создай бота в `@BotFather`, получи токен и передай его через переменную окружения.

### Windows PowerShell

```powershell
$env:BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
python -m bot.bot
```

### Windows CMD

```cmd
set BOT_TOKEN=YOUR_TELEGRAM_BOT_TOKEN
python -m bot.bot
```

### Linux / macOS

```bash
export BOT_TOKEN="YOUR_TELEGRAM_BOT_TOKEN"
python -m bot.bot
```

## Примечание по Telegram-боту

Текущая логика простая:
- бот ищет пользователя по Telegram username;
- Telegram username должен совпадать с логином на сайте.

Поддерживаемые команды:
- `/start`
- `/help`
- `/today`
- `/tasks`

## База данных

Используется SQLite:

```text
student_assistant.db
```

Таблицы создаются автоматически при первом запуске через SQLAlchemy.

## Полезные команды

### Проверка синтаксиса

```bash
python -m py_compile app\models.py app\database.py app\main.py app\routers\web.py bot\bot.py
```

### Запуск через локальное виртуальное окружение (Windows)

```powershell
venv\Scripts\python.exe run.py
venv\Scripts\python.exe -m bot.bot
```

## Что загружать на GitHub

Нужно загружать:
- `app/`
- `bot/`
- `requirements.txt`
- `run.py`
- `README.md`
- `.env.example`

Не нужно загружать:
- `venv/`
- `__pycache__/`
- `.env`
- локальную SQLite-базу, если не хочешь публиковать тестовые данные.

## Рекомендуемый `.gitignore`

```gitignore
venv/
__pycache__/
*.pyc
.env
student_assistant.db
```

## Текущий статус

Реализовано и работает в веб-части:
- предметы;
- задачи;
- заметки;
- расписание;
- редактирование в интерфейсе;
- обновленный дизайн дашборда.

Telegram-бот:
- базовая версия;
- зависит от совпадения Telegram username с логином на сайте.

## Возможные улучшения

- корректная привязка Telegram-аккаунта;
- восстановление пароля;
- уведомления и напоминания;
- инструкция по деплою;
- тесты;
- поддержка Docker;
- админ-панель.

## Лицензия

Сейчас у проекта нет явной лицензии.
Если планируешь публичную публикацию, лучше добавить файл лицензии, например `MIT`.
