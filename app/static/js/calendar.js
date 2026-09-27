(() => {
    const filters = Array.from(document.querySelectorAll('[data-calendar-filter]'));
    const resetButton = document.getElementById('calendarResetFilters');
    const eventTypeSelect = document.querySelector('#calendar-event-form select[name="event_type"]');

    if (!filters.length) {
        return;
    }

    const storageKey = `student-assistant.calendar.filters.${document.documentElement.dataset.userId || 'local'}`;
    try {
        const saved = JSON.parse(sessionStorage.getItem(storageKey));
        if (Array.isArray(saved)) {
            filters.forEach(filter => { filter.checked = saved.includes(filter.dataset.calendarFilter); });
        }
    } catch (_) { /* Filtering also works when storage is unavailable. */ }

    const applyFilters = () => {
        const enabledGroups = new Set(
            filters
                .filter((filter) => filter.checked)
                .map((filter) => filter.dataset.calendarFilter),
        );

        document.querySelectorAll('[data-calendar-event]').forEach((event) => {
            const shouldShow = enabledGroups.has(event.dataset.eventGroup);
            event.hidden = !shouldShow;
        });
        document.querySelectorAll('[data-calendar-month-day]').forEach(day => {
            const events = [...day.querySelectorAll('[data-month-event]')]
                .filter(event => enabledGroups.has(event.dataset.eventGroup));
            events.forEach((event, index) => { event.hidden = index >= 3; });
            const more = day.querySelector('[data-calendar-more]');
            more.hidden = events.length <= 3;
            more.textContent = `Ещё ${Math.max(0, events.length - 3)}`;
        });
        document.querySelectorAll('[data-calendar-agenda-day]').forEach(day => {
            day.hidden = !day.querySelector('[data-calendar-event]:not([hidden])');
        });
        const empty = document.querySelector('[data-calendar-period-empty]');
        if (empty) {
            empty.hidden = Boolean(document.querySelector('[data-calendar-agenda-day]:not([hidden])'));
        }
        try { sessionStorage.setItem(storageKey, JSON.stringify([...enabledGroups])); } catch (_) {}
    };

    filters.forEach((filter) => filter.addEventListener('change', applyFilters));
    applyFilters();
    window.addEventListener('pageshow', applyFilters);

    resetButton?.addEventListener('click', () => {
        filters.forEach((filter) => {
            filter.checked = true;
        });
        applyFilters();
    });

    document.querySelectorAll('[data-calendar-event-type]').forEach((link) => {
        link.addEventListener('click', () => {
            if (eventTypeSelect) {
                eventTypeSelect.value = link.dataset.calendarEventType;
            }
        });
    });
})();
if (document.getElementById('onboardingCalendarCompleted')) {
    window.showToast?.({
        type: 'success',
        title: 'Шаг выполнен',
        description: 'Календарь открыт и добавлен в прогресс настройки.',
        duration: 4200,
    });
}
