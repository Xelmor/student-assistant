# Telegram production-hardening — 2026-10-03

Ветка: `fix/telegram-integration`. Новые пользовательские функции не добавлялись.
Commit/push/merge/deploy и настоящий Bot API не выполнялись. Этот отчёт заменяет
исторический отчёт ранней интеграции. Локальные проверки не равны разрешению
production rollout: остаются CI/image и live hosting gates ниже.

## A. Аудит до исправлений

Проверены webhook, polling, scheduler, модели/миграции, outbox, state, настройки,
CLI setup/diagnose, Dockerfile, CI, `.env` ignore и deployment docs.

Реальные проблемы и пробелы:

1. При включённом Telegram production config допускал SQLite и polling. Два Render
   сервиса с одинаковым SQLite URL всё равно используют разные файлы.
2. Нет PostgreSQL CI; тестовый harness всегда создавал SQLite через create_all.
   Поэтому PostgreSQL locking, SQL constraints и чистые migrations не были доказаны.
3. Разный порядок User/settings/event locks у callbacks и scheduler создавал риск
   PostgreSQL deadlock. SQLite сериализовала записи и скрывала этот риск.
4. Одновременный startup web/worker не сериализовал create_all и migration registry.
5. Pending reply проверял только user/chat IDs: после unlink/relink с теми же IDs
   мог отправиться ответ старого подключения. После ожидания owner lock состояние
   reply также требовало повторной проверки.
6. Ошибка открытия session могла завершить scheduler loop; ошибка одного job
   прерывала оставшиеся jobs текущей итерации. SIGTERM завершал процесс немедленно.
7. Diagnose не проверял все необходимые таблицы/версии миграций и не агрегировал
   readiness blockers. Явный production username и сильный webhook secret не
   требовались. `.env` игнорировался, но варианты `.env.*` — не все.
8. Локально нет Docker CLI/daemon. Linux production image нельзя подтвердить этим
   macOS прогоном; требуется реальный CI run до merge.

Уже корректные части, сохранённые без переизобретения:

- Webhook endpoint `/telegram/webhook` (или настроенный путь), secret-header
  compare_digest, лимит тела, проверка JSON/update_id, HTTP 403/400/413/503.
  Критическая ошибка логируется безопасно и возвращает 503.
- `telegram_updates` PK update_id: бизнес-операция и reply пишутся одной
  транзакцией. Повтор update не повторяет бизнес-операцию. Durable outbox переживает
  restart, имеет lease, максимум 5 попыток и срок 24 часа.
- `telegram_state` PK key, bounded retry/backoff, delivery keys и уникальный
  deadline delivery constraint уже присутствовали.
- Polling проверял getWebhookInfo и не удалял webhook автоматически. Теперь
  дополнительно запрещён production polling и production delete-for-polling.
- Owner-scoped SQL, private-chat guard, одноразовые link-коды, шесть BOT_COMMANDS,
  HMAC workspace credentials и обязательный постоянный production SECRET_KEY.

## B. Исправления

- Введён явный `TELEGRAM_MODE` с совместимостью `TELEGRAM_USE_WEBHOOK`; конфликт
  отклоняется. `PUBLIC_ORIGIN` поддерживается как alias `PUBLIC_BASE_URL`.
- Включённый production Telegram требует PostgreSQL, webhook, username,
  HTTPS origin и webhook secret длиной 32–256 URL-safe символов. Origin не может
  содержать credentials/query/fragment. SECRET_KEY и DATABASE_URL скрыты в repr.
- Миграции в одной транзакции; PostgreSQL `pg_advisory_xact_lock` перед всем DDL.
- Единый порядок: User → settings/task/event/delivery rows. Приём update сначала
  сериализуется dialog-key; scheduler этот dialog-key не захватывает.
- Pending reply сохраняет timestamp текущей привязки и отменяется при её смене;
  после ожидания блокировок status перечитывается. Legacy pending replies без
  binding metadata могут быть безопасно отменены.
- Scheduler продолжает работу после session/job failures, пишет job/result,
  retry attempt/terminal и heartbeat `completed`/`degraded`. SIGTERM/SIGINT дают
  завершить текущую итерацию и закрыть сессии.
