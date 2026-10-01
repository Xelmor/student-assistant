from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.telegram_task_parser import conversational_intent, parse_task

NOW = datetime(2026, 9, 30, 12, tzinfo=ZoneInfo('Europe/Moscow'))  # Wednesday
SUBJECTS = [(1, 'Базы данных'), (2, 'Философия'), (3, 'Английский язык')]


@pytest.mark.parametrize('text,deadline', [
    ('задача завтра в 18', '2026-10-01T18:00'),
    ('задача сегодня 20:30', '2026-09-30T20:30'),
    ('задача послезавтра', '2026-10-02T23:59'),
    ('задача в пятницу', '2026-10-02T23:59'),
    ('задача к пятнице', '2026-10-02T23:59'),
    ('задача до пятницы', '2026-10-02T23:59'),
    ('задача в понедельник', '2026-10-05T23:59'),
    ('задача во вторник', '2026-10-06T23:59'),
    ('задача в среду', '2026-10-07T23:59'),
    ('задача в четверг', '2026-10-01T23:59'),
    ('задача в субботу', '2026-10-03T23:59'),
    ('задача в воскресенье', '2026-10-04T23:59'),
    ('задача к понедельнику', '2026-10-05T23:59'),
    ('задача 02.10', '2026-10-02T23:59'),
    ('задача 02.10.2026', '2026-10-02T23:59'),
    ('задача 2026-10-02', '2026-10-02T23:59'),
    ('задача 02.10 15:00', '2026-10-02T15:00'),
    ('задача в 18', '2026-09-30T18:00'),
    ('задача в 18:30', '2026-09-30T18:30'),
    ('задача до 20:00', '2026-09-30T20:00'),
    ('задача завтра 18', '2026-10-01T18:00'),
    ('задача до 3 октября', '2026-10-03T23:59'),
    ('задача 3 октября 2027 в 18', '2027-10-03T18:00'),
])
def test_date_and_time_formats(text, deadline):
    parsed = parse_task(text, now=NOW)
    assert parsed.deadline == datetime.fromisoformat(deadline)
    assert parsed.title == 'Задача'
    assert parsed.warning is None


@pytest.mark.parametrize('phrase,priority', [('срочно', 'high'), ('важно', 'high'), ('высокий приоритет', 'high'), ('высокий', 'high'), ('средний приоритет', 'medium'), ('низкий приоритет', 'low'), ('низкий', 'low')])
def test_priority(phrase, priority):
    parsed = parse_task('подготовить доклад ' + phrase, now=NOW)
    assert parsed.priority == priority
    assert parsed.title == 'Подготовить доклад'


def test_no_deadline_and_preserved_number():
    assert parse_task('купить тетрадь', now=NOW).deadline is None
    parsed = parse_task('решить задачу 18', now=NOW)
    assert parsed.title == 'Решить задачу 18' and parsed.deadline is None


@pytest.mark.parametrize('phrase,subject_id,title', [
    ('сдать практику по БД завтра в 18', 1, 'Сдать практику'),
    ('сдать практику ПО  базам ДАННЫХ завтра', 1, 'Сдать практику'),
    ('подготовить доклад по философии в пятницу', 2, 'Подготовить доклад'),
    ('эссе по английскому 02.10 15:00', 3, 'Эссе'),
])
def test_owned_subject_matching(phrase, subject_id, title):
    parsed = parse_task(phrase, now=NOW, subjects=SUBJECTS)
    assert parsed.subject_ids == (subject_id,)
    assert parsed.title == title


def test_unknown_subject_preserves_meaning():
    parsed = parse_task('доклад по истории завтра', now=NOW, subjects=SUBJECTS)
    assert parsed.subject_ids == ()
    assert parsed.title == 'Доклад по истории'


def test_ambiguous_acronym_requires_choice():
    parsed = parse_task('практика по бд завтра', now=NOW, subjects=SUBJECTS + [(4, 'Безопасность данных')])
    assert parsed.subject_ids == (1, 4)
    assert parsed.title == 'Практика по бд'
    assert parsed.subject_title == 'Практика'


@pytest.mark.parametrize('text,warning', [
    ('задача сегодня в 10', 'Это время сегодня уже прошло.'),
    ('задача 29.09.2026', 'Эта дата уже прошла'),
    ('задача 29.09', 'Эта дата уже прошла'),
    ('задача 31.02', 'Такой даты нет'),
    ('задача в 25', 'Время должно быть'),
    ('задача в 18:99', 'Время должно быть'),
    ('задача завтра послезавтра', 'несколько дат'),
    ('задача в 18 и в 19', 'одно время'),
    ('задача срочно низкий приоритет', 'один приоритет'),
])
def test_unsafe_dates_and_ambiguity_warn(text, warning):
    assert warning in parse_task(text, now=NOW).warning


def test_exact_deadline_is_not_yet_past():
    assert parse_task('задача сегодня в 12', now=NOW).warning is None


@pytest.mark.parametrize('now,text,expected', [
    (datetime(2026, 12, 31, 12), 'задача завтра', datetime(2027, 1, 1, 23, 59)),
    (datetime(2026, 12, 31, 12), 'задача в понедельник', datetime(2027, 1, 4, 23, 59)),
    (datetime(2028, 2, 28, 12), 'задача послезавтра', datetime(2028, 3, 1, 23, 59)),
])
def test_year_and_month_rollover(now, text, expected):
    assert parse_task(text, now=now).deadline == expected


@pytest.mark.parametrize('text,intent', [('Привет!', 'greeting'), ('здравствуй', 'greeting'), ('хай', 'greeting'), ('Спасибо', 'thanks'), ('помощь', 'help'), ('что ты умеешь?', 'help'), ('отмена', 'cancel')])
def test_conversation(text, intent):
    assert conversational_intent(text) == intent
    assert parse_task(text, now=NOW) is None


@pytest.mark.parametrize('text', ['как дела', 'почему пары отменили?', 'ок', 'ага', 'что будет завтра'])
def test_other_conversation_does_not_become_task(text):
    assert parse_task(text, now=NOW) is None


@pytest.mark.parametrize('text', ['', 'завтра в 18', 'x' * 501, 'очень ' * 30 + 'длинная задача'])
def test_title_validation(text):
    with pytest.raises(ValueError):
        parse_task(text, now=NOW)


@pytest.mark.parametrize('text,title,hour', [
    ('решить задачу 18 завтра', 'Решить задачу 18', 23),
    ('решить задачу 18 завтра в 20', 'Решить задачу 18', 20),
    ('решить задачу завтра 18 срочно', 'Решить задачу', 18),
    ('решить задачу завтра 18.', 'Решить задачу', 18),
    ('решить задачу завтра.', 'Решить задачу', 23),
])
def test_numbers_and_punctuation_preserve_meaning(text, title, hour):
    parsed = parse_task(text, now=NOW)
    assert parsed.title == title
    assert parsed.deadline.hour == hour
