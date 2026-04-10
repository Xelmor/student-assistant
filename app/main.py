import os
from pathlib import Path
from fastapi import FastAPI
from fastapi import Request
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from .database import Base, engine
from .routers import router

load_dotenv()

Base.metadata.create_all(bind=engine)


def ensure_users_schema():
    inspector = inspect(engine)
    if 'users' not in inspector.get_table_names():
        return

    columns = {column['name'] for column in inspector.get_columns('users')}
    if 'schedule_unit' in columns:
        return

    with engine.begin() as connection:
        connection.execute(
            text("ALTER TABLE users ADD COLUMN schedule_unit VARCHAR(20) NOT NULL DEFAULT 'class'")
        )


ensure_users_schema()

app = FastAPI(title='Student Assistant')
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv('SECRET_KEY', 'dev_secret_change_me'),
)

BASE_DIR = Path(__file__).resolve().parent
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')


@app.middleware('http')
async def force_utf8_charset(request: Request, call_next):
    response = await call_next(request)
    content_type = response.headers.get('content-type', '')
    if content_type.startswith('text/html') and 'charset=' not in content_type.lower():
        response.headers['content-type'] = 'text/html; charset=utf-8'
    return response

app.include_router(router)
