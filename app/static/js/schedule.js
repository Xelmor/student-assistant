function findPresetMatch(startTime, endTime, presets) {
    if (!startTime || !endTime) {
        return null;
    }
    for (const [mode, config] of Object.entries(presets)) {
        if (mode === 'free') {
            continue;
        }
        const slot = (config.slots || []).find((item) => item.start === startTime && item.end === endTime);
        if (slot) {
            return { mode, slot };
        }
    }
    return null;
}

function getTimeContainer(element) {
    return element.closest('.schedule-time-row, .schedule-row, form');
}

function fillSlotSelect(slotSelect, mode, selectedSlotKey = '') {
    slotSelect.innerHTML = '<option value="">Выбери слот</option>';
    const preset = (window.scheduleTimePresets || {})[mode];
    if (!preset?.slots?.length) {
        return;
    }
    preset.slots.forEach((slot) => {
        const option = document.createElement('option');
        option.value = slot.key;
        option.textContent = slot.label;
        option.dataset.start = slot.start;
        option.dataset.end = slot.end;
        option.selected = selectedSlotKey === slot.key;
        slotSelect.appendChild(option);
    });
}

function setSlotVisibility(slotSelect, visible) {
    slotSelect.classList.toggle('d-none', !visible);
    slotSelect.closest('.schedule-slot-field')?.classList.toggle('d-none', !visible);
}

window.onTimeModeChange = function onTimeModeChange(modeSelect) {
    const container = getTimeContainer(modeSelect);
    const slotSelect = container?.querySelector('.schedule-time-slot');
    if (!slotSelect) {
        return;
    }
    if (modeSelect.value === 'free') {
        slotSelect.innerHTML = '<option value="">Выбери слот</option>';
        setSlotVisibility(slotSelect, false);
        return;
    }
    fillSlotSelect(slotSelect, modeSelect.value);
    setSlotVisibility(slotSelect, true);
};

window.onTimeSlotChange = function onTimeSlotChange(slotSelect) {
    const container = getTimeContainer(slotSelect);
    const option = slotSelect.options[slotSelect.selectedIndex];
    const startInput = container?.querySelector('input[name="start_time"]');
    const endInput = container?.querySelector('input[name="end_time"]');
    if (!option?.dataset.start || !option?.dataset.end || !startInput || !endInput) {
        return;
    }
    startInput.value = option.dataset.start;
    endInput.value = option.dataset.end;
};

function initializeTimeRow(container) {
    const modeSelect = container.querySelector('.schedule-time-mode');
    const slotSelect = container.querySelector('.schedule-time-slot');
    const startInput = container.querySelector('input[name="start_time"]');
    const endInput = container.querySelector('input[name="end_time"]');
    if (!modeSelect || !slotSelect || !startInput || !endInput) {
        return;
    }

    const start = container.dataset.currentStart || startInput.value;
    const end = container.dataset.currentEnd || endInput.value;
    const match = findPresetMatch(start, end, window.scheduleTimePresets || {});
    if (!match) {
        modeSelect.value = 'free';
        setSlotVisibility(slotSelect, false);
        return;
    }

    modeSelect.value = match.mode;
    fillSlotSelect(slotSelect, match.mode, match.slot.key);
    setSlotVisibility(slotSelect, true);
}

function initializeScheduleTimeControls(scope = document) {
    scope.querySelectorAll('.schedule-row, .schedule-time-row').forEach(initializeTimeRow);
}

function updateWeekdayPickerState(picker) {
    const hiddenInput = picker.querySelector('[data-weekday-input]');
    const summary = picker.querySelector('[data-weekday-summary]');
    const selected = [...picker.querySelectorAll('[data-weekday-option].is-selected')];
    const values = selected.map((button) => button.dataset.weekdayValue);
    const labels = values.map((value) => (window.weekdayLabels || {})[value]).filter(Boolean);
    if (hiddenInput) {
        hiddenInput.value = values.join(',');
    }
    if (summary) {
        summary.textContent = labels.length ? `Выбрано: ${labels.join(', ')}` : 'Выберите хотя бы один день';
    }
}

function initializeWeekdayPickers(scope = document) {
    scope.querySelectorAll('[data-weekday-picker]').forEach((picker) => {
        if (picker.dataset.initialized === 'true') {
            updateWeekdayPickerState(picker);
            return;
        }
        picker.dataset.initialized = 'true';
        picker.querySelectorAll('[data-weekday-option]').forEach((button) => {
            button.addEventListener('click', () => {
                const selectedCount = picker.querySelectorAll('[data-weekday-option].is-selected').length;
                if (button.classList.contains('is-selected') && selectedCount === 1) {
                    return;
                }
                button.classList.toggle('is-selected');
                button.setAttribute('aria-pressed', String(button.classList.contains('is-selected')));
                updateWeekdayPickerState(picker);
            });
        });
        updateWeekdayPickerState(picker);
    });
}

