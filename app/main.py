import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from .database import Base, engine
from .routers import web

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

app.include_router(web.router)
