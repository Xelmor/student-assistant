(() => {
    const pendingToastKey = 'student-assistant-pending-toast';
    const dialog = document.getElementById('confirmDialog');
    const dialogTitle = document.getElementById('confirmDialogTitle');
    const dialogDescription = document.getElementById('confirmDialogDescription');
    const dialogCancel = document.getElementById('confirmDialogCancel');
    const dialogConfirm = document.getElementById('confirmDialogConfirm');
    const dialogClose = document.getElementById('confirmDialogClose');
    const politeRegion = document.getElementById('toastRegionPolite');
    const assertiveRegion = document.getElementById('toastRegionAssertive');
    let activeForm = null;
    let activeConfirmation = null;
    let lastFocusedElement = null;
    let closeTimer = null;

    const toastIcons = {
        success: '✓',
        error: '!',
        warning: '△',
        info: 'i',
    };

    const actionDefinitions = [
        { pattern: /^\/tasks\/add\/?$/, title: 'Задача добавлена', description: 'Новая задача появилась в списке.' },
        { pattern: /^\/tasks\/edit\/\d+\/?$/, title: 'Задача изменена', description: 'Изменения сохранены.' },
        { pattern: /^\/subjects\/add\/?$/, title: 'Предмет добавлен', description: 'Новая дисциплина появилась в каталоге.' },
        { pattern: /^\/subjects\/edit\/\d+\/?$/, title: 'Предмет изменён', description: 'Данные предмета обновлены.' },
        { pattern: /^\/notes\/add\/?$/, title: 'Заметка создана', description: 'Новая запись появилась в коллекции.' },
        { pattern: /^\/notes\/edit\/\d+\/?$/, title: 'Заметка изменена', description: 'Изменения заметки сохранены.' },
        { pattern: /^\/schedule\/add\/?$/, title: 'Занятие добавлено', description: 'Занятие появилось в расписании.' },
        { pattern: /^\/schedule\/edit\/\d+\/?$/, title: 'Занятие изменено', description: 'Расписание обновлено.' },
        { pattern: /^\/calendar\/session\/add\/?$/, title: 'Событие добавлено', description: 'Событие появилось в календаре.' },
        { pattern: /^\/calendar\/session\/edit\/\d+\/?$/, title: 'Событие изменено', description: 'Изменения события сохранены.' },
        { pattern: /^\/calendar\/override\/add\/?$/, title: 'Событие добавлено', description: 'Особый период добавлен в календарь.' },
        { pattern: /^\/profile\/?$/, title: 'Профиль сохранён', description: 'Данные аккаунта сохранены.' },
        { pattern: /^\/data\/import\/?$/, title: 'Данные импортированы', description: 'Учебные данные успешно загружены.' },
        { pattern: /^\/login\/?$/, title: 'Вы успешно вошли', description: 'Добро пожаловать в Student Assistant.' },
        { pattern: /^\/register\/?$/, title: 'Аккаунт создан', description: 'Учебное пространство готово к работе.' },
        { pattern: /^\/forgot-password\/?$/, title: 'Запрос отправлен', description: 'Проверьте почту для продолжения.' },
        { pattern: /^\/reset-password\/?$/, title: 'Пароль обновлён', description: 'Теперь можно войти с новым паролем.' },
        { pattern: /^\/logout\/?$/, title: 'Вы вышли из аккаунта', description: 'Сессия безопасно завершена.' },
    ];

    const deleteDefinitions = [
        {
            pattern: /^\/tasks\/delete\/\d+\/?$/,
            title: 'Удалить задачу?',
            description: 'Это действие нельзя отменить. Задача будет удалена навсегда.',
            successTitle: 'Задача удалена',
            successDescription: 'Задача удалена из списка.',
        },
        {
            pattern: /^\/subjects\/delete\/\d+\/?$/,
            title: 'Удалить предмет?',
            description: 'Это действие нельзя отменить. Предмет будет удалён из каталога.',
            successTitle: 'Предмет удалён',
            successDescription: 'Предмет удалён из каталога.',
        },
        {
            pattern: /^\/notes\/delete\/\d+\/?$/,
            title: 'Удалить заметку?',
            description: 'Это действие нельзя отменить. Заметка будет удалена навсегда.',
            successTitle: 'Заметка удалена',
            successDescription: 'Заметка удалена из коллекции.',
        },
        {
            pattern: /^\/schedule\/delete\/\d+\/?$/,
            title: 'Удалить занятие?',
            description: 'Занятие будет удалено из расписания.',
            successTitle: 'Занятие удалено',
            successDescription: 'Расписание обновлено.',
        },
        {
            pattern: /^\/calendar\/session\/delete\/\d+\/?$/,
            title: 'Удалить событие?',
            description: 'Событие будет удалено из календаря.',
            successTitle: 'Событие удалено',
            successDescription: 'Событие удалено из календаря.',
        },
    ];

    const getPathname = (form) => {
        try {
            return new URL(form.action, window.location.href).pathname;
        } catch (_) {
            return form.getAttribute('action') || '';
        }
    };

    const findDefinition = (definitions, pathname) => definitions.find((item) => item.pattern.test(pathname));

    const showFormLoading = (form, submitter) => {
        window.requestAnimationFrame(() => {
            form.classList.add('is-submitting');
            form.setAttribute('aria-busy', 'true');
            const loadingButton = submitter instanceof HTMLElement
                ? submitter
                : form.querySelector('button[type="submit"], input[type="submit"]');
            if (loadingButton instanceof HTMLElement) {
                loadingButton.classList.add('form-loading-button');
                loadingButton.setAttribute('aria-disabled', 'true');
            }
        });
    };

    const savePendingToast = (toast) => {
        try {
            window.sessionStorage.setItem(pendingToastKey, JSON.stringify({ ...toast, savedAt: Date.now() }));
        } catch (_) {
        }
    };

    const removeToast = (toast) => {
        if (!toast || toast.classList.contains('is-leaving')) {
            return;
        }
        toast.classList.add('is-leaving');
        window.setTimeout(() => toast.remove(), 220);
    };

    window.showToast = ({
        type = 'info',
        title = 'Готово',
        description = '',
        duration = 4200,
    } = {}) => {
        const region = type === 'error' ? assertiveRegion : politeRegion;
        if (!region) {
            return;
        }

        const toast = document.createElement('article');
        toast.className = `app-toast app-toast--${type}`;
        toast.style.setProperty('--toast-duration', `${duration}ms`);
        toast.setAttribute('role', type === 'error' ? 'alert' : 'status');

        const icon = document.createElement('span');
        icon.className = 'app-toast__icon';
        icon.setAttribute('aria-hidden', 'true');
        icon.textContent = toastIcons[type] || toastIcons.info;

        const copy = document.createElement('div');
        copy.className = 'app-toast__copy';
        const heading = document.createElement('strong');
        heading.textContent = title;
        copy.appendChild(heading);
        if (description) {
            const text = document.createElement('p');
            text.textContent = description;
            copy.appendChild(text);
        }

        const close = document.createElement('button');
        close.type = 'button';
        close.className = 'app-toast__close';
        close.setAttribute('aria-label', 'Закрыть уведомление');
        close.textContent = '×';
        close.addEventListener('click', () => removeToast(toast));

        const progress = document.createElement('span');
        progress.className = 'app-toast__progress';
        progress.setAttribute('aria-hidden', 'true');

        toast.append(icon, copy, close, progress);
        region.prepend(toast);
        requestAnimationFrame(() => toast.classList.add('is-visible'));
        window.setTimeout(() => removeToast(toast), duration);
    };

    const getVisibleError = () => {
        const candidates = document.querySelectorAll(
            '.alert-danger, [role="alert"], .tasks-alert, .schedule-alert, .notes-alert, .calendar-alert',
        );
        return [...candidates].find((item) => !item.hidden && item.textContent.trim());
    };

    const showPendingToast = () => {
        let pending = null;
        try {
            pending = JSON.parse(window.sessionStorage.getItem(pendingToastKey) || 'null');
            window.sessionStorage.removeItem(pendingToastKey);
        } catch (_) {
            pending = null;
        }

        const visibleError = getVisibleError();
        if (visibleError) {
            window.showToast({
                type: 'error',
                title: 'Не удалось выполнить действие',
                description: visibleError.textContent.trim() || 'Проверьте данные формы.',
                duration: 5200,
            });
            return;
        }

        if (!pending || Date.now() - Number(pending.savedAt || 0) > 60000) {
            return;
        }
        window.showToast(pending);
    };

    const closeDialog = ({ restoreFocus = true } = {}) => {
        if (!dialog || dialog.hidden) {
            return;
        }
        dialog.classList.remove('is-visible');
        document.body.classList.remove('feedback-modal-open');
        window.clearTimeout(closeTimer);
        closeTimer = window.setTimeout(() => {
            dialog.hidden = true;
            activeForm = null;
            activeConfirmation = null;
        }, 180);
        if (restoreFocus && lastFocusedElement instanceof HTMLElement) {
            lastFocusedElement.focus();
        }
    };

    const openDialog = (form, submitter, definition) => {
        if (!dialog || !dialogTitle || !dialogDescription || !dialogConfirm) {
            return;
        }
        activeForm = form;
        activeConfirmation = null;
        lastFocusedElement = submitter || document.activeElement;
        dialogTitle.textContent = form.dataset.confirmTitle || definition.title;
        dialogDescription.textContent = form.dataset.confirmDescription || definition.description;
        dialogConfirm.textContent = form.dataset.confirmLabel || 'Удалить';
        dialogConfirm.disabled = false;
        window.clearTimeout(closeTimer);
        dialog.hidden = false;
        document.body.classList.add('feedback-modal-open');
        requestAnimationFrame(() => {
            dialog.classList.add('is-visible');
            dialogCancel?.focus();
        });
    };

    window.requestConfirmation = ({
        title = 'Подтвердить действие?',
        description = 'Это действие нельзя отменить.',
        confirmLabel = 'Подтвердить',
        onConfirm,
        trigger,
    } = {}) => {
        if (!dialog || !dialogTitle || !dialogDescription || !dialogConfirm) {
            return false;
        }
        activeForm = null;
        activeConfirmation = { onConfirm };
        lastFocusedElement = trigger || document.activeElement;
        dialogTitle.textContent = title;
        dialogDescription.textContent = description;
        dialogConfirm.textContent = confirmLabel;
        dialogConfirm.disabled = false;
        window.clearTimeout(closeTimer);
        dialog.hidden = false;
        document.body.classList.add('feedback-modal-open');
        requestAnimationFrame(() => {
            dialog.classList.add('is-visible');
            dialogCancel?.focus();
        });
        return true;
    };

    const submitDeletion = async () => {
        if (!dialogConfirm) {
            return;
        }
        if (activeConfirmation) {
            const confirmation = activeConfirmation;
            dialogConfirm.disabled = true;
            try {
                await confirmation.onConfirm?.();
                closeDialog();
            } catch (_) {
                dialogConfirm.disabled = false;
                closeDialog();
                window.showToast({
                    type: 'error',
                    title: 'Не удалось выполнить действие',
                    description: 'Попробуйте ещё раз.',
                    duration: 5200,
                });
            }
            return;
        }
        if (!activeForm) {
            return;
        }
        const form = activeForm;
        const definition = findDefinition(deleteDefinitions, getPathname(form));
        if (!definition) {
            return;
        }

        dialogConfirm.disabled = true;
        const previousLabel = dialogConfirm.textContent;
        dialogConfirm.textContent = 'Удаляю…';

        try {
            const response = await fetch(form.action, {
                method: (form.method || 'post').toUpperCase(),
                body: new FormData(form),
                credentials: 'same-origin',
                headers: { 'X-Requested-With': 'XMLHttpRequest' },
                redirect: 'follow',
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            if (new URL(response.url, window.location.href).pathname === '/login') {
                throw new Error('Authentication required');
            }
            savePendingToast({
                type: 'success',
                title: definition.successTitle,
                description: definition.successDescription,
                duration: 4200,
            });
            closeDialog({ restoreFocus: false });
            window.location.assign(response.url || form.action);
        } catch (_) {
            dialogConfirm.disabled = false;
            dialogConfirm.textContent = previousLabel;
            closeDialog();
            window.showToast({
                type: 'error',
                title: 'Не удалось удалить',
                description: 'Не удалось выполнить действие. Попробуйте ещё раз.',
                duration: 5200,
            });
        }
    };

    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }

        const pathname = getPathname(form);
        const deleteDefinition = findDefinition(deleteDefinitions, pathname);
        if (deleteDefinition) {
            event.preventDefault();
            openDialog(form, event.submitter, deleteDefinition);
            return;
        }

        if ((form.method || 'get').toLowerCase() !== 'post' || form.dataset.skipToast === 'true') {
            return;
        }

        const action = findDefinition(actionDefinitions, pathname);
        if (action) {
            if (/^\/tasks\/toggle\/\d+\/?$/.test(pathname)) {
                return;
            }
            savePendingToast({
                type: 'success',
                title: action.title,
                description: action.description,
                duration: 4200,
            });
            showFormLoading(form, event.submitter);
        }
    }, true);

    document.addEventListener('submit', (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) {
            return;
        }
        const pathname = getPathname(form);
        if (!/^\/tasks\/toggle\/\d+\/?$/.test(pathname)) {
            return;
        }
        const completed = form.closest('[data-task-item]')?.classList.contains('is-completed');
        savePendingToast({
            type: 'success',
            title: completed ? 'Задача возвращена в работу' : 'Задача выполнена',
            description: completed ? 'Задача снова появилась среди активных.' : 'Прогресс задачи обновлён.',
            duration: 3800,
        });
        showFormLoading(form, event.submitter);
    }, true);

    dialogCancel?.addEventListener('click', () => closeDialog());
    dialogClose?.addEventListener('click', () => closeDialog());
    dialogConfirm?.addEventListener('click', submitDeletion);
    dialog?.addEventListener('click', (event) => {
        if (event.target === dialog) {
            closeDialog();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && dialog && !dialog.hidden) {
            event.preventDefault();
            closeDialog();
            return;
        }
        if (event.key === 'Tab' && dialog && !dialog.hidden) {
            const focusable = [...dialog.querySelectorAll('button:not([disabled]), [href], input, select, textarea')]
                .filter((item) => item instanceof HTMLElement && !item.hidden);
            if (!focusable.length) {
                return;
            }
            const first = focusable[0];
            const last = focusable[focusable.length - 1];
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first.focus();
            }
        }
    });

    showPendingToast();
})();
