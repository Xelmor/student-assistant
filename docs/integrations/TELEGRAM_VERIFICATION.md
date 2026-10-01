# Проверка Telegram-интеграции — 29 сентября 2026

## Результат и границы работы

**Проверено в изолированной среде.** Ветка `fix/telegram-integration` создана от
чистого `f002382` (`fix/production-docker-lock`). Изменения зависимостей, четырёх CI
job и production Dockerfile сохранены. Commit, push, merge и deploy не выполнялись.
Рабочий `.env`, ключ сайта, реальные токены, данные пользователей и устройства
не изменялись. Реальные сообщения, getUpdates, setWebhook/deleteWebhook и
сетевые getMe/getWebhookInfo не запускались.

**Осталось подтвердить на настоящем боте.** Наличие токена в локальных настройках
не доказывает, что он принадлежит username из ссылки сайта. Render, его процессы,
БД, актуальная ревизия и зарегистрированный webhook удалённо не проверялись.

## Подтверждённые причины и дефекты

| Наблюдение | Доказательство / исправление |
| --- | --- |
| Локально выбран polling, но polling и scheduler не запущены | Read-only проверка процессов: оба счётчика 0; при этой конфигурации локально некому принимать команды и отправлять уведомления |
| Локальная БД — SQLite; PUBLIC_BASE_URL пуст, валидный публичный webhook не настроен | Вывод безопасной диагностики без секретов; эта БД не считается общей с Render |
| Webhook подтверждал update после ошибки обработки/отправки | Теперь транзакционная обработка + outbox; при сбое 503, при повторе бизнес-операция не повторяется |
| Polling двигал offset после ошибки и безусловно удалял webhook | Дефект offset воспроизведён тестом; теперь offset сохраняется, переключение только отдельной явной командой |
| Команда из группы могла заменить private chat ID и выдать персональные данные | Дефект воспроизведён тестом; тип чата проверяется до поиска данных/обновления привязки |
| Ошибки API скрывались, исходное исключение могло содержать URL с токеном | Безопасные категории/HTTP status/retry_after, ограниченные повторы, подавленная цепочка исходных сетевых исключений и редактирование legacy URL в логах |
| Диалог терялся при рестарте; /done N пересчитывал сортировку и мог закрыть другую задачу | Состояние/TTL в БД, версии кнопок, стабильные ID, нумерация последнего подтверждённо отправленного списка |
| Scheduler заранее писал «отправлено» | Успех фиксируется после API; общие блокировки БД, сохраняемый журнал и измеряемый heartbeat |
| Бот расходился с календарём сайта по отменам/каникулам | Использованы общие правила календаря и общий сервис завершения повторяющихся задач |
| Профиль не узнавал о привязке в боте без ручного обновления | JSON endpoint статуса и ограниченный опрос; тест отправки защищён CSRF/лимитом частоты |

Нет оснований объявлять конкретную настройку Render причиной production-проблемы:
её состояние не наблюдалось. Локальная диагностика также выявила отсутствие двух
новых runtime-таблиц в рабочей БД: это ожидаемо до первого старта новой версии;
миграции на рабочей БД намеренно не запускались.

## Выполненные проверки

| Проверка | Результат |
| --- | --- |
| Исходные Telegram-тесты до правок | 65 passed |
| Первые регрессионные проверки до правок | 2 ожидаемых падения: группа меняет chat ID; offset пропускает ошибочный update |
| Полный итоговый основной набор, Python 3.12.14 | **277 passed, 54 subtests passed** |
| Полный Chromium E2E | **35 passed** |
| Итоговый повтор Telegram UI после уточнения текста | **2 passed**, desktop 1440 и mobile 390 px |
| Production smoke в временной копии, без .env и Telegram/SMTP | Импорты приложения/бота, настоящий QR SVG, `run.py`, временная SQLite, HTTP `/login` 200 — PASS |
| Runtime/lock/constraints | Все **37 runtime-версий** совпадают |
| `pip check` в проверенном окружении | No broken requirements found |
| `compileall`, `node --check`, `git diff --check` | PASS |
| Недеструктивные миграции на временной БД | Повторный запуск сохраняет данные; новые таблицы создаются |
| Linux / Docker / PostgreSQL | Не запускались локально: macOS arm64, Docker отсутствует; требуются CI и проверка целевой БД |