- Diagnose показывает database kind/accessibility/fingerprint, shared-hosting
  verification status, все tables/missing migrations, heartbeat, pending/failed
  replies, network pending updates и production_readiness_blockers.
- Новый PostgreSQL CI и opt-in harness запускают существующие Telegram тесты
  на настоящем PostgreSQL; добавлены concurrent/process smoke проверки.
- Две HTML stress fixtures приведены к реальному лимиту Subject.name (100).
  Количество занятий, escaping, emoji, pagination и Telegram length assertions
  сохранены. PostgreSQL раньше отвергал эти фикстуры, SQLite принимала.

## C. Файлы

Runtime:
`app/core/config.py`, `app/core/migrations.py`, `app/services/telegram_bot.py`,
`app/services/telegram_class_reminders.py`, `app/services/telegram_delivery.py`,
`telegram_bot/diagnose.py`, `telegram_bot/polling.py`, `telegram_bot/scheduler.py`,
`telegram_bot/set_webhook.py`.

Тесты/CI:
`tests/telegram_database.py`, `tests/test_telegram_production.py`,
`tests/test_telegram_bot.py`, `tests/test_telegram_evening_digest.py`,
`tests/test_telegram_weekly_digest.py`, `.github/workflows/telegram-postgresql.yml`,
`scripts/ci/check_scheduler_image.sh`, `scripts/ci/smoke_telegram_processes.py`,
`scripts/ci/scan_secrets.py`.

Документация/секреты:
`.env.example`, `.gitignore`, `docs/DEPLOYMENT.md`,
`docs/integrations/TELEGRAM_BOT_SETUP.md`, этот файл.
Dockerfile и production dependency lock не менялись.

## D–E. Проверки и воспроизведение

Локальный PostgreSQL 16.15 запущен в отдельном временном UTF-8 кластере на loopback,
без production data. Только allowlisted `sa_telegram_test_*` DB разрешены для
разрушающего reset тестовых данных. Ни DATABASE_URL пользователя, ни реальная
SQLite БД не сбрасывались. Отдельные чистые DB/schema использованы для startup и
concurrent migration tests. PostgreSQL подтвердил PK/unique constraints,
FOR UPDATE, повторные update/callback, restart и конкурентных workers.

Проверенные гонки: morning/evening/weekly, deadline, class reminder, snooze;
create confirm, done, reschedule, note delete и snooze callback; scheduler вместе
с изменением настроек. Для каждого подтверждённого ключа — одна мутация/отправка.
Отдельный HTTP smoke создаёт passwordless workspace, связывает fake Telegram,
проходит start/today/tasks, natural-language confirm, note/search и scheduler pass.

| Проверка | Результат |
|---|---|
| Финальный полный SQLite pytest | 863 passed, 54 subtests |
| Финальный полный Telegram/scheduler на PostgreSQL | 707 passed |
| Новый hardening-набор (включён в полные прогоны) | 30 passed на PostgreSQL; 30 passed на SQLite |
| Весь Chromium E2E | 41 passed, включая 8 Telegram desktop/mobile |
| Production web + два настоящих worker-процесса, чистая PostgreSQL | HTTP 200, migrations, heartbeat, reconnect после обрыва DB connections, graceful SIGTERM: PASS |
| pip check | No broken requirements found |
| Runtime lock/constraints | 37 runtime versions match |
| Python syntax / shell syntax / git diff --check | PASS |
| Offline scan текущих файлов | 0 findings; эвристика, не гарантия |
| Полный Git history scan | Не завершён: локальный git log превышает таймаут; секрет по этому результату не обнаружен и отсутствие не доказано |
| Docker build/default HTTP/scheduler image | Подготовлены CI checks; локально Docker отсутствует |
| GitHub Actions | Workflow подготовлен, remote run не выполнялся (нет push) |

Обычный прогон: `python -m pytest -q tests --ignore=tests/e2e`.
PostgreSQL: задать только отдельную тестовую `TELEGRAM_TEST_DATABASE_URL`, затем
`python -m pytest -q tests/test_telegram*.py`. Harness применяет migrations,
затем очищает только явную тестовую БД между тестами. Для CI первоначальная
миграция отдельным обязательным шагом: любой migration failure завершает job.
Browser E2E: `python -m pytest -q tests/e2e` (отдельные SQLite DB).
Secret scan: `python scripts/ci/scan_secrets.py --history` (включает все локальные
ветки, не печатает значения, прерывает job при findings/незавершённом сканировании).

