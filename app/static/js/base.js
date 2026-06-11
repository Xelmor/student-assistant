document.querySelectorAll('[data-password-toggle]').forEach((button) => {
    button.addEventListener('click', () => {
        const targetId = button.getAttribute('data-password-target');
        const input = document.getElementById(targetId);
        if (!input) {
            return;
        }

        const showPassword = input.type === 'password';
        input.type = showPassword ? 'text' : 'password';
        button.textContent = showPassword ? 'Скрыть' : 'Показать';
        button.setAttribute('aria-label', showPassword ? 'Скрыть пароль' : 'Показать пароль');
        button.setAttribute('aria-pressed', showPassword ? 'true' : 'false');
    });
});

window.animateMotionItems = (items) => {
    if (window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }

    [...items].filter((item) => item instanceof HTMLElement && !item.hidden).forEach((item) => {
        item.classList.remove('motion-item-enter');
        void item.offsetWidth;
        item.classList.add('motion-item-enter');
        window.setTimeout(() => item.classList.remove('motion-item-enter'), 220);
    });
};

(() => {
    const focusFormControl = (selector) => {
        if (!selector) {
            return;
        }
        const control = document.querySelector(selector);
        if (!(control instanceof HTMLElement)) {
            return;
        }
        control.focus({ preventScroll: true });
        if (control instanceof HTMLInputElement && ['text', 'search', 'url', 'email'].includes(control.type)) {
            control.select();
        }
    };

    document.addEventListener('click', (event) => {
        const action = event.target.closest('[data-empty-focus]');
        if (!action) {
            return;
        }
        window.setTimeout(() => focusFormControl(action.dataset.emptyFocus), 420);
    });

    const focusableEmptyStateSections = new Set([
        '#task-create',
        '#subject-create',
        '#note-create',
        '#schedule-form-panel',
        '#calendar-event-form',
    ]);
    if (focusableEmptyStateSections.has(window.location.hash)) {
        const section = document.querySelector(window.location.hash);
        const control = section?.querySelector(
            'input:not([type="hidden"]):not([disabled]), select:not([disabled]), textarea:not([disabled])',
        );
        window.setTimeout(() => {
            section?.scrollIntoView({ behavior: 'smooth', block: 'start' });
            if (control instanceof HTMLElement) {
                control.focus({ preventScroll: true });
            }
        }, 350);
    }
})();

(() => {
    const collapseElement = document.getElementById('navbarsExample07');
    const toggler = document.querySelector('[data-bs-target="#navbarsExample07"]');
    const topbar = collapseElement?.closest('.topbar');

    if (!collapseElement || !toggler || !topbar || !window.bootstrap?.Collapse) {
        return;
    }

    const collapse = window.bootstrap.Collapse.getOrCreateInstance(collapseElement, { toggle: false });
    const closeMenu = () => {
        if (collapseElement.classList.contains('show')) {
            collapse.hide();
        }
    };

    collapseElement.addEventListener('shown.bs.collapse', () => {
        toggler.setAttribute('aria-expanded', 'true');
        toggler.setAttribute('aria-label', 'Закрыть меню');
    });

    collapseElement.addEventListener('hidden.bs.collapse', () => {
        toggler.setAttribute('aria-expanded', 'false');
        toggler.setAttribute('aria-label', 'Открыть меню');
    });

    collapseElement.querySelectorAll('a').forEach((link) => {
        link.addEventListener('click', closeMenu);
    });

    document.addEventListener('click', (event) => {
        if (collapseElement.classList.contains('show') && !topbar.contains(event.target)) {
            closeMenu();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeMenu();
            toggler.focus();
        }
    });
})();

(() => {
    const storageKey = 'student-assistant-scroll-restore';
    const maxStateAgeMs = 30 * 1000;
    let restoreState = null;

    try {
        const rawState = window.sessionStorage.getItem(storageKey);
        if (rawState) {
            const parsedState = JSON.parse(rawState);
            const isCurrentPage = parsedState.pathname === window.location.pathname;
            const isFresh = Date.now() - Number(parsedState.savedAt || 0) <= maxStateAgeMs;
            const hasValidPosition = Number.isFinite(parsedState.scrollY) && parsedState.scrollY >= 0;

            if (isCurrentPage && isFresh && hasValidPosition) {
                restoreState = parsedState;
            }
        }
        window.sessionStorage.removeItem(storageKey);
    } catch (_) {
        restoreState = null;
    }

    const restoreScrollPosition = () => {
        if (!restoreState) {
            return;
        }
        window.scrollTo({ top: restoreState.scrollY, left: 0, behavior: 'auto' });
    };

    if (restoreState) {
        requestAnimationFrame(() => {
            restoreScrollPosition();
            requestAnimationFrame(restoreScrollPosition);
        });
        window.addEventListener('load', restoreScrollPosition, { once: true });
    }

    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        const method = (form.getAttribute('method') || 'get').toLowerCase();
        if (method !== 'post' || form.dataset.skipScrollRestore === 'true' || form.target === '_blank') {
            return;
        }

        try {
            window.sessionStorage.setItem(
                storageKey,
                JSON.stringify({
                    pathname: window.location.pathname,
                    scrollY: window.scrollY,
                    savedAt: Date.now(),
                }),
            );
        } catch (_) {
        }
    });
})();

(() => {
    const quickActions = document.getElementById('mobileQuickActions');
    const quickSheet = document.getElementById('mobileQuickActionsSheet');
    const quickToggle = document.getElementById('mobileQuickActionsToggle');

    if (!quickActions || !quickSheet || !quickToggle) {
        return;
    }

    const closeQuickActions = () => {
        quickActions.classList.remove('is-open');
        quickToggle.setAttribute('aria-expanded', 'false');
        quickSheet.hidden = true;
    };

    const openQuickActions = () => {
        quickSheet.hidden = false;
        requestAnimationFrame(() => {
            quickActions.classList.add('is-open');
            quickToggle.setAttribute('aria-expanded', 'true');
        });
    };

    quickToggle.addEventListener('click', () => {
        if (quickActions.classList.contains('is-open')) {
            closeQuickActions();
            return;
        }
        openQuickActions();
    });

    quickSheet.querySelectorAll('a').forEach((link) => {
        link.addEventListener('click', closeQuickActions);
    });

    document.addEventListener('click', (event) => {
        if (!quickActions.classList.contains('is-open')) {
            return;
        }
        if (!quickActions.contains(event.target)) {
            closeQuickActions();
        }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape') {
            closeQuickActions();
        }
    });
})();
