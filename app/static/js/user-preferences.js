(() => {
    const root = document.documentElement;
    const userId = root.dataset.userId || 'guest';
    const keys = {
        accent: 'studentAssistant.accentColor',
        timezone: `studentAssistant.timezone.${userId}`,
        timeFormat: `studentAssistant.timeFormat.${userId}`,
        avatar: `studentAssistant.avatar.${userId}`,
    };
    const defaults = {
        accent: 'purple',
        timezone: 'system',
        timeFormat: '24',
        avatar: 'violet',
    };
    const accents = {
        purple: { base: '#8b5cf6', hover: '#7c3aed', soft: 'rgba(139, 92, 246, 0.15)', border: 'rgba(139, 92, 246, 0.34)', glow: 'rgba(139, 92, 246, 0.22)' },
        blue: { base: '#3b82f6', hover: '#2563eb', soft: 'rgba(59, 130, 246, 0.15)', border: 'rgba(59, 130, 246, 0.34)', glow: 'rgba(59, 130, 246, 0.22)' },
        pink: { base: '#ec4899', hover: '#db2777', soft: 'rgba(236, 72, 153, 0.15)', border: 'rgba(236, 72, 153, 0.34)', glow: 'rgba(236, 72, 153, 0.22)' },
        green: { base: '#10b981', hover: '#059669', soft: 'rgba(16, 185, 129, 0.15)', border: 'rgba(16, 185, 129, 0.34)', glow: 'rgba(16, 185, 129, 0.22)' },
        orange: { base: '#f59e0b', hover: '#d97706', soft: 'rgba(245, 158, 11, 0.15)', border: 'rgba(245, 158, 11, 0.34)', glow: 'rgba(245, 158, 11, 0.22)' },
        cyan: { base: '#06b6d4', hover: '#0891b2', soft: 'rgba(6, 182, 212, 0.15)', border: 'rgba(6, 182, 212, 0.34)', glow: 'rgba(6, 182, 212, 0.22)' },
    };
    const allowedTimezones = new Set(['system', 'Europe/Moscow', 'Europe/Vienna', 'Europe/London', 'Asia/Shanghai', 'UTC']);
    const allowedTimeFormats = new Set(['24', '12']);
    const allowedAvatars = new Set(['violet', 'blue', 'pink', 'green', 'orange', 'cyan']);
    const originalText = new Map();

    const read = (key, fallback) => {
        try {
            return window.localStorage.getItem(key) || fallback;
        } catch (_) {
            return fallback;
        }
    };

    const write = (key, value) => {
        try {
            window.localStorage.setItem(key, value);
            return true;
        } catch (_) {
            return false;
        }
    };

    const remove = (key) => {
        try {
            window.localStorage.removeItem(key);
        } catch (_) {
        }
    };

    const getSettings = () => {
        const accent = read(keys.accent, defaults.accent);
        const timezone = read(keys.timezone, defaults.timezone);
        const timeFormat = read(keys.timeFormat, defaults.timeFormat);
        const avatar = read(keys.avatar, defaults.avatar);
        return {
            accent: accents[accent] ? accent : defaults.accent,
            timezone: allowedTimezones.has(timezone) ? timezone : defaults.timezone,
            timeFormat: allowedTimeFormats.has(timeFormat) ? timeFormat : defaults.timeFormat,
            avatar: allowedAvatars.has(avatar) ? avatar : defaults.avatar,
        };
    };

    const applyDarkTheme = () => {
        root.dataset.appTheme = 'dark';
        delete root.dataset.themePreference;
        root.style.colorScheme = 'dark';
        remove('studentAssistant.theme');
    };

    const applyAccent = (accentName) => {
        const accent = accents[accentName] || accents.purple;
        root.dataset.accent = accents[accentName] ? accentName : defaults.accent;
        root.style.setProperty('--accent', accent.base);
        root.style.setProperty('--accent-hover', accent.hover);
        root.style.setProperty('--accent-soft', accent.soft);
        root.style.setProperty('--accent-border', accent.border);
        root.style.setProperty('--accent-glow', accent.glow);
    };

    const formatTimeValue = (hours, minutes, seconds = '') => {
        const settings = getSettings();
        if (settings.timeFormat !== '12') {
            return `${String(hours).padStart(2, '0')}:${minutes}${seconds ? `:${seconds}` : ''}`;
        }
        const numericHours = Number(hours);
        const suffix = numericHours >= 12 ? 'PM' : 'AM';
        const displayHours = numericHours % 12 || 12;
        return `${displayHours}:${minutes}${seconds ? `:${seconds}` : ''} ${suffix}`;
    };

    const formatTextTimes = (scope = document.body) => {
        if (!scope) {
            return;
        }
        const timePattern = /\b([01]\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\b/g;
        const timeTestPattern = /\b(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\b/;
        const walker = document.createTreeWalker(scope, NodeFilter.SHOW_TEXT, {
            acceptNode(node) {
                const parent = node.parentElement;
                if (!parent || parent.closest('script, style, input, textarea, select, option')) {
                    return NodeFilter.FILTER_REJECT;
                }
                return timeTestPattern.test(node.data) || originalText.has(node)
                    ? NodeFilter.FILTER_ACCEPT
                    : NodeFilter.FILTER_REJECT;
            },
        });
        const nodes = [];
        while (walker.nextNode()) {
            nodes.push(walker.currentNode);
        }
        const useTwelveHours = getSettings().timeFormat === '12';
        nodes.forEach((node) => {
            if (!originalText.has(node)) {
                originalText.set(node, node.data);
            }
            const source = originalText.get(node);
            node.data = useTwelveHours
                ? source.replace(timePattern, (_, hours, minutes, seconds) => formatTimeValue(hours, minutes, seconds))
                : source;
        });
    };

    const applyAvatar = (avatar) => {
        document.querySelectorAll('[data-user-avatar]').forEach((element) => {
            element.dataset.avatar = avatar;
        });
        document.querySelectorAll('[data-avatar-option]').forEach((button) => {
            const selected = button.dataset.avatarOption === avatar;
            button.classList.toggle('is-selected', selected);
            button.setAttribute('aria-pressed', String(selected));
        });
    };

    const applySettings = () => {
        const settings = getSettings();
        applyDarkTheme();
        applyAccent(settings.accent);
        if (document.body) {
            document.body.style.setProperty('--profile-purple', 'var(--accent)');
            document.body.style.setProperty('--dash-purple', 'var(--accent)');
            document.body.style.setProperty('--tasks-purple', 'var(--accent)');
            document.body.style.setProperty('--subjects-purple', 'var(--accent)');
            document.body.style.setProperty('--schedule-purple', 'var(--accent)');
            document.body.style.setProperty('--calendar-purple', 'var(--accent)');
            document.body.style.setProperty('--notes-purple', 'var(--accent)');
        }
        applyAvatar(settings.avatar);
        formatTextTimes();
        document.dispatchEvent(new CustomEvent('studentAssistantPreferencesChanged', { detail: settings }));
    };

    const showPreferenceToast = (title, description) => {
        window.showToast?.({ type: 'success', title, description, duration: 3600 });
    };

    const saveSetting = (name, value) => {
        const key = keys[name];
        if (!key || !write(key, value)) {
            window.showToast?.({
                type: 'error',
                title: 'Не удалось сохранить настройки',
                description: 'Локальное хранилище браузера недоступно.',
                duration: 5200,
            });
            return false;
        }
        applySettings();
        return true;
    };

    const resetSettings = ({ includeAvatar = false } = {}) => {
        remove(keys.accent);
        remove(keys.timezone);
        remove(keys.timeFormat);
        if (includeAvatar) {
            remove(keys.avatar);
        }
        applySettings();
        syncControls();
    };

    const syncControls = () => {
        const settings = getSettings();
        const timezoneSelect = document.getElementById('profileTimezoneSelect');
        const timeFormatSelect = document.getElementById('profileTimeFormatSelect');
        if (timezoneSelect) timezoneSelect.value = settings.timezone;
        if (timeFormatSelect) timeFormatSelect.value = settings.timeFormat;
        document.querySelectorAll('[data-accent-option]').forEach((button) => {
            const selected = button.dataset.accentOption === settings.accent;
            button.classList.toggle('is-selected', selected);
            button.setAttribute('aria-pressed', String(selected));
        });
        applyAvatar(settings.avatar);
    };

    const initializeProfileMenu = () => {
        const menu = document.getElementById('profileMenu');
        const toggle = document.getElementById('profileMenuToggle');
        const panel = document.getElementById('profileMenuPanel');
        if (!menu || !toggle || !panel) {
            return;
        }
        let closeTimer = null;
        const close = ({ restoreFocus = false } = {}) => {
            panel.classList.remove('is-visible');
            toggle.setAttribute('aria-expanded', 'false');
            window.clearTimeout(closeTimer);
            closeTimer = window.setTimeout(() => {
                panel.hidden = true;
            }, 180);
            if (restoreFocus) toggle.focus();
        };
        const open = () => {
            window.clearTimeout(closeTimer);
            panel.hidden = false;
            requestAnimationFrame(() => {
                panel.classList.add('is-visible');
                toggle.setAttribute('aria-expanded', 'true');
                panel.querySelector('a, button')?.focus();
            });
        };
        toggle.addEventListener('click', () => {
            if (panel.hidden) open();
            else close();
        });
        document.addEventListener('click', (event) => {
            if (!panel.hidden && !menu.contains(event.target)) {
                close();
            }
        });
        document.addEventListener('keydown', (event) => {
            if (event.key === 'Escape' && !panel.hidden) {
                event.preventDefault();
                close({ restoreFocus: true });
            }
        });
        panel.querySelectorAll('a, button').forEach((control) => {
            control.addEventListener('click', () => close());
        });
    };

    const initializeControls = () => {
        syncControls();
        initializeProfileMenu();

        document.querySelectorAll('[data-accent-option]').forEach((button) => {
            button.addEventListener('click', () => {
                if (saveSetting('accent', button.dataset.accentOption)) {
                    syncControls();
                    showPreferenceToast('Цвет акцента изменён', 'Новый акцент применён к интерфейсу.');
                }
            });
        });

        document.querySelectorAll('[data-avatar-option]').forEach((button) => {
            button.addEventListener('click', () => {
                if (saveSetting('avatar', button.dataset.avatarOption)) {
                    syncControls();
                    showPreferenceToast('Аватар обновлён', 'Выбранный аватар сохранён в браузере.');
                }
            });
        });
        document.getElementById('profileAvatarChange')?.addEventListener('click', () => {
            document.querySelector('[data-avatar-option]')?.focus();
        });

        document.getElementById('profileTimeForm')?.addEventListener('submit', (event) => {
            event.preventDefault();
            const timezone = document.getElementById('profileTimezoneSelect')?.value || defaults.timezone;
            const timeFormat = document.getElementById('profileTimeFormatSelect')?.value || defaults.timeFormat;
            const timezoneSaved = write(keys.timezone, timezone);
            const timeFormatSaved = write(keys.timeFormat, timeFormat);
            if (!timezoneSaved || !timeFormatSaved) {
                window.showToast?.({ type: 'error', title: 'Не удалось сохранить настройки', duration: 5000 });
                return;
            }
            applySettings();
            showPreferenceToast('Настройки времени сохранены', 'Формат времени обновлён.');
        });

        const requestReset = (includeAvatar, trigger) => {
            const title = includeAvatar ? 'Удалить локальные настройки?' : 'Сбросить настройки?';
            const description = includeAvatar
                ? 'Локальный аватар и все параметры интерфейса будут удалены из этого браузера.'
                : 'Цвет акцента и параметры времени вернутся к значениям по умолчанию.';
            window.requestConfirmation?.({
                title,
                description,
                confirmLabel: includeAvatar ? 'Удалить' : 'Сбросить',
                trigger,
                onConfirm: () => {
                    resetSettings({ includeAvatar });
                    showPreferenceToast(includeAvatar ? 'Локальные настройки удалены' : 'Настройки сброшены');
                },
            });
        };

        document.getElementById('profileResetSettings')?.addEventListener('click', (event) => requestReset(false, event.currentTarget));
        document.getElementById('profileDeleteLocalSettings')?.addEventListener('click', (event) => requestReset(true, event.currentTarget));

        const systemTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        document.querySelectorAll('[data-system-timezone]').forEach((option) => {
            option.textContent = `Системный (${systemTimezone || 'UTC'})`;
        });
    };

    applyDarkTheme();
    applyAccent(read(keys.accent, defaults.accent));

    window.StudentAssistantPreferences = {
        getSettings,
        applySettings,
        formatTimeValue,
        formatTextTimes,
        saveSetting,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => {
            applySettings();
            initializeControls();
        });
    } else {
        applySettings();
        initializeControls();
    }

})();
