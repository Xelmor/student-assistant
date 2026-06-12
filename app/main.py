from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi import Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .core.config import settings
from .core.migrations import run_migrations
from .web.dependencies import templates
from .web.routes import router


logger = logging.getLogger(__name__)


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

    def render_error_page(request: Request, status_code: int):
        try:
            is_authenticated = bool(request.session.get('user_id'))
        except (AssertionError, RuntimeError):
            is_authenticated = False

        home_href = '/dashboard' if is_authenticated else '/'
        pages = {
            403: {
                'code': '403',
                'title': 'Нет доступа',
                'description': (
                    'У тебя нет прав для просмотра этой страницы. '
                    'Возможно, нужно войти в аккаунт или вернуться на главную.'
                ),
                'tone': 'forbidden',
                'icon': 'lock',
                'primary_label': 'На главную' if is_authenticated else 'Войти',
                'primary_href': home_href if is_authenticated else '/login',
                'primary_action': None,
                'secondary_label': None if is_authenticated else 'На главную',
                'secondary_href': None if is_authenticated else '/',
                'secondary_action': None,
                'hint': 'Доступ к данным остаётся защищённым.',
            },
            404: {
                'code': '404',
                'title': 'Страница не найдена',
                'description': (
                    'Похоже, такой страницы больше нет или ссылка введена неправильно.'
                ),
                'tone': 'not-found',
                'icon': 'search',
                'primary_label': 'На главную',
                'primary_href': home_href,
                'primary_action': None,
                'secondary_label': 'Назад',
                'secondary_href': home_href,
                'secondary_action': 'back',
                'hint': 'Проверь адрес или вернись в знакомый раздел.',
            },
            500: {
                'code': '500',
                'title': 'Что-то пошло не так',
                'description': (
                    'Мы уже знаем, что произошла ошибка. '
                    'Попробуй обновить страницу или вернуться позже.'
                ),
                'tone': 'server',
                'icon': 'warning',
                'primary_label': 'Обновить страницу',
                'primary_href': None,
                'primary_action': 'reload',
                'secondary_label': 'На главную',
                'secondary_href': home_href,
                'secondary_action': None,
                'hint': 'Технические детали безопасно записаны на сервере.',
            },
        }
        return templates.TemplateResponse(
            request,
            'errors/error.html',
            {
                **pages[status_code],
                'home_href': home_href,
                'is_authenticated': is_authenticated,
            },
            status_code=status_code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def student_assistant_http_error(
        request: Request,
        exc: StarletteHTTPException,
    ):
        if exc.status_code in {403, 404}:
            return render_error_page(request, exc.status_code)
        return await http_exception_handler(request, exc)

    @app.exception_handler(Exception)
    async def student_assistant_server_error(request: Request, exc: Exception):
        logger.error(
            'Unhandled exception while processing %s %s',
            request.method,
            request.url.path,
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return render_error_page(request, 500)

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
