# Student Assistant

Student Assistant is a study management project built with `FastAPI`, `Jinja2`, `SQLAlchemy`, `SQLite`, and `aiogram`.

The project combines:
- a web application for managing study data
- a Telegram bot for quick access to tasks and schedule

The main goal is to keep subjects, assignments, deadlines, notes, and schedule in one place.

## Features

- user registration and login
- dashboard with:
  - live clock
  - calendar widget
  - motivational quote
  - today overview
- subject management
- task management
- weekly schedule management
- notes management
- Telegram bot with basic commands

## Tech Stack

- Python
- FastAPI
- Jinja2
- SQLAlchemy
- SQLite
- aiogram
- Bootstrap 5

## Project Structure

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

## Requirements

- Python 3.11+ recommended
- Windows, Linux, or macOS

## Installation

### 1. Clone the repository

```bash
git clone <your-repo-url>
cd student_assistant_project
```

### 2. Create and activate a virtual environment

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

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## Running the Web App

Start the web application:

```bash
python run.py
```

Then open:

```text
http://127.0.0.1:8000
```

## Running the Telegram Bot

Create your bot in `@BotFather`, get the token, and set it as an environment variable.

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

## Telegram Bot Note

The current bot logic is simple:

- it searches the user by Telegram username
- your Telegram username should match your website username

Supported commands:

- `/start`
- `/help`
- `/today`
- `/tasks`

## Database

The project uses SQLite:

```text
student_assistant.db
```

Tables are created automatically on first start through SQLAlchemy.

## Useful Commands

### Run syntax check

```bash
python -m py_compile app\models.py app\database.py app\main.py app\routers\web.py bot\bot.py
```

### Run with local virtual environment on Windows

```powershell
venv\Scripts\python.exe run.py
venv\Scripts\python.exe -m bot.bot
```

## What to Upload to GitHub

You should upload:

- `app/`
- `bot/`
- `requirements.txt`
- `run.py`
- `README.md`
- `.env.example`

You should NOT upload:

- `venv/`
- `__pycache__/`
- `.env`
- local SQLite database if you do not want to publish test data

## Recommended .gitignore

```gitignore
venv/
__pycache__/
*.pyc
.env
student_assistant.db
```

## Current Status

Implemented and working in the web part:

- subjects
- tasks
- notes
- schedule
- editing in the interface
- updated dashboard design

Telegram bot:

- basic version only
- depends on matching Telegram username with website login

## Possible Improvements

- proper Telegram account linking
- password reset
- notifications and reminders
- deployment instructions
- tests
- Docker support
- admin panel

## License

This project currently has no explicit license.
If you plan to publish it publicly on GitHub, it is better to add a license file, for example `MIT`.
