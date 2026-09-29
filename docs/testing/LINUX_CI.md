# Проверка production-lock на Linux

Workflow: [tests.yml](../../.github/workflows/tests.yml). Цель — Linux x86_64,
Python 3.12. Наличие workflow само по себе не подтверждает успешную проверку Linux.
Основной [Dockerfile](../../Dockerfile) и настройки Render не меняются.

## Запуск

После самостоятельного commit и push в `fix/dependency-reproducibility` workflow
запустится автоматически. Также он запускается для pull request в `main`.
Результаты находятся в **Actions → Linux dependency validation**.

Предусмотрен `workflow_dispatch`: когда файл workflow доступен в default branch,
можно выбрать **Run workflow** и нужную ветку. До этого используйте автоматический
запуск по push. Повторить существующий запуск можно через **Re-run jobs**.
Workflow ничего не публикует и не развёртывает.

## Независимые jobs

- `production-lock`: новый venv, установка только `requirements.lock.txt` с
  `--require-hashes`, `pip check`, сравнение установленных версий с lock и constraints,
  отсутствие dev-пакетов, импорты приложения и Telegram, настоящая генерация QR SVG,
  запуск `run.py` и проверка HTML-ответа HTTP 200 на `/login`.
- `tests`: отдельный venv, сначала production-lock, затем dev requirements с
  `requirements.constraints.txt`; сравнение всех runtime-версий до/после установки.
  Основные тесты, Chromium с системными библиотеками, существующий E2E-набор.
  E2E запускается и после падения основных тестов, если установка зависимостей
  прошла успешно. Любое падение теста делает job красным.
- `docker-lock`: сборка [Dockerfile.ci](../../Dockerfile.ci) на `python:3.12-slim`
  для `linux/amd64`, установка lock с хешами и `pip check`, проверка runtime-версий.
  Затем контейнер без внешней сети запускает те же проверки QR и HTTP.

Jobs не зависят друг от друга. Два известных локальных E2E-падения
`test_final_cta_morph_keyboard_repeat_click_and_existing_onboarding`
на ширинах 1440 и 390 не исключены и не помечены `xfail`.
Их результат на Linux должен быть установлен реальным запуском.

## Изоляция и диагностика

Используются временные SQLite-базы и отдельные тестовые ключи. Загрузка `.env`,
Telegram и SMTP отключены; секреты GitHub/Render не подключаются.
Smoke-проверка копирует только файлы приложения во временный каталог и удаляет
его вместе с базой после завершения.

Официальные actions закреплены по commit SHA; права — только `contents: read`,
Git credentials не сохраняются. У jobs и длительных шагов заданы таймауты.

Артефакты хранятся 7 дней: runtime-версии, результаты smoke, Docker build log,
JUnit со статусами/временем тестов и PNG падений E2E. Из JUnit удалены captured logs,
свойства и содержимое ошибок; подробные traceback остаются в выводе тестового шага.
Playwright trace ZIP, cookies/storage state, `.env` и базы не загружаются.
Скриншоты создаются только в изолированной тестовой сессии.

## Локальная проверка вспомогательных скриптов

В отдельном окружении с установленным lock:

```bash
python scripts/ci/check_runtime.py --production-only --snapshot /tmp/runtime-before.json
python scripts/ci/smoke_runtime.py
python -m pip install -c requirements.constraints.txt -r requirements-dev.txt
python scripts/ci/check_runtime.py --baseline /tmp/runtime-before.json
```

`smoke_runtime.py --require-target` дополнительно требует именно Linux x86_64 /
Python 3.12. Без флага скрипт печатает фактически проверенную платформу.
На macOS это не проверка Linux. Docker при наличии доступного daemon:

```bash
docker build --platform linux/amd64 -f Dockerfile.ci -t student-assistant-lock-ci .
docker run --rm --network none --read-only --tmpfs /tmp:rw,nosuid,size=256m student-assistant-lock-ci
```

Синтаксис GitHub Actions проверяется `actionlint .github/workflows/tests.yml`.
