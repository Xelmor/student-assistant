from pathlib import Path
import unittest

from app.main import app
from app.web.dependencies import templates


class AppSmokeTests(unittest.TestCase):
    @staticmethod
    def _template_dir() -> Path:
        return Path(templates.env.loader.searchpath[0])

    def test_expected_routes_exist(self):
        paths = {route.path for route in app.routes}
        expected = {
            '/',
            '/login',
            '/register',
            '/password-hint',
            '/about',
            '/dashboard',
            '/subjects',
            '/tasks',
            '/schedule',
            '/calendar',
            '/notes',
            '/profile',
            '/onboarding/chat/complete',
            '/onboarding/chat/skip',
            '/onboarding/chat/restart',
            '/manifest.webmanifest',
            '/service-worker.js',
        }
        self.assertTrue(expected.issubset(paths))

    def test_template_root_exists(self):
        template_dir = self._template_dir()
        self.assertTrue(template_dir.exists())
        self.assertTrue((template_dir / 'base.html').exists())

    def test_feature_templates_exist(self):
        template_dir = self._template_dir()
        expected_templates = [
            'auth/index.html',
            'auth/login.html',
            'auth/register.html',
            'auth/forgot_password.html',
            'auth/reset_password.html',
            'about/about.html',
            'dashboard/dashboard.html',
            'subjects/subjects.html',
            'tasks/tasks.html',
            'schedule/schedule.html',
            'calendar/calendar.html',
            'notes/notes.html',
            'profile/profile.html',
            'profile/local_profile.html',
            'errors/error.html',
        ]
        for relative_path in expected_templates:
            with self.subTest(template=relative_path):
                self.assertTrue((template_dir / relative_path).exists())

    def test_split_css_files_exist(self):
        css_dir = Path('app/static/css')
        self.assertTrue(css_dir.exists())
        self.assertTrue((css_dir / 'style.css').exists())
        self.assertTrue((css_dir / 'core').exists())
        self.assertTrue((css_dir / 'pages').exists())

        expected_core_css = {
            'base.css',
            'responsive.css',
            'mobile.css',
        }
        expected_page_css = {
            'dashboard.css',
            'onboarding.css',
            'onboarding-chat.css',
            'entities.css',
            'profile.css',
            'calendar.css',
            'landing.css',
            'tasks-theme.css',
            'subjects-theme.css',
            'schedule-theme.css',
            'auth-theme.css',
            'navbar-tools.css',
            'empty-state.css',
            'actions-feedback.css',
            'mobile-app.css',
            'motion-system.css',
            'user-preferences.css',
            'local-profile.css',
            'profile-simple.css',
            'password-recovery.css',
            'error-pages.css',
            'about.css',
        }

        self.assertTrue(expected_core_css.issubset({path.name for path in (css_dir / 'core').iterdir()}))
        self.assertTrue(expected_page_css.issubset({path.name for path in (css_dir / 'pages').iterdir()}))

    def test_templates_compile(self):
        template_dir = self._template_dir()
        for template_path in template_dir.rglob('*.html'):
            relative_path = template_path.relative_to(template_dir).as_posix()
            with self.subTest(template=relative_path):
                templates.env.get_template(relative_path)

    def test_base_template_uses_local_shell_assets(self):
        text = (self._template_dir() / 'base.html').read_text(encoding='utf-8')
        self.assertIn('/static/vendor/bootstrap/bootstrap.min.css', text)
        self.assertIn('/static/vendor/bootstrap/bootstrap.bundle.min.js', text)
        self.assertIn('/static/css/style.css?v=20260612-password-hint-v1', text)
        self.assertIn('/static/js/base.js?v=20260611-motion-v1', text)
        self.assertIn('/static/js/user-preferences.js?v=20260611-dark-only-v1', text)
        self.assertIn('/static/js/actions-feedback.js?v=20260611-preferences-v1', text)
        self.assertIn('/static/js/navbar-tools.js?v=20260611-preferences-v1', text)
        self.assertIn('/static/js/pwa.js?v=20260612-password-hint-v1', text)
        self.assertNotIn('id="themeToggle"', text)
        self.assertNotIn('student-assistant-theme', text)
        self.assertNotIn('https://cdn.jsdelivr.net', text)
        self.assertNotIn('https://fonts.googleapis.com', text)
        self.assertNotIn('https://fonts.gstatic.com', text)

    def test_pwa_install_prompt_uses_dark_glass_layout(self):
        template_text = (self._template_dir() / 'base.html').read_text(encoding='utf-8')
        styles = Path('app/static/css/mobile.css').read_text(encoding='utf-8')
        script = Path('app/static/js/pwa.js').read_text(encoding='utf-8')

        self.assertIn('id="installSheetTitle"', template_text)
        self.assertIn('aria-modal="true"', template_text)
        self.assertIn('linear-gradient(145deg, rgba(15, 18, 43, 0.97)', styles)
        self.assertIn('backdrop-filter: blur(24px)', styles)
        self.assertIn('#installAction', styles)
        self.assertIn('#installLater', styles)
        self.assertIn('beforeinstallprompt', script)
        self.assertIn('deferredPrompt.prompt()', script)

    def test_error_pages_use_shared_dark_safe_template(self):
        template_text = (self._template_dir() / 'errors/error.html').read_text(encoding='utf-8')
        styles = Path('app/static/css/pages/error-pages.css').read_text(encoding='utf-8')
        script = Path('app/static/js/error-page.js').read_text(encoding='utf-8')
        main_text = Path('app/main.py').read_text(encoding='utf-8')

        self.assertIn('{{ code }}', template_text)
        self.assertIn('{{ title }}', template_text)
        self.assertIn('{{ description }}', template_text)
        self.assertIn('data-error-back', template_text)
        self.assertIn('data-error-reload', template_text)
        self.assertIn('backdrop-filter: blur(24px)', styles)
        self.assertIn('@media (max-width: 767.98px)', styles)
        self.assertIn('window.history.back()', script)
        self.assertIn('window.location.reload()', script)
        self.assertIn('@app.exception_handler(StarletteHTTPException)', main_text)
        self.assertIn('@app.exception_handler(Exception)', main_text)

    def test_dashboard_onboarding_uses_persistent_dark_checklist(self):
        template_text = (self._template_dir() / 'dashboard/dashboard.html').read_text(encoding='utf-8')
        route_text = Path('app/web/routes/dashboard.py').read_text(encoding='utf-8')
        styles = Path('app/static/css/pages/onboarding.css').read_text(encoding='utf-8')
        script = Path('app/static/js/dashboard.js').read_text(encoding='utf-8')

        self.assertIn('id="dashboardOnboarding"', template_text)
        self.assertIn('Добавь первый предмет', route_text)
        self.assertIn('Создай первую задачу', route_text)
        self.assertIn('Настрой расписание', route_text)
        self.assertIn('Открой календарь', route_text)
        self.assertIn('action="/onboarding/complete"', template_text)
        self.assertIn('action="/onboarding/skip"', template_text)
        self.assertIn('linear-gradient(145deg, rgba(15, 23, 42, 0.94)', styles)
        self.assertIn('@media (max-width: 479.98px)', styles)
        self.assertIn('window.requestConfirmation', script)
        self.assertIn("title: 'Onboarding завершён'", script)

    def test_first_run_onboarding_chat_uses_scripted_conversation(self):
        dashboard_text = (self._template_dir() / 'dashboard/dashboard.html').read_text(encoding='utf-8')
        component_text = (self._template_dir() / 'components/onboarding_chat.html').read_text(encoding='utf-8')
        route_text = Path('app/web/routes/dashboard.py').read_text(encoding='utf-8')
        styles = Path('app/static/css/pages/onboarding-chat.css').read_text(encoding='utf-8')
        script = Path('app/static/js/onboarding-chat.js').read_text(encoding='utf-8')
        profile_text = (self._template_dir() / 'profile/profile.html').read_text(encoding='utf-8')

        self.assertIn("include 'components/onboarding_chat.html'", dashboard_text)
        self.assertIn('id="onboardingChatMessages"', component_text)
        self.assertIn('hidden', component_text)
        self.assertIn('role="progressbar"', component_text)
        self.assertIn('action="/onboarding/chat/complete"', component_text)
        self.assertIn('action="/onboarding/chat/skip"', component_text)
        self.assertIn("@router.post('/onboarding/chat/complete')", route_text)
        self.assertIn("@router.post('/onboarding/chat/restart')", route_text)
        self.assertIn('backdrop-filter: blur(14px)', styles)
        self.assertIn('@media (max-width: 479.98px)', styles)
        self.assertIn('window.requestConfirmation', script)
        self.assertIn('chat.hidden = false', script)
        self.assertIn('const buildSteps = () =>', script)
        self.assertIn('restartMode || !state.displayName', script)
        self.assertIn('restartMode || !state.groupName', script)
        self.assertIn('restartMode || !state.course', script)
        self.assertIn("title: 'Профиль настроен'", script)
        self.assertIn('action="/onboarding/chat/restart"', profile_text)

    def test_registration_contains_only_account_creation_fields(self):
        register_text = (self._template_dir() / 'auth/register.html').read_text(encoding='utf-8')

        self.assertIn('name="username"', register_text)
        self.assertIn('name="email"', register_text)
        self.assertIn('name="password"', register_text)
        self.assertIn('name="password_hint"', register_text)
        self.assertNotIn('name="group_name"', register_text)
        self.assertNotIn('name="course"', register_text)

    def test_post_scroll_restore_is_enabled_globally(self):
        base_script = Path('app/static/js/base.js').read_text(encoding='utf-8')
        dashboard_template = (self._template_dir() / 'dashboard/dashboard.html').read_text(encoding='utf-8')

        self.assertIn('student-assistant-scroll-restore', base_script)
        self.assertIn("method !== 'post'", base_script)
        self.assertIn('data-skip-scroll-restore="true"', dashboard_template)

    def test_untrusted_host_is_rejected(self):
        from fastapi.testclient import TestClient

        with TestClient(app, base_url='http://evil.example') as client:
            response = client.get('/')

        self.assertEqual(response.status_code, 400)

    def test_local_bind_host_is_accepted(self):
        from fastapi.testclient import TestClient

        with TestClient(app, base_url='http://0.0.0.0') as client:
            response = client.get('/')

        self.assertEqual(response.status_code, 200)

    def test_security_headers_are_present(self):
        from fastapi.testclient import TestClient

        with TestClient(app) as client:
            response = client.get('/')

        self.assertEqual(response.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(response.headers['x-frame-options'], 'DENY')
        self.assertEqual(response.headers['referrer-policy'], 'strict-origin-when-cross-origin')
        self.assertIn("default-src 'self'", response.headers['content-security-policy'])
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        self.assertIn('camera=()', response.headers['permissions-policy'])
        self.assertEqual(response.headers['cache-control'], 'no-store')

    def test_theme_switcher_is_removed(self):
        template_text = (self._template_dir() / 'base.html').read_text(encoding='utf-8')
        navbar_script = Path('app/static/js/navbar-tools.js').read_text(encoding='utf-8')
        navbar_styles = Path('app/static/css/pages/navbar-tools.css').read_text(encoding='utf-8')

        self.assertIn('dashboard-moon-icon', template_text)
        self.assertNotIn('data-theme-quick-toggle', template_text)
        self.assertNotIn('themeQuickToggle', template_text)
        self.assertNotIn('theme-icon-sun', template_text)
        self.assertNotIn('id="themeToggle"', template_text)
        self.assertNotIn('student-assistant-theme', template_text + navbar_script)
        self.assertNotIn('theme-light', navbar_styles)

    def test_profile_preferences_use_safe_local_storage_fallback(self):
        template_text = (self._template_dir() / 'profile/profile.html').read_text(encoding='utf-8')
        base_text = (self._template_dir() / 'base.html').read_text(encoding='utf-8')
        preferences_script = Path('app/static/js/user-preferences.js').read_text(encoding='utf-8')

        self.assertIn('id="profile-settings"', template_text)
        self.assertNotIn('id="profileThemeSelect"', template_text)
        self.assertIn('id="profileTimezoneSelect"', template_text)
        self.assertIn('id="profileMenuPanel"', base_text)
        self.assertNotIn('data-theme-quick-toggle', base_text)
        self.assertIn("root.dataset.appTheme = 'dark'", preferences_script)
        self.assertIn('studentAssistant.accentColor', preferences_script)
        self.assertIn('studentAssistant.timezone.', preferences_script)
        self.assertIn('studentAssistant.avatar.', preferences_script)
        self.assertIn('window.requestConfirmation', Path('app/static/js/actions-feedback.js').read_text(encoding='utf-8'))

    def test_profile_settings_page_is_compact(self):
        template_text = (self._template_dir() / 'profile/profile.html').read_text(encoding='utf-8')
        styles = Path('app/static/css/pages/profile-simple.css').read_text(encoding='utf-8')

        self.assertIn('profile-simple-layout', template_text)
        self.assertIn('profile-simple-sidebar', template_text)
        self.assertIn('profile-simple-data', template_text)
        self.assertNotIn('profile-activity-card', template_text)
        self.assertNotIn('profile-history-card', template_text)
        self.assertIn('grid-template-columns: 14.5rem minmax(0, 1fr)', styles)

    def test_local_private_profile_uses_dark_dashboard_layout(self):
        template_text = (self._template_dir() / 'profile/local_profile.html').read_text(encoding='utf-8')
        styles = Path('app/static/css/pages/local-profile.css').read_text(encoding='utf-8')

        self.assertIn('local-private-page', template_text)
        self.assertIn('local-private-sidebar', template_text)
        self.assertIn('local-private-data-list', template_text)
        self.assertIn('ALLOW_LOCAL_PRIVATE_DATA=true', template_text)
        self.assertIn('Пароль не отображается в целях безопасности.', template_text)
        self.assertNotIn('<table', template_text)
        self.assertIn('grid-template-columns: minmax(15rem, 17.5rem)', styles)
        self.assertIn('overflow-x: hidden', styles)

    def test_password_recovery_uses_dark_auth_layout(self):
        forgot_text = (self._template_dir() / 'auth/forgot_password.html').read_text(encoding='utf-8')
        reset_text = (self._template_dir() / 'auth/reset_password.html').read_text(encoding='utf-8')
        styles = Path('app/static/css/pages/password-recovery.css').read_text(encoding='utf-8')
        script = Path('app/static/js/password-recovery.js').read_text(encoding='utf-8')

        self.assertIn('auth-recovery-page', forgot_text)
        self.assertIn('password-recovery-card', forgot_text)
        self.assertIn('name="email"', forgot_text)
        self.assertIn('name="new_password"', reset_text)
        self.assertIn('name="confirm_password"', reset_text)
        self.assertIn('aria-live="assertive"', forgot_text)
        self.assertIn('data-recovery-form', forgot_text + reset_text)
        self.assertIn('linear-gradient(145deg', styles)
        self.assertIn('prefers-reduced-motion', styles)
        self.assertIn('Введите корректный email.', script)

    def test_mobile_card_layouts_are_present(self):
        mobile_styles = Path('app/static/css/pages/mobile-app.css').read_text(encoding='utf-8')
        calendar_template = (self._template_dir() / 'calendar/calendar.html').read_text(encoding='utf-8')

        self.assertIn('overflow-x: hidden', mobile_styles)
        self.assertIn('.tasks-task-row', mobile_styles)
        self.assertIn('.schedule-event-row', mobile_styles)
        self.assertIn('.calendar-timeline-scroll', mobile_styles)
        self.assertIn('.calendar-mobile-week', mobile_styles)
        self.assertIn('calendar-mobile-event-copy', calendar_template)

    def test_shared_empty_state_component_is_reused(self):
        component = (self._template_dir() / 'components/empty_state.html').read_text(encoding='utf-8')
        styles = Path('app/static/css/pages/empty-state.css').read_text(encoding='utf-8')
        templates = [
            'base.html',
            'dashboard/dashboard.html',
            'tasks/tasks.html',
            'subjects/subjects.html',
            'schedule/schedule.html',
            'calendar/calendar.html',
            'notes/notes.html',
        ]

        self.assertIn('{% macro empty_state(', component)
        self.assertIn('empty-state__action', component)
        self.assertIn('.empty-state--compact', styles)
        self.assertIn('.empty-state--timeline', styles)
        for template_name in templates:
            with self.subTest(template=template_name):
                text = (self._template_dir() / template_name).read_text(encoding='utf-8')
                self.assertIn("components/empty_state.html", text)

    def test_destructive_actions_use_shared_confirmation_and_toasts(self):
        template_text = (self._template_dir() / 'base.html').read_text(encoding='utf-8')
        feedback_script = Path('app/static/js/actions-feedback.js').read_text(encoding='utf-8')
        feedback_styles = Path('app/static/css/pages/actions-feedback.css').read_text(encoding='utf-8')

        self.assertIn('id="confirmDialog"', template_text)
        self.assertIn('id="toastRegionPolite"', template_text)
        self.assertIn('id="toastRegionAssertive"', template_text)
        self.assertIn('window.showToast', feedback_script)
        self.assertIn("event.preventDefault()", feedback_script)
        self.assertIn(r'\/tasks\/delete', feedback_script)
        self.assertIn(r'\/subjects\/delete', feedback_script)
        self.assertIn(r'\/notes\/delete', feedback_script)
        self.assertIn(r'\/schedule\/delete', feedback_script)
        self.assertIn(r'\/calendar\/session\/delete', feedback_script)
        self.assertIn('.confirm-dialog__button--confirm', feedback_styles)
        self.assertIn('.app-toast--error', feedback_styles)

    def test_motion_system_is_subtle_and_accessible(self):
        motion_styles = Path('app/static/css/pages/motion-system.css').read_text(encoding='utf-8')
        base_script = Path('app/static/js/base.js').read_text(encoding='utf-8')

        self.assertIn('premium-page-enter', motion_styles)
        self.assertIn('translateY(6px)', motion_styles)
        self.assertIn('@media (hover: hover) and (pointer: fine)', motion_styles)
        self.assertIn('@media (prefers-reduced-motion: reduce)', motion_styles)
        self.assertIn('animation: none !important', motion_styles)
        self.assertIn('window.animateMotionItems', base_script)

    def test_local_bootstrap_vendor_files_exist(self):
        vendor_dir = Path('app/static/vendor/bootstrap')
        expected_files = {
            'bootstrap.min.css',
            'bootstrap.bundle.min.js',
        }
        self.assertTrue(vendor_dir.exists())
        self.assertTrue(expected_files.issubset({path.name for path in vendor_dir.iterdir()}))


if __name__ == '__main__':
    unittest.main()
