import os
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from dotenv import load_dotenv
from .database import Base, engine
from .routers import web

load_dotenv()

Base.metadata.create_all(bind=engine)

app = FastAPI(title='Student Assistant')
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv('SECRET_KEY', 'dev_secret_change_me'),
)

BASE_DIR = Path(__file__).resolve().parent
app.mount('/static', StaticFiles(directory=str(BASE_DIR / 'static')), name='static')

app.include_router(web.router)
