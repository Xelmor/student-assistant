# Student Assistant — Graphite + Ice Blue

Обновлена визуальная система: graphite-фон, непрозрачные поверхности, ice-blue акцент, приглушённые статусы, однотонные кнопки и заголовки, мягкие тени. Радиусы карточек 14 px, основных кнопок 12 px. Существующие анимационные сценарии и тайминги сохранены; изменены цвета эффектов и чрезмерный hover scale.

Сетка, размеры блоков, отступы, позиционирование, HTML-структура, маршруты, backend и данные не изменены. В шаблонах изменены только theme-color, версии ресурсов, оформление SVG и название акцента. В двух JS-файлах обновлены только палитры и подписи. В service worker изменены версия кэша и список ресурсов.

Работающая версия приложения принудительно использует dark theme (`applyDarkTheme`); переключателя светлой темы нет. Старые светлые стили оставлены в legacy-файлах, их нейтральная палитра не переписана.

## Глобальные токены

Единый источник — `app/static/css/theme.css`, подключённый последним из `style.css`. Локальные `--dash-*`, `--tasks-*`, `--subjects-*`, `--schedule-*`, `--calendar-*`, `--notes-*`, `--profile-*`, `--landing-*`, `--auth-*`, `--about-*` теперь ссылаются на общие токены. Имена с `purple` сохранены для совместимости с существующим JS и сохранёнными настройками; фиолетового цвета за ними больше нет.

| Переменная | Значение |
| --- | --- |
| `--bg` | `#0D0F12` |
| `--bg-secondary` | `#111419` |
| `--surface` | `#15181D` |
| `--surface-elevated` | `#1A1E24` |
| `--border` | `#272B32` |
| `--border-hover` | `#343A44` |
| `--text` | `#F2F4F7` |
| `--text-secondary` | `#8D96A3` |
| `--text-muted` | `#69717D` |
| `--accent` | `#6C8EFF` |
| `--accent-hover` | `#82A0FF` |
| `--accent-rgb` | `108 142 255` |
| `--palette-ice` | `#6C8EFF` |
| `--palette-rose` | `#B77F9F` |
| `--palette-cyan` | `#70A7B8` |
| `--accent-soft` | `rgba(108, 142, 255, 0.10)` |
| `--accent-border` | `rgba(108, 142, 255, 0.28)` |
| `--accent-glow` | `rgba(108, 142, 255, 0.06)` |
| `--success` | `#59A881` |
| `--success-rgb` | `89 168 129` |
| `--warning` | `#C99A55` |
| `--warning-rgb` | `201 154 85` |
| `--danger` | `#C76767` |
| `--danger-rgb` | `199 103 103` |
| `--info` | `var(--accent)` |
| `--surface-strong` | `var(--surface-elevated)` |
| `--surface-muted` | `var(--bg-secondary)` |
| `--border-strong` | `var(--border-hover)` |
| `--muted` | `var(--text-secondary)` |
| `--primary` | `var(--accent)` |
| `--primary-dark` | `var(--accent-hover)` |
| `--accent-strong` | `var(--accent-hover)` |
| `--danger-soft` | `rgb(var(--danger-rgb) / 0.10)` |
| `--shadow` | `0 4px 16px rgba(0, 0, 0, 0.12)` |
| `--shadow-hover` | `0 6px 20px rgba(0, 0, 0, 0.16)` |
| `--radius-xl` | `14px` |
| `--radius-lg` | `14px` |
| `--radius-md` | `12px` |
| `--radius-control` | `12px` |
| `--bs-body-color` | `var(--text)` |
| `--bs-body-bg` | `var(--bg)` |
| `--bs-border-color` | `var(--border)` |

Дополнительные приглушённые акценты профиля сохранены. CSS `--accent-rgb` синхронизирован с выбранным `data-accent`; основной акцент по умолчанию — Ice Blue. Ключ `purple` в localStorage сохранён для совместимости, отображаемая подпись — «Ледяной синий».

## Проверки

- Chromium: Landing, Dashboard, Tasks, Subjects, Schedule, Calendar, Notes, Profile/Settings, About на ширинах 1440 и 390 px. Проверены пустые состояния и страницы с тестовыми данными в отдельной временной SQLite-базе. Нет JS-ошибок и горизонтального переполнения проверенных основных страниц.
- Проверены переключение всех дополнительных акцентов и фокус поля задачи.
- CSS разобран tinycss2: ошибок синтаксиса и циклических ссылок переменных нет. Сравнение деклараций с исходной версией не обнаружило изменений геометрии, типографических размеров, animation/transition таймингов.
- `pytest -q tests/test_smoke.py tests/test_about_page.py tests/e2e`: **31 passed**, 41 subtests passed.
- `pytest -q tests`: **172 passed, 19 failed**, 50 subtests passed. Все 19 падений воспроизводятся на исходном HEAD: account normalization, onboarding и password hint. В изолированной исходной копии было 171 passed / 20 failed; дополнительное старое падение касалось устаревшей версии CSS в smoke-тесте. Backend не менялся.
- Запуск pytest без явного `tests` дополнительно собирает старые тесты из `.sa_patch_backups` и приводит к конфликтам имён модулей. Проверки запускались с явной директорией.
- `git diff --check`: без замечаний.

