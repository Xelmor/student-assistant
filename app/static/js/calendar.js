(() => {
    const filters = Array.from(document.querySelectorAll('[data-calendar-filter]'));
    const resetButton = document.getElementById('calendarResetFilters');
    const eventTypeSelect = document.querySelector('#calendar-event-form select[name="event_type"]');

    if (!filters.length) {
        return;
    }

    const applyFilters = () => {
        const enabledGroups = new Set(
            filters
                .filter((filter) => filter.checked)
                .map((filter) => filter.dataset.calendarFilter),
        );

        const revealedItems = [];
        document.querySelectorAll('[data-calendar-event]').forEach((event) => {
            const shouldShow = enabledGroups.has(event.dataset.eventGroup);
            if (event.hidden && shouldShow) {
                revealedItems.push(event);
            }
            event.hidden = !shouldShow;
        });
        window.animateMotionItems?.(revealedItems);
    };

    filters.forEach((filter) => filter.addEventListener('change', applyFilters));

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
