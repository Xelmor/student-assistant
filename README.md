# Student Assistant

Student Assistant is a FastAPI web app for managing subjects, tasks, notes, schedule, and calendar data in one place.

## Stack

- FastAPI
- Jinja2
- SQLAlchemy
- SQLite for local development
- PostgreSQL for production

## Features

- registration and login
- dashboard
- subjects
- tasks
- weekly schedule
- calendar
- notes
- profile editing
- password reset by email
- JSON and CSV data export
- JSON data import

## Local run

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

The site is available at `http://127.0.0.1:8000`.

## Environment

Copy the example file first:

```powershell
Copy-Item .env.example .env
```

Minimum required variable:

```env
SECRET_KEY=replace_with_a_unique_random_string_at_least_32_chars_long
```

For production on Render:

```env
APP_ENV=production
COOKIE_SECURE=true
DATABASE_URL=postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
HOST=0.0.0.0
PORT=10000
RELOAD=false
ALLOW_LOCAL_PRIVATE_DATA=false
SECRET_KEY=replace_with_a_unique_random_string_at_least_32_chars_long
```

## Docker

```powershell
docker compose up --build
```

## Check

```powershell
python -m unittest
```
