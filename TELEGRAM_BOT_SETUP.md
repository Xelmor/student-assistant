# Telegram-бот Student Assistant

Минимальный Telegram-бот работает как дополнение к сайту: показывает планы на
сегодня, ближайшие задачи и открывает Student Assistant. ИИ для работы бота не
используется.

## 1. Создание бота

1. Откройте официальный аккаунт `@BotFather` в Telegram.
2. Отправьте команду `/newbot`.
3. Задайте имя и username бота.
4. Сохраните выданный токен в переменной окружения `TELEGRAM_BOT_TOKEN`.

Токен нельзя добавлять в код, коммитить в GitHub или публиковать в документации.
Если `TELEGRAM_BOT_TOKEN` пуст, приложение использует
`TELEGRAM_BOT_API_TOKEN` как fallback.

## 2. Переменные окружения

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_API_TOKEN=
TELEGRAM_BOT_API_BASE_URL=
TELEGRAM_LINK_CODE_TTL_MINUTES=10
TELEGRAM_USE_WEBHOOK=false
TELEGRAM_WEBHOOK_BASE_URL=
TELEGRAM_WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_BOT_HOST=127.0.0.1
TELEGRAM_BOT_PORT=8001
TELEGRAM_BOT_LOG_LEVEL=INFO
TELEGRAM_BOT_USERNAME=student_assistant_max_bot
TELEGRAM_DIGEST_CHECK_INTERVAL_SECONDS=60
```

Для `TELEGRAM_WEBHOOK_SECRET` используйте длинную случайную URL-безопасную
строку. Файл `.env` уже исключён из Git через `.gitignore`.

## 3. Локальная проверка Telegram-бота

Для локальной разработки webhook не нужен. В `.env` должны быть:

```env
TELEGRAM_USE_WEBHOOK=false
TELEGRAM_BOT_TOKEN=<токен-из-BotFather>
TELEGRAM_BOT_API_BASE_URL=http://127.0.0.1:8000
TELEGRAM_WEBHOOK_BASE_URL=
```

Если `TELEGRAM_BOT_TOKEN` пуст, polling использует
`TELEGRAM_BOT_API_TOKEN`.

Терминал 1:

```bash
cd ~/Desktop/student_assistant_project/student_assistant_project
source venv/bin/activate
python run.py
```

Терминал 2:

```bash
cd ~/Desktop/student_assistant_project/student_assistant_project
source venv/bin/activate
python -m telegram_bot.polling
```

Терминал 3 для автоматических сводок и дедлайн-напоминаний:

```bash
cd ~/Desktop/student_assistant_project/student_assistant_project
source venv/bin/activate
python -m telegram_bot.scheduler
```

При запуске polling удаляет активный webhook, получает сообщения через
`getUpdates` и работает до остановки через `Ctrl+C`. Сайт и бот используют одну
и ту же базу из `DATABASE_URL`.

После запуска:

1. Откройте профиль на локальном сайте и создайте код подключения.
2. В Telegram отправьте `/start`.
3. Отправьте `/link CODE`, подставив созданный код.
4. Проверьте `/today`, `/tomorrow`, `/week`, `/tasks`, `/notifications`,
   `/digest`, `/digest_test`, `/add_task`, `/done` и `/site`.

При `TELEGRAM_USE_WEBHOOK=false` Telegram не требуется для запуска самого
сайта. Регистрация и профиль продолжают работать даже без токена.

## 4. Подключение аккаунта

1. Войдите на сайт.
2. Откройте `Профиль → Telegram-бот`.
3. Нажмите `Подключить Telegram`.
4. Скопируйте команду вида `/link A7K92Q`.
5. Отправьте её боту в личном чате.

Код одноразовый и действует столько минут, сколько указано в
`TELEGRAM_LINK_CODE_TTL_MINUTES`. После успешной привязки код удаляется.

## 5. Webhook на Render

В Render задайте:

```env
TELEGRAM_USE_WEBHOOK=true
TELEGRAM_WEBHOOK_BASE_URL=https://student-assistant-beby.onrender.com
TELEGRAM_WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=<длинный-случайный-secret>
TELEGRAM_BOT_TOKEN=<токен-из-BotFather>
```

После деплоя выполните в Render Shell:

```bash
python -m telegram_bot.set_webhook
```

Для ежедневной сводки и дедлайн-напоминаний добавьте в Render отдельный
`Background Worker` с той же базой данных и переменными окружения. Команда
запуска:

```bash
python -m telegram_bot.scheduler
```

Не запускайте scheduler как часть web-процесса: отдельный worker продолжит
проверять время и дедлайны независимо от перезапусков сайта. Интервал проверки
задаётся через `TELEGRAM_DIGEST_CHECK_INTERVAL_SECONDS`, по умолчанию раз в
60 секунд.

Для web-сервиса и worker используйте одну базу и один набор Telegram-настроек:

```env
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_API_TOKEN=
TELEGRAM_USE_WEBHOOK=true
TELEGRAM_WEBHOOK_BASE_URL=https://student-assistant-beby.onrender.com
TELEGRAM_WEBHOOK_PATH=/telegram/webhook
TELEGRAM_WEBHOOK_SECRET=<длинный-случайный-secret>
TELEGRAM_BOT_API_BASE_URL=https://student-assistant-beby.onrender.com
TELEGRAM_BOT_USERNAME=student_assistant_max_bot
TELEGRAM_DIGEST_CHECK_INTERVAL_SECONDS=60
```

Команда берёт публичный адрес из `TELEGRAM_WEBHOOK_BASE_URL`. Если переменная
пуста, используется `TELEGRAM_BOT_API_BASE_URL`. Токен в консоль не выводится.

Webhook принимает Telegram update по защищённому адресу:

```text
TELEGRAM_WEBHOOK_BASE_URL + TELEGRAM_WEBHOOK_PATH + / + TELEGRAM_WEBHOOK_SECRET
```

Неверный secret получает HTTP `403`. Если токен не настроен, сайт не падает:
update безопасно принимается, но ответ в Telegram не отправляется.

## 6. Команды

- `/start` — начать работу;
- `/help` — показать помощь;
- `/link CODE` — подключить аккаунт;
- `/today` — расписание, задачи и события на сегодня;
- `/tomorrow` — расписание, задачи и события на завтра;
- `/week` — краткий обзор ближайших семи дней;
- `/tasks` — до семи ближайших активных задач;
- `/notifications` — все настройки Telegram-уведомлений;
- `/digest` — показать состояние утренней сводки;
- `/digest_on` — включить ежедневную сводку;
- `/digest_off` — выключить ежедневную сводку;
- `/digest_test` — сразу отправить тестовую сводку;
- `/add_task` — добавить задачу из Telegram;
- `/done NUMBER` — отметить задачу выполненной;
- `/cancel` — отменить текущий диалог;
- `/site` — открыть Student Assistant;
- `/unlink` — отключить Telegram.

### Удобное добавление задач

1. Через пошаговый диалог:

```text
/add_task
```

Бот последовательно спросит название, дедлайн, предмет и приоритет, а затем
покажет задачу перед созданием. Текущий диалог можно отменить командой
`/cancel`.

2. Быстро одной строкой:

```text
/add_task Сделать практику по ТПР
```

3. Расширенный формат:

```text
/add_task Выучить слова | завтра 18:00 | Английский | высокий
```

Формат с запятыми также поддерживается:

```text
/add_task Выучить слова, завтра 18:00, Английский, высокий
```

4. Обычным сообщением:

```text
Сделать доклад по философии
```

Для привязанного аккаунта бот предложит сразу создать задачу или открыть
пошаговую настройку.

Поддерживаются дедлайны `сегодня`, `завтра`, время в формате `HH:MM`, а также
даты `YYYY-MM-DD`, `YYYY-MM-DD HH:MM`, `DD.MM.YYYY` и `DD.MM.YYYY HH:MM`.
Предмет ищется без учёта регистра только среди предметов текущего пользователя.
Новый предмет автоматически не создаётся.

После `/tasks` задачу можно закрыть командой:

```text
/done 1
```

Также под каждой задачей есть безопасная inline-кнопка `✅ Закрыть N`. Команда и
кнопка повторно проверяют владельца задачи перед изменением данных.

Команды `/today`, `/tomorrow`, `/week`, `/tasks`, `/digest`, `/add_task` и
`/done` работают только с пользователем, связанным по `telegram_user_id`.
Выполненные задачи и данные других аккаунтов не выводятся.

### Утренняя сводка

Сводка выключена по умолчанию и начинает отправляться только после явного
включения в профиле или командой `/digest_on`. В профиле можно выбрать время и
часовой пояс, сохранить настройки и отправить тестовое сообщение.

Scheduler показывает количество пар, активных задач и дедлайнов на сегодня,
ближайшую ещё не начавшуюся пару и до трёх приоритетных задач. Дата последней
успешной отправки хранится в базе, поэтому один аккаунт не получает дубли в
течение одного локального дня.

### Настройки уведомлений

На сайте откройте `Профиль → Telegram-бот`. После подключения Telegram доступны
две секции:

- `Утренняя сводка` — включение, время и часовой пояс;
- `Напоминания о дедлайнах` — включение и интервал `2`, `6` или `24` часа.

Нажмите `Сохранить настройки`. Кнопка `Отправить тестовую сводку` отправляет
сообщение сразу и не меняет дату обычной утренней отправки.

В Telegram команда `/notifications` показывает те же параметры. Inline-кнопки
позволяют включить или выключить сводку, проверить её, включить дедлайны и
выбрать интервал напоминания.

Scheduler проверяет только подключённые аккаунты с включённой настройкой.
Напоминание отправляется для активной задачи с датой дедлайна и содержит кнопки
`Задачи`, `Закрыть задачу` и `Сайт`. Каждая доставка записывается в отдельный
журнал, поэтому одинаковое напоминание не отправляется повторно. Выполненные
задачи, задачи без дедлайна и чужие данные не используются.

Для локальной проверки запустите одновременно:

```bash
python run.py
python -m telegram_bot.polling
python -m telegram_bot.scheduler
```

На Render scheduler запускается отдельным Background Worker командой
`python -m telegram_bot.scheduler`. Web-сервис, polling/webhook и worker должны
использовать одну и ту же `DATABASE_URL`.

## 7. Рекомендуемое оформление в BotFather

Откройте `@BotFather` и настройте публичное оформление:

```text
/setname
Student Assistant
```

```text
/setdescription
Student Assistant — учебный помощник для студентов. Бот показывает ближайшие задачи, расписание на сегодня и помогает быстро перейти к личному кабинету.
```

```text
/setabouttext
Учебный Telegram-помощник для задач, расписания и дедлайнов.
```

```text
/setcommands
start - Начать работу
help - Помощь по командам
link - Подключить аккаунт
today - Планы на сегодня
tomorrow - Планы на завтра
week - Обзор недели
tasks - Ближайшие задачи
notifications - Настройки уведомлений
digest - Настройки утренней сводки
digest_on - Включить утреннюю сводку
digest_off - Выключить утреннюю сводку
digest_test - Проверить утреннюю сводку
add_task - Добавить задачу
done - Закрыть задачу
cancel - Отменить действие
site - Открыть сайт
unlink - Отключить Telegram
```

Тот же список можно безопасно синхронизировать через Telegram Bot API:

```bash
python -m telegram_bot.set_commands
```

Команду нужно повторять после добавления или переименования команд бота.
Токен берётся из переменных окружения и в консоль не выводится.

Рекомендуемая аватарка:

- тёмный круглый фон;
- буквы `SA` или `S`;
- фиолетово-бирюзовый градиент;
- мягкое свечение;
- минималистичный стиль;
- хорошая читаемость в маленьком размере.

Не добавляйте мелкий текст: в Telegram аватар чаще всего отображается небольшим
кругом.

Ответы бота используют безопасную HTML-разметку и компактные inline-кнопки.
Кнопки `Сегодня`, `Завтра`, `Неделя`, `Задачи`, `Уведомления`,
`Добавить задачу`, пошагового диалога, `Закрыть задачу`, `Сайт`, `Помощь` и
подтверждение отключения обрабатываются одинаково через webhook и polling.

## 8. Проверка

```bash
pytest -q tests/test_telegram_bot.py
```

Проверяются одноразовые и истёкшие коды, изоляция пользовательских данных,
webhook secret, polling offset, общий обработчик команд, scheduler без дублей,
изоляция дедлайн-напоминаний и команды `/site`, `/today`, `/tomorrow`, `/week`,
`/tasks`, `/notifications`, `/digest`, `/add_task`, `/done`, `/cancel` и
`/unlink`.