## F–H. Production architecture / Render / env

Схема и точные команды: [DEPLOYMENT.md](../DEPLOYMENT.md#telegram-production-topology-hardening-2026-10-03).
Web: `python run.py`; отдельный Background Worker:
`python -m telegram_bot.scheduler`; одна постоянная PostgreSQL для обоих.
Публичный HTTPS нужен web, worker HTTP-порт не нужен. Миграции запускаются при
старте обоих процессов и сериализуются. Web не запускает scheduler внутри себя.

Общие env names:
`APP_ENV`, `DATABASE_URL`, `SECRET_KEY`, `COOKIE_SECURE`, `PUBLIC_ORIGIN`,
`ALLOWED_HOSTS`, `APP_TIMEZONE`, `TELEGRAM_MODE`, `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_BOT_USERNAME`, `TELEGRAM_WEBHOOK_SECRET`, `TELEGRAM_WEBHOOK_PATH`,
`DISABLE_TELEGRAM`, `TESTING`, `PYTHON_DOTENV_DISABLED`.
Web: `HOST`, `PORT`, `RELOAD`. Worker: `TELEGRAM_DIGEST_CHECK_INTERVAL_SECONDS`,
`TELEGRAM_BOT_LOG_LEVEL`. Legacy aliases: `PUBLIC_BASE_URL`, `TELEGRAM_USE_WEBHOOK`.
Секретные значения не входят в этот отчёт.

Free Render web засыпает, а worker должен быть always-on. Не обещаем real-time
reminders на спящем или отсутствующем процессе. Варианты: Background Worker,
внешний scheduler подходящей частоты либо другой always-on runtime.
Источники: [Render Free](https://render.com/docs/free),
[Background Workers](https://render.com/docs/background-workers).

## I. Ручной live smoke после отдельно разрешённого deploy

1. `python -m telegram_bot.diagnose --network`.
2. `python -m telegram_bot.set_commands` — ровно шесть команд.
3. `python -m telegram_bot.set_webhook`.
4. Повторить `diagnose --network`: mode webhook, username/webhook match,
   database accessible, missing tables/migrations пусты, свежий heartbeat.
5. `/start`.
6. Привязать существующий профиль и сверить workspace на сайте.
7. «📍 Сейчас».
8. «📅 Сегодня».
9. «🗓 Неделя» и расписание.
10. «📌 Задачи».
11. Создать задачу обычной фразой, явно подтвердить.
12. Выполнить/восстановить задачу.
13. Создать заметку и проверить сайт.
14. Поиск и `поиск: ...`.
15. Настройки.
16. Включить напоминание о тестовой паре, проверить доставку и snooze один раз.
17. Evening preview без изменения delivery marker.
18. Weekly preview без изменения delivery marker.
19. Unlink/relink, убедиться, что старые pending replies не отправились.

## J. Что не подтверждено / release gates

До merge нужны зелёные remote CI (включая настоящий Linux Docker build и worker
image smoke) и завершённый history scan. До production rollout нужны проверка
реального bot username/token/header secret, публичного TLS/webhook, общей Render
БД и always-on worker. Эти действия здесь не выполнялись и не подразумеваются.

Ни mock transport, ни тестовый HTML Telegram viewer не проверяют официальный
Telegram client. Hosting access logs, реальный тариф/ресурсы/спящий web,
production data migration/backup/restore требуют проверки владельцем окружения.

Даже после успешных concurrency tests потеря Telegram acknowledgement или crash
между send и DB commit могут дать повтор внешнего сообщения. Бизнес-операции
по одному update защищены отдельно. Нет обещания exactly-once внешней доставки.
Grace windows и bounded retries могут оставить недоставленное уведомление при
длительном downtime. Записи дедупликации/TTL автоматически не удаляются.
SECRET_KEY не ротировать при обычном deploy: он участвует в доступе к workspace.

## K. Git status

Изменения из списка C остаются unstaged в `fix/telegram-integration`.
Новые workflow, три CI scripts, test DB helper и hardening tests — untracked до
отдельной команды пользователя. Commit/push/merge/deploy не выполнялись.