Включён интеграционный сценарий без пароля: HTTP `/start` → HTTP генерация кода
из профиля → webhook с secret header → исходящий `sendMessage` через замоканный
`urlopen` → настоящие задачи того же пространства → актуальный статус профиля.
Другие проверки покрывают конкурентные update/привязки/worker, потери ответа,
rollback до commit, одноразовые и истёкшие коды, изоляцию пользователей и групп,
диалоги после рестарта, устаревшие кнопки, /done после изменения сортировки и
неудачной отправки списка, CSRF/rate limit, 401/403/409/429/5xx, retry_after,
длинный HTML, временные сбои scheduler, heartbeat и часовые пояса.

Это моки Telegram API, **не проверка настоящего бота**. Браузерная проверка меняет
только временную тестовую БД. Скриншоты Telegram-блока проверены визуально после
удаления одноразового кода со страницы; секретные trace-артефакты не создаются
новыми Telegram E2E.

Первый общий прогон старого пользовательского `venv` обнаружил отсутствие
`qrcode`, хотя он уже есть в requirements/lock. Окончательные проверки выполнены
в существующем отдельном Python 3.12 окружении с проверкой всех runtime-пинов;
рабочий `venv` не переписывался. Первый общий E2E выявил исчерпание общего лимита
`/start`; новые Telegram E2E получили отдельный сервер/БД. Ограничения приложения
не ослаблялись. Несколько старых тестов, прямо требовавших опасного поведения
(удаление webhook/пропуск update), заменены проверками исправленного контракта;
skip/xfail и отключение проверок не добавлялись.

## Запуск и действия оператора

Полная инструкция: [TELEGRAM_BOT_SETUP.md](TELEGRAM_BOT_SETUP.md).
Команды ниже выполняются из корня проекта с заранее настроенным окружением.
Для локального polling используйте один бот-процесс, ту же БД и режим
`TELEGRAM_USE_WEBHOOK=false`. Настоящий production-токен требует отдельного
осознанного решения о запуске/переключении транспорта.

```bash
source .venv/bin/activate
python -m telegram_bot.diagnose
```

Три отдельных терминала:

```bash
python run.py
```

```bash
python -m telegram_bot.polling
```

```bash
python -m telegram_bot.scheduler
```

Для Render оператору осталось:

1. После собственного решения о публикации выбрать эту ревизию и проверить
   Linux CI/сборку текущего Dockerfile с production lock.
2. Проверить постоянную общую PostgreSQL БД, постоянный SECRET_KEY, публичный HTTPS
   origin, username/токен, режим webhook и отключённый TESTING/DISABLE_TELEGRAM.
3. Запустить web, дождаться миграций, затем отдельный scheduler. Проверить свежий
   heartbeat; не полагаться на одно наличие переменной окружения.
4. Явно выполнить setup и read-only сетевую диагностику в защищённом окружении:

```bash
python -m telegram_bot.diagnose --network
python -m telegram_bot.set_webhook
python -m telegram_bot.set_commands
python -m telegram_bot.diagnose --network
```

5. На своём пространстве подтвердить /link → данные → добавить/закрыть задачу →
   тест сводки → плановую отправку → отключение. Сверить изменение той же записи
   на сайте. Для Free web без Shell setup можно выполнить локально с **адресами
   Render**, не запуская polling и не передавая токен аргументом команды.

## Оставшиеся ограничения

- Нужны реальные проверки getMe, getWebhookInfo, HTTPS доставки, общей БД и
  worker в Render. Бесплатный спящий web не гарантирует быстрый ответ и не заменяет
  постоянно работающий scheduler; тариф/ресурсы здесь не менялись.
