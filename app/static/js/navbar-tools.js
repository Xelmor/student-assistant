(() => {
    const dataNode = document.getElementById('navbarToolsData');
    const searchToggle = document.getElementById('globalSearchToggle');
    const searchOverlay = document.getElementById('globalSearchOverlay');
    const searchClose = document.getElementById('globalSearchClose');
    const searchInput = document.getElementById('globalSearchInput');
    const searchQuickActions = document.getElementById('globalSearchQuickActions');
    const searchResults = document.getElementById('globalSearchResults');
    const searchEmpty = document.getElementById('globalSearchEmpty');
    const searchClear = document.getElementById('globalSearchClear');
    const searchShortcut = document.getElementById('globalSearchShortcut');
    const notificationToggle = document.getElementById('notificationToggle');
    const notificationPanel = document.getElementById('notificationPanel');
    const notificationClose = document.getElementById('notificationClose');
    const notificationContent = document.getElementById('notificationContent');
    const notificationEmpty = document.getElementById('notificationEmpty');
    const notificationBadge = document.getElementById('notificationBadge');
    const notificationReadAll = document.getElementById('notificationReadAll');
    const notificationReadHint = document.getElementById('notificationReadHint');

    let payload = {
        user_id: null,
        search: [],
        notifications: { today: [], soon: [], overdue: [] },
    };
    try {
        payload = JSON.parse(dataNode?.textContent || '{}');
    } catch (_) {
    }

    const normalize = (value) => String(value || '')
        .toLocaleLowerCase('ru')
        .replace(/ё/g, 'е')
        .trim();

    const setButtonActive = (button, active) => {
        button?.classList.toggle('is-active', active);
        button?.setAttribute('aria-expanded', String(active));
    };

    let lastFocusedElement = null;
    let activeResultIndex = -1;
    let searchCloseTimer = null;
    let notificationCloseTimer = null;

    const closeSearch = ({ restoreFocus = true } = {}) => {
        if (!searchOverlay || searchOverlay.hidden) {
            return;
        }
        searchOverlay.classList.remove('is-visible');
        setButtonActive(searchToggle, false);
        document.body.classList.remove('navbar-modal-open');
        window.clearTimeout(searchCloseTimer);
        searchCloseTimer = window.setTimeout(() => {
            searchOverlay.hidden = true;
        }, 160);
        if (restoreFocus && lastFocusedElement instanceof HTMLElement) {
            lastFocusedElement.focus();
        }
    };

    const closeNotifications = ({ restoreFocus = true } = {}) => {
        if (!notificationPanel || notificationPanel.hidden) {
            return;
        }
        notificationPanel.classList.remove('is-visible');
        setButtonActive(notificationToggle, false);
        window.clearTimeout(notificationCloseTimer);
        notificationCloseTimer = window.setTimeout(() => {
            notificationPanel.hidden = true;
        }, 160);
        if (restoreFocus && notificationToggle && restoreFocus) {
            notificationToggle.focus();
        }
    };

    const updateActiveResult = (nextIndex) => {
        const results = [...(searchResults?.querySelectorAll('[data-search-result]') || [])];
        if (!results.length) {
            activeResultIndex = -1;
            return;
        }
        activeResultIndex = (nextIndex + results.length) % results.length;
        results.forEach((result, index) => {
            const active = index === activeResultIndex;
            result.classList.toggle('is-active', active);
            result.setAttribute('aria-selected', String(active));
        });
        results[activeResultIndex].scrollIntoView({ block: 'nearest' });
    };

    const resultIconText = {
        task: '✓',
        subject: '◇',
        class: '◷',
        event: '□',
        note: '✎',
    };

    const renderSearchResults = () => {
        if (!searchResults || !searchQuickActions || !searchEmpty) {
            return;
        }
        const query = normalize(searchInput?.value);
        const emptyWasHidden = searchEmpty.hidden;
        searchResults.replaceChildren();
        activeResultIndex = -1;

        if (!query) {
            searchQuickActions.hidden = false;
            searchResults.hidden = true;
            searchEmpty.hidden = true;
            return;
        }

        const words = query.split(/\s+/).filter(Boolean);
        const matches = (payload.search || []).filter((item) => {
            const haystack = normalize(`${item.title} ${item.description} ${item.keywords} ${item.type_label}`);
            return words.every((word) => haystack.includes(word));
        }).slice(0, 30);

        searchQuickActions.hidden = true;
        searchResults.hidden = matches.length === 0;
        searchEmpty.hidden = matches.length !== 0;

        matches.forEach((item, index) => {
            const link = document.createElement('a');
            link.className = 'global-search-result';
            link.href = item.href;
            link.dataset.searchResult = '';
            link.setAttribute('role', 'option');
            link.setAttribute('aria-selected', 'false');

            const icon = document.createElement('span');
            icon.className = `navbar-result-icon is-${item.type}`;
            icon.textContent = resultIconText[item.type] || '•';

            const text = document.createElement('span');
            text.className = 'global-search-result-text';
            const title = document.createElement('strong');
            title.textContent = item.title;
            const description = document.createElement('small');
            description.textContent = item.description;
            text.append(title, description);

            const badge = document.createElement('span');
            badge.className = 'global-search-result-badge';
            badge.textContent = item.type_label;

            link.append(icon, text, badge);
            link.addEventListener('mouseenter', () => updateActiveResult(index));
            searchResults.appendChild(link);
        });

        if (matches.length) {
            updateActiveResult(0);
            window.animateMotionItems?.(searchResults.children);
        } else if (emptyWasHidden && !searchEmpty.hidden) {
            window.animateMotionItems?.([searchEmpty]);
        }
        window.StudentAssistantPreferences?.formatTextTimes?.(searchResults);
    };

    const openSearch = () => {
        if (!searchOverlay || !searchInput) {
            return;
        }
        closeNotifications({ restoreFocus: false });
        lastFocusedElement = document.activeElement;
        window.clearTimeout(searchCloseTimer);
        searchOverlay.hidden = false;
        document.body.classList.add('navbar-modal-open');
        requestAnimationFrame(() => {
            searchOverlay.classList.add('is-visible');
            setButtonActive(searchToggle, true);
            searchInput.focus();
            searchInput.select();
        });
        renderSearchResults();
    };

    searchToggle?.addEventListener('click', () => {
        if (searchOverlay?.hidden) {
            openSearch();
        } else {
            closeSearch();
        }
    });
    searchClose?.addEventListener('click', () => closeSearch());
    searchInput?.addEventListener('input', renderSearchResults);
    searchClear?.addEventListener('click', () => {
        if (searchInput) {
            searchInput.value = '';
            searchInput.focus();
        }
        renderSearchResults();
    });
    searchOverlay?.addEventListener('click', (event) => {
        if (event.target === searchOverlay) {
            closeSearch();
        }
    });
    searchOverlay?.querySelectorAll('[data-search-close]').forEach((link) => {
        link.addEventListener('click', () => closeSearch({ restoreFocus: false }));
    });

    const notificationLabels = {
        today: 'Сегодня',
        soon: 'Скоро',
        overdue: 'Просрочено',
    };
    const notificationIcons = {
        task: '✓',
        class: '◷',
        exam: '□',
        change: '↻',
        overdue: '!',
    };
    const notificationKindLabels = {
        task: 'Задача',
        class: 'Пара',
        exam: 'Событие',
        change: 'Изменение',
        overdue: 'Просрочено',
    };
    const notificationGroups = payload.notifications || { today: [], soon: [], overdue: [] };
    const allNotifications = ['today', 'soon', 'overdue']
        .flatMap((group) => notificationGroups[group] || []);
    const readStorageKey = `student-assistant-notifications-read:${payload.user_id || 'current'}`;
    let readNotificationIds = new Set();
    try {
        readNotificationIds = new Set(JSON.parse(window.localStorage.getItem(readStorageKey) || '[]'));
    } catch (_) {
    }

    const updateNotificationBadge = () => {
        if (!notificationBadge) {
            return;
        }
        const unreadCount = allNotifications.filter((item) => !readNotificationIds.has(item.id)).length;
        notificationBadge.textContent = unreadCount > 99 ? '99+' : String(unreadCount);
        notificationBadge.hidden = unreadCount === 0;
        notificationReadAll?.toggleAttribute('disabled', unreadCount === 0);
        if (notificationReadHint) {
            notificationReadHint.hidden = allNotifications.length === 0 || unreadCount !== 0;
        }
    };

    const renderNotifications = () => {
        if (!notificationContent || !notificationEmpty) {
            return;
        }
        notificationContent.replaceChildren();
        notificationEmpty.hidden = allNotifications.length !== 0;
        notificationContent.hidden = allNotifications.length === 0;

        ['today', 'soon', 'overdue'].forEach((groupName) => {
            const items = notificationGroups[groupName] || [];
            if (!items.length) {
                return;
            }
            const section = document.createElement('section');
            section.className = 'notification-group';
            const heading = document.createElement('h3');
            heading.textContent = notificationLabels[groupName];
            section.appendChild(heading);

            items.forEach((item) => {
                const link = document.createElement('a');
                link.className = `notification-item is-${item.kind}`;
                link.href = item.href;
                link.classList.toggle('is-read', readNotificationIds.has(item.id));

                const icon = document.createElement('span');
                icon.className = 'notification-item-icon';
                icon.textContent = notificationIcons[item.kind] || '•';

                const text = document.createElement('span');
                text.className = 'notification-item-text';
                const kind = document.createElement('span');
                kind.className = 'notification-item-kind';
                kind.textContent = notificationKindLabels[item.kind] || 'Событие';
                const title = document.createElement('strong');
                title.textContent = item.title;
                const description = document.createElement('small');
                description.textContent = item.description;
                const time = document.createElement('time');
                time.textContent = item.time;
                text.append(kind, title, description, time);

                link.append(icon, text);
                section.appendChild(link);
            });
            notificationContent.appendChild(section);
        });
        updateNotificationBadge();
        window.StudentAssistantPreferences?.formatTextTimes?.(notificationContent);
    };

    const openNotifications = () => {
        if (!notificationPanel) {
            return;
        }
        closeSearch({ restoreFocus: false });
        window.clearTimeout(notificationCloseTimer);
        notificationPanel.hidden = false;
        requestAnimationFrame(() => {
            notificationPanel.classList.add('is-visible');
            setButtonActive(notificationToggle, true);
            notificationClose?.focus();
            if (notificationContent && notificationContent.dataset.motionShown !== 'true') {
                notificationContent.dataset.motionShown = 'true';
                window.animateMotionItems?.(notificationContent.querySelectorAll('.notification-item'));
            }
        });
    };

    notificationToggle?.addEventListener('click', () => {
        if (notificationPanel?.hidden) {
            openNotifications();
        } else {
            closeNotifications();
        }
    });
    notificationClose?.addEventListener('click', () => closeNotifications());
    notificationReadAll?.addEventListener('click', () => {
        readNotificationIds = new Set(allNotifications.map((item) => item.id));
        try {
            window.localStorage.setItem(readStorageKey, JSON.stringify([...readNotificationIds]));
        } catch (_) {
        }
        renderNotifications();
    });
    document.addEventListener('click', (event) => {
        if (
            notificationPanel
            && !notificationPanel.hidden
            && !notificationPanel.contains(event.target)
            && !notificationToggle?.contains(event.target)
        ) {
            closeNotifications({ restoreFocus: false });
        }
    });

    if (searchShortcut) {
        searchShortcut.textContent = /Mac|iPhone|iPad/.test(navigator.platform) ? '⌘ K' : 'Ctrl K';
    }

    document.addEventListener('keydown', (event) => {
        if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
            event.preventDefault();
            event.stopImmediatePropagation();
            openSearch();
            return;
        }

        if (event.key === 'Escape') {
            if (searchOverlay && !searchOverlay.hidden) {
                event.preventDefault();
                closeSearch();
            } else if (notificationPanel && !notificationPanel.hidden) {
                event.preventDefault();
                closeNotifications();
            }
            return;
        }

        if (!searchOverlay || searchOverlay.hidden) {
            return;
        }
        if (event.key === 'ArrowDown') {
            event.preventDefault();
            updateActiveResult(activeResultIndex + 1);
        } else if (event.key === 'ArrowUp') {
            event.preventDefault();
            updateActiveResult(activeResultIndex - 1);
        } else if (event.key === 'Enter' && activeResultIndex >= 0) {
            const activeResult = searchResults?.querySelectorAll('[data-search-result]')[activeResultIndex];
            if (activeResult) {
                event.preventDefault();
                activeResult.click();
            }
        }
    }, true);

    renderNotifications();
})();
