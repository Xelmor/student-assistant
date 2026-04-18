function findPresetMatch(startTime, endTime, scheduleTimePresets) {
    if (!startTime || !endTime) {
        return null;
    }

    for (const [mode, config] of Object.entries(scheduleTimePresets)) {
        if (mode === 'free') {
            continue;
        }
        const match = (config.slots || []).find((slot) => slot.start === startTime && slot.end === endTime);
        if (match) {
            return { mode, slot: match };
        }
    }

    return null;
}

function getTimeContainer(element) {
    return element.closest('.schedule-time-row, .schedule-row, form');
}

function fillSlotSelect(slotSelect, mode, scheduleTimePresets, selectedSlotKey = '') {
    slotSelect.innerHTML = '<option value="">Выбери слот</option>';
    const preset = scheduleTimePresets[mode];
    if (!preset || !preset.slots || preset.slots.length === 0) {
        return;
    }

    preset.slots.forEach((slot) => {
        const option = document.createElement('option');
        option.value = slot.key;
        option.textContent = slot.label;
        option.dataset.start = slot.start;
        option.dataset.end = slot.end;
        if (selectedSlotKey && selectedSlotKey === slot.key) {
            option.selected = true;
        }
        slotSelect.appendChild(option);
    });
}

window.onTimeModeChange = function onTimeModeChange(modeSelect) {
    const container = getTimeContainer(modeSelect);
    if (!container) {
        return;
    }

    const slotSelect = container.querySelector('.schedule-time-slot');
    const mode = modeSelect.value;
    const scheduleTimePresets = window.scheduleTimePresets || {};

    if (!slotSelect) {
        return;
    }

    if (mode === 'free') {
        slotSelect.classList.add('d-none');
        slotSelect.innerHTML = '<option value="">Выбери слот</option>';
        return;
    }

    fillSlotSelect(slotSelect, mode, scheduleTimePresets);
    slotSelect.classList.remove('d-none');
};

window.onTimeSlotChange = function onTimeSlotChange(slotSelect) {
    const container = getTimeContainer(slotSelect);
    if (!container) {
        return;
    }

    const selectedOption = slotSelect.options[slotSelect.selectedIndex];
    if (!selectedOption || !selectedOption.dataset.start || !selectedOption.dataset.end) {
        return;
    }

    const startInput = container.querySelector('input[name="start_time"]');
    const endInput = container.querySelector('input[name="end_time"]');
    if (!startInput || !endInput) {
        return;
    }

    startInput.value = selectedOption.dataset.start;
    endInput.value = selectedOption.dataset.end;
};

function initializeTimeRow(container) {
    const modeSelect = container.querySelector('.schedule-time-mode');
    const slotSelect = container.querySelector('.schedule-time-slot');
    const startInput = container.querySelector('input[name="start_time"]');
    const endInput = container.querySelector('input[name="end_time"]');
    const scheduleTimePresets = window.scheduleTimePresets || {};

    if (!modeSelect || !slotSelect || !startInput || !endInput) {
        return;
    }

    const initialStart = container.dataset.currentStart || startInput.value;
    const initialEnd = container.dataset.currentEnd || endInput.value;
    const match = findPresetMatch(initialStart, initialEnd, scheduleTimePresets);

    if (!match) {
        modeSelect.value = 'free';
        slotSelect.classList.add('d-none');
        slotSelect.innerHTML = '<option value="">Выбери слот</option>';
        return;
    }

    modeSelect.value = match.mode;
    fillSlotSelect(slotSelect, match.mode, scheduleTimePresets, match.slot.key);
    slotSelect.classList.remove('d-none');
}

function initializeScheduleTimeControls(scope = document) {
    const containers = scope.querySelectorAll('.schedule-row, .schedule-time-row');
    containers.forEach((container) => {
        initializeTimeRow(container);
    });
}

function updateWeekdayPickerState(picker) {
    const hiddenInput = picker.querySelector('[data-weekday-input]');
    const summary = picker.querySelector('[data-weekday-summary]');
    const selectedButtons = Array.from(picker.querySelectorAll('[data-weekday-option].is-selected'));
    const selectedValues = selectedButtons.map((button) => button.dataset.weekdayValue);
    const weekdayLabels = window.weekdayLabels || {};
    const selectedLabels = selectedValues.map((value) => weekdayLabels[value]).filter(Boolean);

    if (hiddenInput) {
        hiddenInput.value = selectedValues.join(',');
    }

    if (summary) {
        summary.textContent = selectedLabels.length
            ? `Выбрано: ${selectedLabels.join(', ')}`
            : 'Выберите хотя бы один день';
    }
}

function initializeWeekdayPickers(scope = document) {
    const pickers = scope.querySelectorAll('[data-weekday-picker]');
    pickers.forEach((picker) => {
        if (picker.dataset.initialized === 'true') {
            updateWeekdayPickerState(picker);
            return;
        }

        picker.dataset.initialized = 'true';
        const buttons = picker.querySelectorAll('[data-weekday-option]');

        buttons.forEach((button) => {
            button.addEventListener('click', () => {
                const selectedCount = picker.querySelectorAll('[data-weekday-option].is-selected').length;
                const isSelected = button.classList.contains('is-selected');

                if (isSelected && selectedCount === 1) {
                    return;
                }

                button.classList.toggle('is-selected');
                button.setAttribute('aria-pressed', button.classList.contains('is-selected') ? 'true' : 'false');
                updateWeekdayPickerState(picker);
            });
        });

        updateWeekdayPickerState(picker);
    });
}

window.toggleScheduleEdit = function toggleScheduleEdit(itemId) {
    const row = document.getElementById(`schedule-edit-${itemId}`);
    if (!row) {
        return;
    }

    row.classList.toggle('d-none');
};

window.addScheduleRow = function addScheduleRow() {
    const template = document.getElementById('schedule-row-template');
    const container = document.getElementById('schedule-rows');
    const clone = template.content.cloneNode(true);
    container.appendChild(clone);
    initializeScheduleTimeControls(container.lastElementChild);
    initializeWeekdayPickers(container.lastElementChild);
};

window.removeScheduleRow = function removeScheduleRow(button) {
    const rows = document.querySelectorAll('.schedule-row');
    if (rows.length <= 1) {
        alert('Нужна хотя бы одна строка для ввода.');
        return;
    }
    button.closest('.schedule-row').remove();
};

initializeScheduleTimeControls();
initializeWeekdayPickers();
