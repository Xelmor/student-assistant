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
| Working tree secret scan (включая ignored .env) | Завершён: локальный Telegram token в ignored `.env`; значения не выводятся |
| Tracked HEAD secret scan | PASS: 237 файлов, 236 уникальных blobs |
| Полный reachable Git history scan | Завершён: 50 commits; исторический небезопасный fallback SECRET_KEY, подробности ниже |
| Docker build/default HTTP/scheduler image | Подготовлены CI checks; локально Docker отсутствует |
| GitHub Actions | Workflow подготовлен, remote run не выполнялся (нет push) |

Обычный прогон: `python -m pytest -q tests --ignore=tests/e2e`.
PostgreSQL: задать только отдельную тестовую `TELEGRAM_TEST_DATABASE_URL`, затем
`python -m pytest -q tests/test_telegram*.py`. Harness применяет migrations,
затем очищает только явную тестовую БД между тестами. Для CI первоначальная
миграция отдельным обязательным шагом: любой migration failure завершает job.
Browser E2E: `python -m pytest -q tests/e2e` (отдельные SQLite DB).
Secret scan: `python3 scripts/ci/scan_secrets.py --history --timeout 60`.
Для безопасного машиночитаемого отчёта добавить `--json`.

### Завершение history scan, 2026-10-03

Проверено на HEAD `1d45e3c5c43a1e2cc5ff81d75e0a7ffd0be24104`, ветка
`fix/telegram-integration`. Исходный timeout был связан с iCloud dataless
Git objects: после загрузки локальных объектов обход завершается. Сканер сам
не обращается в сеть и не загружает недостающие объекты.

Вместо повторного сканирования patch для каждого commit сканер получает деревья
всех reachable commits, читает каждый уникальный blob один раз через
`git cat-file --batch`, затем связывает findings с путями и commits.
Дополнительно проверяются commit/tag metadata и refs, указывающие прямо на
деревья/blobs (в этом checkout есть служебные refs Codex). Временные blob data
хранятся только в приватной временной директории, удаляемой после прохода.

| Область | Проверено | Результат |
|---|---|---|
| Working tree | 242 файла, включая 2 env-файла и ignored local files вне dependency/cache directories | FAIL: только локальный ignored `.env` |
| Tracked HEAD | 1 commit, 237 файлов, 236 blobs | **PASS** |
| Reachable history и служебные tree refs | 50 commits + их metadata, 3 дополнительных tree roots, 351 путь, 863 версии файлов, 820 уникальных blobs, 17 env-версий | FAIL: один потенциально небезопасный исторический ключ в 8 commits |

Повторный полный проход: **5.021 s**, exit **1** (findings, а не timeout).
Количество blobs/путей включает текущие служебные snapshots и может меняться
без новых commits. Результаты повторного прохода совпали: новых findings нет.
Это эвристическая offline-проверка: действительность credentials у провайдера
не проверялась. Reflogs, unreachable objects и refs, существующие только на
remote, не входят в reachable local history. Shallow checkout, недоступные
objects, submodules и external LFS content дают INCOMPLETE (exit 2), а не PASS.
Ignored dependency/cache directories исключены только из working tree обхода;
tracked blobs проверяются без фильтра по расширению или размеру.

Безопасные findings:

- Commit отсутствует; path `.env`; type `telegram_bot_token`;
  fingerprint `sha256:4757a726cf94db9d`. Файл ignored/untracked; этот токен
  в reachable Git history не найден. Наличие локального токена само по себе
  не доказывает утечку и не требует ротации.
- Commit `969bb1548ef65fefd2de118c3e67e508f86b8240`; path `app/main.py`;
  type `secret_key`; fingerprint `sha256:376912d192756c41`.
  Это известный development fallback в `os.getenv`, который старая версия
  `SessionMiddleware` использовала без production guard. Фактическое применение
  этого значения на публичном окружении по Git доказать нельзя. Он также есть
  в commits `3fad685827252c964f419a993bddbd90694396fd`,
  `3a7b6efe83aba3044033cc93b1bb0a8644d7acb6`,
  `06c60e7a4512eccccc03c1d6c0e168815b49bedb`,
  `35c7ed89a15d5282c5caa41775e845692a122b8a`,
  `5f0773611be268d191dc2b08061c0d305f8b10c0`,
  `a98e9bdc25f98889930c94ffc7f59f0614d6cba8`,
  `0e2445521d5cc1002ea5f9e57e8917bd25dcee01`.

Если исторический fallback использовался для публичных сессий, нужно заменить
SECRET_KEY безопасным способом с учётом инвалидирования сессий и доступа к
workspace. Ротация не выполнялась. Переписывание истории для публичного
development-default не требуется и не заменяет ротацию, если он использовался.
История не переписывалась; автоматически объявлять её чистой нельзя.

Обычные placeholders документации не считаются секретами. Проверенные fixture
исключения ограничены точным path/type/SHA-256 fingerprint и пояснены в
`REVIEWED_EXAMPLES`; произвольные файлы tests/docs не исключаются из проверки.
Исторический fallback из `app/core/config.py` отдельно проверен: production
ветка выбрасывала ошибку до его использования, поэтому это development-only
пример. Небезопасный fallback `app/main.py` в исключения не добавлен.

Scanner regression tests: `python -m pytest -q tests/test_secret_scanner.py`
— **58 passed**. Проверяются категории секретов, placeholders, удалённый
секрет в другой ветке, metadata/non-commit refs, разделение working tree/HEAD,
ignored env/key files, большие binary blobs, symlinks, дедупликация blob reads,
shallow/missing/LFS/timeout и отсутствие raw secrets в отчёте.

CI использует `fetch-depth: 0`, общий budget сканера 60 s и ограничение шага
2 минуты; шаг запускает regression tests. При текущем историческом finding
CI должен завершать secret scan с exit 1 до его явного разбора, а не скрывать
результат. Дополнительный проход в отдельном чистом local clone без `.env`
завершился за **4.634 s**: working tree/HEAD PASS, history exit 1 с тем же
fallback (50 commits, 350 путей, 811 blobs; служебные refs Codex clone не
переносит). Remote CI в этом этапе не запускался.

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
image smoke) и разбор найденного исторического fallback SECRET_KEY. History
scan завершён, но имеет finding (см. E). До production rollout нужны проверка
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

Предыдущий hardening уже входит в HEAD `1d45e3c5c43a1e2cc5ff81d75e0a7ffd0be24104`.
В этапе завершения history scan изменены `scripts/ci/scan_secrets.py`,
`.github/workflows/telegram-postgresql.yml` и этот отчёт; добавлен
`tests/test_secret_scanner.py`. Изменения остаются unstaged/untracked.
Commit/push/merge/deploy не выполнялись.
