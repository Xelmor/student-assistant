from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .core.config import settings
from .core.migrations import run_migrations
from .web.routes import router


@asynccontextmanager
async def lifespan(_: FastAPI):
    run_migrations()
    yield


def create_app() -> FastAPI:
    expose_api_docs = settings.app_env != 'production'
    app = FastAPI(
        title='Student Assistant',
        lifespan=lifespan,
        docs_url='/docs' if expose_api_docs else None,
        redoc_url='/redoc' if expose_api_docs else None,
        openapi_url='/openapi.json' if expose_api_docs else None,
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        same_site='lax',
        https_only=settings.cookie_secure,
        max_age=settings.session_max_age_seconds,
    )
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
    app.mount('/static', StaticFiles(directory=str(settings.base_dir / 'static')), name='static')

    @app.middleware('http')
    async def secure_response_headers(request: Request, call_next):
        response = await call_next(request)
        content_type = response.headers.get('content-type', '')
        if content_type.startswith('text/html') and 'charset=' not in content_type.lower():
            response.headers['content-type'] = 'text/html; charset=utf-8'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self'; "
            "base-uri 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "form-action 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self' data:; "
            "connect-src 'self'; "
            "manifest-src 'self'; "
            "worker-src 'self'; "
            "frame-src 'none'"
        )
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy'] = (
            'camera=(), microphone=(), geolocation=(), payment=(), usb=()'
        )
        if settings.app_env == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        if content_type.startswith('text/html'):
            response.headers.setdefault('Cache-Control', 'no-store')
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
