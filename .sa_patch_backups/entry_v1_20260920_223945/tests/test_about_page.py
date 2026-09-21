from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app


def test_about_page_is_public_and_uses_project_metadata():
    with TestClient(app) as client:
        response = client.get('/about')

    assert response.status_code == 200
    assert 'О проекте — Student Assistant' in response.text
    assert (
        'Student Assistant — учебный веб-сервис для управления задачами, '
        'расписанием, предметами, заметками и дедлайнами студента.'
    ) in response.text
    assert 'Max Alekseenko' in response.text


def test_about_page_lists_only_confirmed_stack():
    with TestClient(app) as client:
        response = client.get('/about')

    confirmed_technologies = {
        'Python',
        'FastAPI',
        'Jinja2',
        'SQLAlchemy',
        'SQLite',
        'PostgreSQL',
        'HTML5',
        'CSS3',
        'JavaScript',
        'Bootstrap 5.3',
        'Uvicorn',
        'Docker',
        'PWA / Service Worker',
    }
    invented_technologies = {'Flask', 'React', 'Node.js', 'Gunicorn'}

    for technology in confirmed_technologies:
        assert technology in response.text
    for technology in invented_technologies:
        assert technology not in response.text


def test_landing_links_to_about_page():
    with TestClient(app) as client:
        response = client.get('/')

    assert response.status_code == 200
    assert 'href="/about">О проекте</a>' in response.text
    assert response.text.index('href="#faq">FAQ</a>') < response.text.index(
        'href="/about">О проекте</a>'
    )


def test_about_page_keeps_full_public_navigation():
    with TestClient(app) as client:
        response = client.get('/about')

    assert response.status_code == 200
    for href, label in (
        ('/#hero', 'Главная'),
        ('/#features', 'Возможности'),
        ('/#interface', 'Интерфейс'),
        ('/#study', 'Для учёбы'),
        ('/#faq', 'FAQ'),
        ('/about', 'О проекте'),
    ):
        assert f'href="{href}"' in response.text
        assert f'>{label}</a>' in response.text
    assert 'href="/about" aria-current="page"' in response.text


def test_about_page_has_responsive_dark_styles():
    styles = Path('app/static/css/pages/about.css').read_text(encoding='utf-8')

    assert 'body.about-page' in styles
    assert 'backdrop-filter: blur(18px)' in styles
    assert '@media (max-width: 767.98px)' in styles
    assert '@media (max-width: 575.98px)' in styles
    assert 'overflow-x: hidden' in styles
