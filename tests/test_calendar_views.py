from datetime import date, datetime, time
import re
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.models import AcademicEvent, ScheduleItem, Subject, Task, User
from app.web.routes.calendar import calendar_redirect


@pytest.fixture
def calendar_client():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)

    def get_test_db():
        with sessions() as db:
            yield db

    app.dependency_overrides[get_db] = get_test_db
    client = TestClient(app)
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', client.get('/').text)[1]
    assert client.post('/start', data={'display_name': 'Calendar views', 'csrf_token': csrf}, follow_redirects=False).status_code == 302
    with sessions() as db:
        user = db.query(User).one()
        other = User(username='Other calendar', email='other-calendar@example.com', password_hash='unused')
        subject = Subject(user_id=user.id, name='Математика')
        db.add_all([other, subject])
        db.flush()
        db.add_all([
            ScheduleItem(user_id=user.id, subject_id=subject.id, weekday=3, start_time=time(9), end_time=time(10), room='101'),
            ScheduleItem(user_id=user.id, subject_id=subject.id, weekday=4, start_time=time(7), end_time=time(8), room='102'),
            AcademicEvent(user_id=user.id, title='Особый день', event_type='day_override', event_date=date(2026, 12, 31)),
            AcademicEvent(user_id=user.id, title='Разовое занятие', event_type='changed_class', event_date=date(2026, 12, 31), start_time=time(12), end_time=time(13)),
            AcademicEvent(user_id=user.id, title='Без времени', event_type='exam', event_date=date(2027, 1, 1)),
            AcademicEvent(user_id=user.id, title='Экзамен утром', event_type='exam', event_date=date(2027, 1, 1), start_time=time(10)),
            AcademicEvent(user_id=user.id, title='Экзамен вечером', event_type='exam', event_date=date(2027, 1, 1), start_time=time(21)),
            Task(user_id=user.id, title='На дату', scheduled_for_date=date(2027, 1, 1)),
            Task(user_id=user.id, title='Дедлайн ночью', deadline=datetime(2027, 1, 1, 23, 59)),
            AcademicEvent(user_id=other.id, title='Чужой экзамен', event_type='exam', event_date=date(2027, 1, 1)),
        ])
        db.commit()
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', client.get('/calendar').text)[1]
    try:
        yield client, csrf
    finally:
        client.close()
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


@pytest.mark.parametrize('view', ['month', 'week', 'agenda'])
def test_real_views_and_week_data(calendar_client, view):
    client, _ = calendar_client
    response = client.get(f'/calendar?selected=2027-01-01&view={view}')
    assert response.status_code == 200
    context = response.context
    assert context['view_mode'] == view
    assert f'data-calendar-view="{view}"' in response.text
    assert f'data-calendar-view-link="{view}" class="is-active" aria-current="page"' in response.text
    assert 'Чужой экзамен' not in response.text
    assert context['selected_iso'] == '2027-01-01'
    assert context['week_days'][0]['iso_date'] == '2026-12-28'
    assert context['week_days'][-1]['iso_date'] == '2027-01-03'
    thursday, friday = context['week_days'][3:5]
    assert {e['type'] for e in thursday['events']} == {'override', 'schedule-change'}
    assert {e['title'] for e in friday['all_day_events']} == {'Без времени', 'На дату'}
    assert {e['title'] for e in friday['timeline_events']} == {'Математика', 'Экзамен утром', 'Экзамен вечером', 'Дедлайн ночью'}
    assert context['timeline_hours'][0] == '07:00'
    assert context['timeline_hours'][-1] == '23:00'
    for event in friday['timeline_events']:
        assert 0 <= event['timeline_top'] < 100
        assert event['timeline_top'] + event['timeline_height'] <= 100.0001
    assert len(next(day for week in context['month_weeks'] for day in week if day['iso_date'] == '2027-01-01')['events']) == 6
    if view == 'month':
        assert 'calendar-month-grid' in response.text
        assert context['previous_selected'] == '2026-12-01'
    else:
        assert context['previous_selected'] == '2026-12-25'
        assert context['next_selected'] == '2027-01-08'


@pytest.mark.parametrize('view', ['month', 'week', 'agenda'])
def test_mini_month_does_not_reset_selection(calendar_client, view):
    client, _ = calendar_client
    context = client.get(f'/calendar?year=2027&month=3&selected=2027-01-01&view={view}').context
    assert context['calendar_month'] == 3
    assert context['selected_iso'] == '2027-01-01'
    assert len(context['selected_events']) == 6
    assert context['week_days'][0]['iso_date'] == '2026-12-28'
    assert context['view_mode'] == view


@pytest.mark.parametrize('view', ['month', 'week', 'agenda'])
def test_calendar_mutations_preserve_view(calendar_client, view):
    client, csrf = calendar_client
    state = {'year': '2027', 'month': '1', 'selected': '2027-01-01', 'view': view, 'csrf_token': csrf}
    payload = {**state, 'title': 'Проверка сохранения', 'event_type': 'exam', 'event_date': '2027-01-01', 'start_time': '', 'end_time': ''}

    def post(path, data):
        response = client.post(path, data=data, follow_redirects=False)
        assert response.status_code == 302
        query = parse_qs(urlparse(response.headers['location']).query)
        assert query['view'] == [view]
        assert query['selected'] == ['2027-01-01']
        return query

    post('/calendar/session/add', payload)
    context = client.get(calendar_redirect(2027, 1, '2027-01-01', view)).context
    event_id = next(e['academic_event_id'] for e in context['selected_events'] if e['title'] == payload['title'])
    post(f'/calendar/session/edit/{event_id}', payload)
    assert 'calendar_error' in post(f'/calendar/session/edit/{event_id}', {**payload, 'event_date': 'bad'})
    post('/calendar/settings', {**state, 'last_study_day': ''})
    post('/calendar/override/add', {**state, 'start_date': '2027-01-01'})
    post(f'/calendar/session/delete/{event_id}', state)
    assert 'calendar_error' in post('/calendar/session/add', {**payload, 'event_date': 'bad'})


def test_fallback_and_month_end_navigation(calendar_client):
    client, _ = calendar_client
    assert client.get('/calendar?view=invalid').context['view_mode'] == 'week'
    assert parse_qs(urlparse(calendar_redirect(view='invalid')).query)['view'] == ['week']
    context = client.get('/calendar?view=month&selected=2027-01-31').context
    assert context['next_selected'] == '2027-02-28'
    assert context['previous_selected'] == '2026-12-31'
