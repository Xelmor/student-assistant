# Student Assistant

Student Assistant is a web app for organizing study workflows in one place: subjects, tasks, schedule, notes, calendar, and profile data.

The project is built with FastAPI, Jinja2, SQLAlchemy, and Bootstrap. It supports local development with SQLite and production deployment with PostgreSQL.

## Features

- User registration, login, logout, and password reset
- Personal dashboard with task summary, streaks, urgent tasks, and today's schedule
- Subject management with teacher, room, color, and notes
- Task management with deadlines, priority, difficulty, and completion tracking
- Weekly schedule management with flexible or preset time slots
- Notes linked to subjects
- Calendar view with `.ics` export
- Profile editing with study group, course, and schedule terminology
- Data export to JSON and CSV ZIP
- Data import from JSON backup

## Tech Stack

- Python
- FastAPI
- Jinja2
- SQLAlchemy
- SQLite for local development
- PostgreSQL for production
- Bootstrap 5

## Demo

Production URL:

`https://student-assistant-beby.onrender.com/`

## Local Setup

### 1. Clone the repository

```bash
git clone https://github.com/Xelmor/student-assistant.git
cd student-assistant
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

### 3. Activate the environment

PowerShell:

```powershell
venv\Scripts\Activate.ps1
```

CMD:

```cmd
venv\Scripts\activate.bat
```

Linux/macOS:

```bash
source venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Create `.env`

Example local configuration:

```env
APP_ENV=development
SECRET_KEY=replace_with_a_unique_random_string_at_least_32_chars_long
COOKIE_SECURE=false
DATABASE_URL=sqlite:///./student_assistant.db
HOST=0.0.0.0
PORT=8001
RELOAD=false
ALLOW_LOCAL_PRIVATE_DATA=true
```

### 6. Run the app

```bash
python run.py
```

Then open:

`http://127.0.0.1:8001`

## Environment Variables

| Variable | Required | Description |
| --- | --- | --- |
| `APP_ENV` | Yes | `development` or `production` |
| `SECRET_KEY` | Yes | Session secret, must be at least 32 characters |
| `COOKIE_SECURE` | Yes | Must be `true` in production |
| `DATABASE_URL` | Yes | SQLite or PostgreSQL connection string |
| `HOST` | No | Host for local run, default `0.0.0.0` |
| `PORT` | No | Port for local run, default `8000` |
| `RELOAD` | No | Enables auto-reload in development |
| `ALLOW_LOCAL_PRIVATE_DATA` | No | Enables local-only profile details page |

## Database

For local development the app uses SQLite by default:

```text
sqlite:///./student_assistant.db
```

For production use PostgreSQL:

```text
postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME
```

The app also accepts `postgres://...` and `postgresql://...` URLs and normalizes them automatically.

## Deploy on Render

Recommended production setup:

1. Create a PostgreSQL database in Render.
2. Copy the database `Internal Database URL`.
3. Create or update a Web Service connected to this repository.
4. Set environment variables:

```env
APP_ENV=production
SECRET_KEY=replace_with_a_long_random_secret
COOKIE_SECURE=true
DATABASE_URL=<Render Internal Database URL>
RELOAD=false
ALLOW_LOCAL_PRIVATE_DATA=false
```

5. Use these service commands:

Build command:

```bash
pip install -r requirements.txt
```

Start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

Detailed deployment notes are available in [DEPLOYMENT.md](./DEPLOYMENT.md).

## Project Structure

```text
app/
  main.py              FastAPI app setup
  settings.py          environment configuration
  database.py          SQLAlchemy engine and session
  models.py            database models
  auth.py              password hashing and session user lookup
  routers/             application routes
  templates/           Jinja2 templates
  static/              CSS and static assets
run.py                 local entry point
requirements.txt       Python dependencies
DEPLOYMENT.md          production deployment notes
```

## Notes

- The app uses server-side persistence through the configured database.
- Production should use PostgreSQL instead of SQLite on ephemeral hosting.
- CSRF protection is enabled for form actions.
- Sessions are stored via signed cookies.

## License

This project currently does not include a license file.
