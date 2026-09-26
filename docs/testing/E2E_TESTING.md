# End-to-end тесты

E2E-слой использует Python Playwright и `pytest-playwright`. Проект уже построен
на Python, FastAPI и Jinja, поэтому отдельный Node/npm toolchain для одного
набора браузерных тестов здесь не нужен.

## Установка

```bash
source venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
```

Для CI на Linux можно установить Chromium вместе с системными зависимостями:

```bash
python -m playwright install --with-deps chromium
```

## Запуск

Все E2E-тесты:

```bash
pytest -q tests/e2e
```

Только сценарий авторизации:

```bash
pytest -q tests/e2e/test_auth.py
```

Открыть настоящий браузер во время теста:

```bash
pytest tests/e2e/test_auth.py --headed
```

Пошаговая отладка Playwright Inspector:

```bash
PWDEBUG=1 pytest -s tests/e2e/test_auth.py
```

Обычный `pytest -q` намеренно не собирает `tests/e2e`: браузерные тесты
запускаются только при явном указании папки или файла.

## Изоляция и безопасность

`tests/e2e/conftest.py` автоматически:

- выбирает свободный локальный порт;
- запускает Uvicorn перед тестами и останавливает его после них;
- создаёт временную SQLite-базу `test_e2e.db` вне рабочей базы проекта;
- задаёт `APP_ENV=test` и `TESTING=true`;
- отключает Telegram через `DISABLE_TELEGRAM=true`, пустые токены и выключенный webhook;
- отключает SMTP и не отправляет письма;
- блокирует service worker в браузерном контексте;
- удаляет временную базу вместе с временным каталогом pytest.

Тестовый сервер не читает и не изменяет пользовательскую базу. Значения,
переданные runner-ом через окружение, имеют приоритет над локальным `.env`.

## Первый сценарий

`tests/e2e/test_auth.py` проверяет полный пользовательский путь:

1. регистрация уникального аккаунта;
2. переход на dashboard;
3. пропуск onboarding;
4. выход через меню пользователя;
5. повторный вход по email и паролю;
6. отображение dashboard и имени пользователя.

## Артефакты падений

При падении теста сохраняются:

- полноэкранный screenshot;
- Playwright trace с DOM snapshots и сетевыми действиями.

Файлы находятся в `test-results/e2e/` и исключены из Git. Trace открывается так:

```bash
python -m playwright show-trace test-results/e2e/<trace>.zip
```

Эта структура готова к запуску в CI: достаточно установить
`requirements-dev.txt`, браузер Chromium и выполнить `pytest -q tests/e2e`.