window.toggleScheduleEdit = function toggleScheduleEdit(itemId) {
    const panel = document.getElementById(`schedule-edit-${itemId}`);
    if (!panel) {
        return;
    }
    const shouldOpen = panel.classList.contains('d-none');
    document.querySelectorAll('[id^="schedule-edit-"]').forEach((item) => item.classList.add('d-none'));
    if (!shouldOpen) {
        return;
    }
    panel.classList.remove('d-none');
    document.getElementById(`schedule-row-${itemId}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
};

window.addScheduleRow = function addScheduleRow() {
    const template = document.getElementById('schedule-row-template');
    const container = document.getElementById('schedule-rows');
    if (!template || !container) {
        return;
    }
    const clone = template.content.cloneNode(true);
    container.appendChild(clone);
    initializeScheduleTimeControls(container.lastElementChild);
    initializeWeekdayPickers(container.lastElementChild);
};

window.removeScheduleRow = function removeScheduleRow(button) {
    const rows = document.querySelectorAll('.schedule-row');
    if (rows.length <= 1) {
        return;
    }
    button.closest('.schedule-row')?.remove();
};

(() => {
    const weekPanel = document.querySelector('.schedule-week-panel');
    const daysRoot = document.getElementById('scheduleDays');
    const emptyState = document.getElementById('scheduleEmptyFilter');
    const resetButton = document.getElementById('scheduleResetFilters');
    const searchInput = document.getElementById('scheduleSearchInput');
    const subjectFilter = document.getElementById('scheduleSubjectFilter');
    const roomFilter = document.getElementById('scheduleRoomFilter');
    const typeButtons = [...document.querySelectorAll('[data-schedule-filter]')];
    const viewButtons = [...document.querySelectorAll('[data-schedule-view]')];
    let activeType = 'all';

    const items = () => [...document.querySelectorAll('[data-schedule-item]')];
    const days = () => [...document.querySelectorAll('[data-schedule-day]')];

    const applyFilters = () => {
        const query = (searchInput?.value || '').trim().toLocaleLowerCase('ru');
        const subject = subjectFilter?.value || '';
        const room = roomFilter?.value || '';
        const revealedItems = [];

        items().forEach((item) => {
            const typeMatches = activeType === 'all' || item.dataset.scheduleType === activeType;
            const subjectMatches = !subject || item.dataset.scheduleSubject === subject;
            const roomMatches = !room || item.dataset.scheduleRoom === room;
            const searchMatches = !query || (item.dataset.scheduleSearch || '').includes(query);
            const shouldShow = typeMatches && subjectMatches && roomMatches && searchMatches;
            if (item.hidden && shouldShow) {
                revealedItems.push(item);
            }
            item.hidden = !shouldShow;
        });

        let visibleTotal = 0;
        days().forEach((day) => {
            const visible = [...day.querySelectorAll('[data-schedule-item]')].filter((item) => !item.hidden).length;
            const count = day.querySelector('[data-day-count]');
            if (count) {
                count.textContent = `${visible} ${visible === 1 ? 'занятие' : 'занятий'}`;
            }
            const hasStoredItems = day.querySelectorAll('[data-schedule-item]').length > 0;
            day.hidden = visible === 0 && hasStoredItems;
            visibleTotal += visible;
        });

        const emptyWasHidden = emptyState?.hidden;
        if (emptyState) {
            emptyState.hidden = visibleTotal !== 0 || items().length === 0;
        }
        if (daysRoot) {
            daysRoot.hidden = visibleTotal === 0 && items().length > 0;
        }
        if (emptyWasHidden && emptyState && !emptyState.hidden) {
            revealedItems.push(emptyState);
        }
        window.animateMotionItems?.(revealedItems);
    };

    typeButtons.forEach((button) => {
        button.addEventListener('click', () => {
            activeType = button.dataset.scheduleFilter || 'all';
            typeButtons.forEach((item) => item.classList.toggle('is-active', item === button));
            applyFilters();
        });
    });
    searchInput?.addEventListener('input', applyFilters);
    subjectFilter?.addEventListener('change', applyFilters);
    roomFilter?.addEventListener('change', applyFilters);
    resetButton?.addEventListener('click', () => {
        activeType = 'all';
        if (searchInput) searchInput.value = '';
        if (subjectFilter) subjectFilter.value = '';
        if (roomFilter) roomFilter.value = '';
        typeButtons.forEach((button) => {
            button.classList.toggle('is-active', button.dataset.scheduleFilter === 'all');
        });
        applyFilters();
        searchInput?.focus();
    });

    document.querySelectorAll('[data-schedule-day-toggle]').forEach((button) => {
        button.addEventListener('click', () => {
            const day = button.closest('[data-schedule-day]');
            const collapsed = day?.classList.toggle('is-collapsed') || false;
            button.setAttribute('aria-expanded', String(!collapsed));
        });
    });

    viewButtons.forEach((button) => {
        button.addEventListener('click', () => {
            weekPanel?.classList.toggle('is-calendar-view', button.dataset.scheduleView === 'calendar');
            viewButtons.forEach((item) => item.classList.toggle('is-active', item === button));
        });
    });

    initializeScheduleTimeControls();
    initializeWeekdayPickers();
})();