- Таймаут после фактической отправки может дать повтор сообщения; ошибка между
  отправкой и записью подтверждения scheduler тоже имеет неопределённый исход.
  Повтор бизнес-операции для того же update предотвращается отдельно.
- Outbox ограничен пятью попытками и 24 часами. Терминальные ответы видны в
  диагностике, после исправления пользователь отправляет новую команду.
- SQLite ограничивает параллельную запись во время отправки уведомления; для
  нескольких production-сервисов нужен общий PostgreSQL. Его конкурентные
  сценарии остаются live/staging-проверкой, локальные конкурентные тесты — SQLite.
- Перенос старой SQLite в PostgreSQL требует отдельной пробной миграции всех таблиц
  и проверки ID/устройств. Копирование одинакового SQLite URL между сервисами
  не переносит пространство.
- Небольшие записи дедупликации пока сохраняются без автоматического удаления;
  контролируйте рост БД. Старые URL-секреты поддерживаются, но внешний reverse proxy
  может вести собственные access-логи: предпочтителен переход на secret header.

## Изменённые файлы

Основная логика:
`app/services/telegram_bot.py`, `telegram_delivery.py`, `telegram_state.py`,
`telegram_digest.py`, `telegram_notifications.py`, `task_completion.py`,
`calendar_service.py`.

БД/безопасность/приложение:
`app/core/database.py`, `app/core/migrations.py`, `app/core/telegram_logging.py`,
`app/models/telegram_runtime.py`, `app/models/__init__.py`, `app/main.py`.

Маршруты/UI:
`app/web/routes/telegram.py`, `profile.py`, `tasks.py`,
`app/web/templates/profile/profile.html`, `app/static/js/profile-telegram.js`.

CLI/настройки:
`telegram_bot/polling.py`, `scheduler.py`, `set_webhook.py`, `diagnose.py`, `.env.example`.

Тесты:
`tests/test_telegram_bot.py`, `test_telegram_reliability.py`, `test_migrations.py`,
`tests/e2e/conftest.py`, `tests/e2e/test_telegram_profile.py`.

Документация:
`docs/integrations/TELEGRAM_BOT_SETUP.md`, `docs/DEPLOYMENT.md`, этот отчёт.

Ниже — фактический `git diff --stat` для отслеживаемых файлов. Git не включает
неотслеживаемые новые файлы в эту команду; они перечислены отдельно. Ничего не staged.

```text
 .env.example                            |   2 +
 app/core/database.py                    |   2 +-
 app/core/migrations.py                  |  10 +
 app/main.py                             |   3 +
 app/models/__init__.py                  |   1 +
 app/services/calendar_service.py        |  14 +
 app/services/telegram_bot.py            | 354 ++++++++++++--------
 app/services/telegram_digest.py         |  15 +-
 app/services/telegram_notifications.py  |   9 +-
 app/static/js/profile-telegram.js       |  46 ++-
 app/web/routes/profile.py               |  33 +-
 app/web/routes/tasks.py                 |  54 +--
 app/web/routes/telegram.py              |  62 ++--
 app/web/templates/profile/profile.html  |  10 +-
 docs/DEPLOYMENT.md                      |   8 +
 docs/integrations/TELEGRAM_BOT_SETUP.md | 577 ++++++++++++++------------------
 telegram_bot/polling.py                 | 107 +++---
 telegram_bot/scheduler.py               | 386 ++++++++-------------
 telegram_bot/set_webhook.py             |  64 ++--
 tests/e2e/conftest.py                   |  14 +-
 tests/test_migrations.py                |   1 +
 tests/test_telegram_bot.py              |  70 ++--
 22 files changed, 901 insertions(+), 941 deletions(-)
```

Новые файлы:

```text
app/core/telegram_logging.py
app/models/telegram_runtime.py
app/services/task_completion.py
app/services/telegram_delivery.py
app/services/telegram_state.py
docs/integrations/TELEGRAM_VERIFICATION.md
telegram_bot/diagnose.py
tests/e2e/test_telegram_profile.py
tests/test_telegram_reliability.py
```
