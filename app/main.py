from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from .core.config import settings
from .core.migrations import run_migrations
from .web.routes import router


def create_app() -> FastAPI:
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


run_migrations()
app = create_app()
