# Student Assistant

Умный студенческий планировщик для задач, расписания, заметок и дедлайнов.

[Live Demo](https://student-assistant-beby.onrender.com) · [Telegram Bot](https://t.me/student_assistant_max_bot) · [License](LICENSE)

![Главная панель Student Assistant](docs/images/dashboard.png)

> Скриншот пока не добавлен. Поместите изображение главной панели в `docs/images/dashboard.png`.

## Возможности

- **Задачи и дедлайны** — приоритеты, сроки и повторяющиеся задачи.
- **Расписание** — учебные занятия и план на неделю.
- **Календарь** — задачи и занятия в одном представлении.
- **Заметки** — учебные материалы и личные записи.
- **Telegram-уведомления** — напоминания о дедлайнах и ежедневная сводка при настроенном боте.
- **Синхронизация устройств** — подключение телефона или компьютера через QR-код или одноразовый код.
- **Без email и пароля** — создание пространства и доступ с доверенного устройства.
- **Recovery key** — ключ восстановления доступа при потере устройств.

## Как это работает

1. Создаёшь пространство и сохраняешь ключ восстановления.
2. Добавляешь задачи и расписание.
3. Подключаешь телефон через QR-код или код из профиля.
4. Данные синхронизируются между устройствами в общем пространстве.

## Технологии

| Область | Технологии |
| --- | --- |
| Backend | Python, FastAPI, Jinja2 |
| База данных | PostgreSQL / SQLite |
| Интерфейс | JavaScript, HTML/CSS |
| Уведомления | Telegram Bot API |
| Развёртывание | Docker, Render |

## Быстрый запуск

Нужны Python 3.12+ и Git. Для локального запуска достаточно SQLite.

```bash
git clone https://github.com/Xelmor/student-assistant.git
cd student-assistant
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python run.py
```

В Windows PowerShell вместо `source venv/bin/activate`:

```powershell
.\venv\Scripts\Activate.ps1
```

Приложение доступно по адресу [http://127.0.0.1:8000](http://127.0.0.1:8000).
Если команда `python` недоступна в Linux/macOS, используйте `python3`.

Для установки зафиксированных версий:

```bash
pip install -r requirements.lock.txt
```

Lock-файл — снимок окружения Python 3.14.5 на macOS, включая инструменты
разработки. Совместимость с целевой ОС и версией Python нужно проверять отдельно.

## Переменные окружения

[.env.example](.env.example) содержит шаблон настроек. Для своей конфигурации
скопируйте его в `.env` и задайте нужные значения:

```bash
cp .env.example .env
```

В Windows PowerShell: `Copy-Item .env.example .env`.

Основные настройки: `DATABASE_URL`, `SECRET_KEY`, `APP_ENV`, `HOST` и `PORT`.
Для production также настройте `COOKIE_SECURE`, `ALLOWED_HOSTS` и `PUBLIC_BASE_URL`.
Telegram настраивается отдельно по инструкции ниже. Не публикуйте `.env`,
токены и ключи доступа.

## Структура проекта

```text
app/           — приложение, маршруты, шаблоны и статические файлы
telegram_bot/  — Telegram-интеграция и отправка уведомлений
tests/         — автоматические тесты и E2E-сценарии
docs/          — документация по запуску, тестированию и безопасности
scripts/       — вспомогательные скрипты запуска
```

## Тесты

Установите зависимости для разработки:

```bash
pip install -r requirements-dev.txt
```

Основной набор тестов:

```bash
pytest
```

Браузерные E2E-тесты запускаются отдельно:

```bash
python -m playwright install chromium
pytest tests/e2e
```

Команды выполняются из корня проекта с активированным виртуальным окружением.

## Документация

- [E2E-тестирование](docs/testing/E2E_TESTING.md)
- [Аудит безопасности](docs/security/SECURITY_AUDIT.md)
- [Настройка Telegram-бота](docs/integrations/TELEGRAM_BOT_SETUP.md)
- [Развёртывание и production](docs/DEPLOYMENT.md)

## License

[MIT License](LICENSE).