## Контраст

На поверхности `#15181D`: основной текст — 16.15:1, вторичный — 5.95:1, акцент — 5.89:1.

Сохранено запрошенное сочетание белого текста с кнопкой `#6C8EFF`: 3.02:1 (hover `#82A0FF`: 2.49:1). Оно не достигает WCAG AA 4.5:1 для мелкого текста. Muted `#69717D` на поверхности — 3.61:1; используется для placeholder/приглушённых элементов. Полное соответствие AA не заявляется; для него потребуется скорректировать заданные цвета кнопок и muted.

## Где остались старые purple-значения

- `app/web/templates/subjects/subjects.html`: `#7c3aed` в пользовательской палитре предметов, `#8b5cf6` в custom color input. Это существующая функция выбора цвета, а не системный акцент; Jinja-список и данные не менялись.
- `app/web/routes/schedule.py:237` и `app/web/routes/notes.py:51`: `#8b5cf6` как backend fallback цвета предмета. Оставлены в соответствии с запретом менять backend.
- `app/static/css/calendar.css`: почти белые lavender-оттенки `rgba(250, 246, 255, ...)` в старых светлых правилах (строки 192, 403, 513, 684, 1010). Не являются яркими purple-акцентами; активная тёмная тема переопределяет эти поверхности.
- Исторические `.bak`, `.sa_patch_backups` и сторонний Bootstrap не редактировались. В активных CSS темах страниц ярких hardcoded purple/violet больше нет, включая динамические rgba с alpha-переменными.
- Сохранённые пользователем цвета предметов могут оставаться любыми: данные не мигрировались.

## Изменённые файлы

- `app/static/css/calendar.css`
- `app/static/css/entities.css`
- `app/static/css/mobile.css`
- `app/static/css/pages/about.css`
- `app/static/css/pages/actions-feedback.css`
- `app/static/css/pages/auth-theme.css`
- `app/static/css/pages/calendar.css`
- `app/static/css/pages/dashboard-theme.css`
- `app/static/css/pages/empty-state.css`
- `app/static/css/pages/entry.css`
- `app/static/css/pages/error-pages.css`
- `app/static/css/pages/landing.css`
- `app/static/css/pages/local-profile.css`
- `app/static/css/pages/mobile-app.css`
- `app/static/css/pages/motion-system.css`
- `app/static/css/pages/navbar-tools.css`
- `app/static/css/pages/notes-theme.css`
- `app/static/css/pages/onboarding-chat.css`
- `app/static/css/pages/onboarding.css`
- `app/static/css/pages/password-recovery.css`
- `app/static/css/pages/profile-simple.css`
- `app/static/css/pages/profile.css`
- `app/static/css/pages/schedule-theme.css`
- `app/static/css/pages/subjects-theme.css`
- `app/static/css/pages/tasks-theme.css`
- `app/static/css/pages/user-preferences.css`
- `app/static/css/responsive.css`
- `app/static/css/style.css`
- `app/static/css/theme.css`
- `app/static/js/onboarding-chat.js`
- `app/static/js/user-preferences.js`
- `app/static/manifest.webmanifest`
- `app/static/pwa/icon-app.svg`
- `app/static/service-worker.js`
- `app/web/templates/about/about.html`
- `app/web/templates/auth/forgot_password.html`
- `app/web/templates/auth/index.html`
- `app/web/templates/auth/login.html`
- `app/web/templates/auth/register.html`
- `app/web/templates/auth/reset_password.html`
- `app/web/templates/base.html`
- `app/web/templates/calendar/calendar.html`
- `app/web/templates/dashboard/dashboard.html`
- `app/web/templates/errors/error.html`
- `app/web/templates/notes/notes.html`
- `app/web/templates/profile/local_profile.html`
- `app/web/templates/profile/profile.html`
- `app/web/templates/schedule/schedule.html`
- `app/web/templates/subjects/subjects.html`
- `app/web/templates/tasks/tasks.html`
- `docs/GRAPHITE_ICE_BLUE.md`
- `tests/test_about_page.py`
- `tests/test_smoke.py`
