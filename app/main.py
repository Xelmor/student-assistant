from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import inspect, text
from starlette.middleware.sessions import SessionMiddleware
from .database import Base, engine
from .routers import router
from .settings import settings

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


def ensure_tasks_schema():
    inspector = inspect(engine)
    if 'tasks' not in inspector.get_table_names():
        return

    columns = {column['name'] for column in inspector.get_columns('tasks')}
    if 'completed_at' in columns:
        return

    completed_at_type = 'DATETIME' if engine.dialect.name == 'sqlite' else 'TIMESTAMP'

    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE tasks ADD COLUMN completed_at {completed_at_type}")
        )


def create_app() -> FastAPI:
    ensure_users_schema()
    ensure_tasks_schema()

    app = FastAPI(title='Student Assistant')
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site='lax',
        https_only=settings.cookie_secure,
    )
    app.mount('/static', StaticFiles(directory=str(settings.base_dir / 'static')), name='static')

    @app.middleware('http')
    async def force_utf8_charset(request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get('content-type', '')
        if content_type.startswith('text/html') and 'charset=' not in content_type.lower():
            response.headers['content-type'] = 'text/html; charset=utf-8'
        return response

    @app.get('/manifest.webmanifest', include_in_schema=False)
    async def manifest():
        return FileResponse(
            settings.base_dir / 'static' / 'manifest.webmanifest',
            media_type='application/manifest+json',
        )

    @app.get('/service-worker.js', include_in_schema=False)
    async def service_worker():
        return FileResponse(
            settings.base_dir / 'static' / 'service-worker.js',
            media_type='application/javascript',
        )

    app.include_router(router)
    return app


app = create_app()
