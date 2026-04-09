# Student Assistant

Небольшой учебный помощник, в котором можно держать все в одном месте: предметы, задания, дедлайны, расписание и заметки.

Проект написан как веб-приложение на `FastAPI` + `Jinja2` + `SQLAlchemy` + `SQLite`. Идея простая: открыть сайт и быстро посмотреть, что у тебя по учебе происходит прямо сейчас.

## Открыть сразу

Если не хочется ничего устанавливать локально, можно просто зайти в онлайн-версию:

[student-assistant-beby.onrender.com](https://student-assistant-beby.onrender.com/)

## Что умеет

- регистрация и вход
- дашборд с общей картиной по задачам и расписанию
- добавление и редактирование предметов
- добавление задач с дедлайнами
- ведение расписания
- хранение заметок

## На чем сделано

- Python
- FastAPI
- Jinja2
- SQLAlchemy
- SQLite
- Bootstrap 5

## Как устроен проект

```text
student_assistant_project/
├── app/
│   ├── routers/
│   ├── static/
│   ├── templates/
│   ├── auth.py
│   ├── database.py
│   ├── main.py
│   ├── models.py
│   └── utils.py
├── requirements.txt
├── run.py
├── start_web.bat
├── start_web.sh
└── README.md
```

## Как запустить

### Вариант 1. Самый простой

Если ты на Windows, можно просто запустить `start_web.bat`.

Если ты на Linux или macOS:

```bash
chmod +x start_web.sh
./start_web.sh
```

### Вариант 2. Вручную

1. Создай виртуальное окружение:

```bash
python -m venv venv
```

2. Активируй его.

Windows PowerShell:

```powershell
venv\Scripts\Activate.ps1
```

Windows CMD:

```cmd
venv\Scripts\activate.bat
```

Linux / macOS:

```bash
source venv/bin/activate
```

3. Установи зависимости:

```bash
pip install -r requirements.txt
```

4. Запусти проект:

```bash
python run.py
```

После этого сайт будет доступен по адресу:

```text
http://127.0.0.1:8000
```

## База данных

По умолчанию используется локальная база `SQLite`.

Файл базы:

```text
student_assistant.db
```

Таблицы создаются автоматически при первом запуске.

## Полезно знать

- файл `.env` нужен для локальных настроек
- `.env.example` можно использовать как шаблон
- если не хочешь загружать свои локальные данные в GitHub, не коммить `.env`, `venv` и `student_assistant.db`

## Быстрая проверка кода

Если нужно просто проверить, что основные файлы без синтаксических ошибок:

```bash
python -m py_compile app\models.py app\database.py app\main.py app\routers\web.py
```

## Что можно улучшить потом

- уведомления и напоминания
- тесты
- Docker
- деплой
- админку

## Итог

Это не огромная система, а скорее удобный личный проект для учебы. Открыл, посмотрел задачи, обновил расписание, записал заметку и пошел дальше.
