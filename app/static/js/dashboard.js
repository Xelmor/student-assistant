(() => {
    const center = document.getElementById('dashboardCenter');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    function getClockParts() {
        const now = new Date();
        const settings = window.StudentAssistantPreferences?.getSettings?.() || {};
        const timeZone = settings.timezone && settings.timezone !== 'system' ? settings.timezone : undefined;
        const formatter = new Intl.DateTimeFormat('ru-RU', {
            hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false, timeZone,
        });
        const parts = Object.fromEntries(formatter.formatToParts(now).map((part) => [part.type, part.value]));
        return { now, timeZone, hours: Number(parts.hour) % 24, minutes: Number(parts.minute), text: formatter.format(now) };
    }

    function formatRemaining(totalSeconds) {
        const seconds = Math.max(0, Math.floor(totalSeconds));
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        if (hours) return `До конца: ${hours} ч ${minutes} мин`;
        if (minutes) return `До конца: ${minutes} мин`;
        return `До конца: ${seconds} сек`;
    }

    function startDashboardClock() {
        const clock = document.getElementById('dashboard-live-clock');
        const liveDate = document.getElementById('dashboard-live-date');
        const remaining = document.getElementById('dashboard-lesson-remaining');
        let seconds = Number.parseInt(remaining?.dataset.remainingSeconds || '0', 10) || 0;

        const render = () => {
            const parts = getClockParts();
            if (clock) clock.textContent = parts.text;
            if (liveDate) liveDate.textContent = `Сегодня: ${parts.now.toLocaleDateString('ru-RU', { timeZone: parts.timeZone })}`;
            renderTimeline(parts.hours * 60 + parts.minutes);
        };
        const renderRemaining = () => {
            if (!remaining) return;
            remaining.textContent = formatRemaining(seconds);
            seconds = Math.max(0, seconds - 1);
        };
        render();
        renderRemaining();
        window.setInterval(render, 1000);
        if (remaining) window.setInterval(renderRemaining, 1000);
        document.addEventListener('studentAssistantPreferencesChanged', render);
    }

    function formatMinutes(value) {
        const safe = Math.max(0, Math.min(1440, value));
        const hours = Math.floor(safe / 60) % 24;
        return `${String(hours).padStart(2, '0')}:${String(safe % 60).padStart(2, '0')}`;
    }

    function renderTimeline(nowMinutes = Number(center?.dataset.nowMinutes || '0')) {
        if (!center) return;
        const timeline = document.getElementById('dashboardDayTimeline');
        const scale = document.getElementById('dashboardTimelineScale');
        const eventsRoot = document.getElementById('dashboardTimelineEvents');
        const start = Number(center.dataset.dayStart || '0');
        const end = Number(center.dataset.dayEnd || '1440');
        const span = Math.max(1, end - start);
        const position = (minute) => Math.max(0, Math.min(100, ((minute - start) / span) * 100));
        const events = [...(eventsRoot?.querySelectorAll('[data-timeline-event]') || [])]
            .sort((a, b) => Number(a.dataset.minute) - Number(b.dataset.minute));

        if (scale && !scale.childElementCount) {
            const candidates = [...new Set([start, ...events.map((event) => Number(event.dataset.minute)), end])].sort((a, b) => a - b);
            const labels = candidates.length <= 6
                ? candidates
                : [candidates[0], ...candidates.slice(1, -1).filter((_, index, values) => index % Math.ceil(values.length / 4) === 0).slice(0, 4), candidates.at(-1)];
            labels.forEach((minute) => {
                const label = document.createElement('span');
                label.textContent = formatMinutes(minute);
                label.style.left = `${position(minute)}%`;
                scale.append(label);
            });
        }

        const eventWidthPercent = eventsRoot?.clientWidth
            ? Math.max(...events.map((event) => event.getBoundingClientRect().width), 0) / eventsRoot.clientWidth * 100
            : 18;
        const minimumLaneDistance = eventWidthPercent + 1.5;
        const laneEnds = [];
        let maxLane = 0;
        events.forEach((event, index) => {
            const minute = Number(event.dataset.minute);
            const eventPosition = position(minute);
            let lane = laneEnds.findIndex((lastPosition) => eventPosition - lastPosition >= minimumLaneDistance);
            if (lane < 0) lane = laneEnds.length;
            laneEnds[lane] = eventPosition;
            maxLane = Math.max(maxLane, lane);
            event.style.setProperty('--event-position', `${eventPosition}%`);
            event.style.setProperty('--event-lane', String(lane));
            event.style.setProperty('--event-order', String(index));
            const eventEnd = Number(event.dataset.endMinute || minute);
            event.classList.toggle('is-past', eventEnd < nowMinutes);
        });
        eventsRoot?.style.setProperty('--timeline-height', `${Math.max(2, maxLane + 1) * 7 + 0.8}rem`);

        const nowPosition = position(nowMinutes);
        timeline?.style.setProperty('--now-position', `${nowPosition}%`);
        center.dataset.nowMinutes = String(nowMinutes);
    }

    function initCountUp() {
        document.querySelectorAll('[data-dashboard-stat] [data-count]').forEach((number, index) => {
            const target = Number(number.dataset.count || '0');
            if (reduceMotion || target <= 0) {
                number.textContent = String(target);
                return;
            }
            const delay = 300 + index * 100;
            const duration = 620;
            let startTime = null;
            const tick = (timestamp) => {
                if (startTime === null) startTime = timestamp;
                const elapsed = Math.max(0, timestamp - startTime - delay);
                const progress = Math.min(1, elapsed / duration);
                const eased = 1 - Math.pow(1 - progress, 3);
                number.textContent = String(Math.round(target * eased));
                if (progress < 1) window.requestAnimationFrame(tick);
            };
            number.textContent = '0';
            window.requestAnimationFrame(tick);
        });
    }

    function initLoadSequence() {
        if (!center) return;
        if (reduceMotion) {
            center.classList.add('is-ready', 'is-settled');
            return;
        }
        window.requestAnimationFrame(() => window.requestAnimationFrame(() => center.classList.add('is-ready')));
        window.setTimeout(() => center.classList.add('is-settled'), 2500);
    }

    function initSpotlight() {
        if (!center || reduceMotion || !window.matchMedia('(hover: hover) and (pointer: fine)').matches) return;
        let frame = 0;
        center.addEventListener('pointermove', (event) => {
            if (frame) return;
            frame = window.requestAnimationFrame(() => {
                const box = center.getBoundingClientRect();
                center.style.setProperty('--dashboard-spotlight-x', `${event.clientX - box.left}px`);
                center.style.setProperty('--dashboard-spotlight-y', `${event.clientY - box.top}px`);
                center.style.setProperty('--dashboard-spotlight-opacity', '1');
                frame = 0;
            });
        });
        center.addEventListener('pointerleave', () => center.style.setProperty('--dashboard-spotlight-opacity', '0'));
    }

    function markOnboardingStepComplete(stepKey) {
        const card = document.getElementById('dashboardOnboarding');
        const step = card?.querySelector(`[data-onboarding-step="${stepKey}"]`);
        if (!card || !step || step.classList.contains('is-completed')) return;
        step.classList.remove('is-active');
        step.classList.add('is-completed');
        const state = step.querySelector('.onboarding-step-state');
        if (state) state.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 12 4 4 8-9"></path></svg>';
        const current = Number.parseInt(card.dataset.onboardingCompleted || '0', 10) + 1;
        const total = Number.parseInt(card.dataset.onboardingTotal || '4', 10);
        const percent = Math.round((current / total) * 100);
        card.dataset.onboardingCompleted = String(current);
        const completed = document.getElementById('onboardingCompletedCount');
        const percentLabel = document.getElementById('onboardingPercent');
        if (completed) completed.textContent = String(current);
        if (percentLabel) percentLabel.textContent = `${percent}%`;
        document.getElementById('onboardingProgressBar')?.style.setProperty('--onboarding-progress', `${percent}%`);
        card.querySelector('.onboarding-progress-track')?.setAttribute('aria-valuenow', String(current));
        card.querySelector('.onboarding-step:not(.is-completed)')?.classList.add('is-active');
    }

    function pendingLabel(count) {
        const remainder = count % 10;
        const teen = count % 100;
        if (remainder === 1 && teen !== 11) return 'активная задача';
        if ([2, 3, 4].includes(remainder) && ![12, 13, 14].includes(teen)) return 'активные задачи';
        return 'активных задач';
    }

    function initQuickTask() {
        const card = document.getElementById('dashboardQuickTaskCard');
        const form = document.getElementById('dashboardQuickTaskForm');
        const input = document.getElementById('dashboard-quick-task-title');
        const status = document.getElementById('dashboardQuickTaskStatus');
        let submitting = false;
        if (!card || !form || !input || !status) return;

        card.addEventListener('click', (event) => {
            if (!event.target.closest('a, button, form')) input.focus();
        });
        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            if (submitting) return;
            const title = input.value.trim();
            if (!title) {
                status.textContent = 'Введите название задачи';
                input.focus();
                return;
            }
            submitting = true;
            form.setAttribute('aria-busy', 'true');
            status.textContent = 'Сохраняю…';
            const data = new FormData(form);
            data.set('title', title);
            try {
                const response = await fetch(form.action, { method: 'POST', body: data, headers: { 'X-Requested-With': 'XMLHttpRequest' } });
                const payload = await response.json();
                if (!response.ok || !payload.ok) throw new Error(payload.error || 'request');
                input.value = '';
                status.textContent = 'Задача добавлена';
                markOnboardingStepComplete('task');
                if (typeof payload.pending_count === 'number') {
                    const count = document.getElementById('dashboardCorePendingCount');
                    const label = document.getElementById('dashboardCorePendingLabel');
                    if (count) {
                        count.textContent = String(payload.pending_count);
                        count.dataset.count = String(payload.pending_count);
                    }
                    if (label) label.textContent = pendingLabel(payload.pending_count);
                }
                window.showToast?.({ type: 'success', title: 'Задача добавлена', description: 'Новая задача появилась в списке.', duration: 3800 });
            } catch (_) {
                status.textContent = 'Не удалось добавить задачу';
                window.showToast?.({ type: 'error', title: 'Не удалось добавить задачу', description: 'Проверь соединение и попробуй ещё раз.', duration: 5000 });
            } finally {
                submitting = false;
                form.removeAttribute('aria-busy');
            }
        });
    }

    function initOnboarding() {
        const skipButton = document.getElementById('onboardingSkipButton');
        const skipForm = document.getElementById('onboardingSkipForm');
        const status = document.getElementById('onboardingStatus')?.dataset.status || '';
        const messages = {
            completed: { type: 'success', title: 'Onboarding завершён', description: 'Рабочее пространство готово к учёбе.' },
            skipped: { type: 'info', title: 'Настройка пропущена', description: 'Все разделы останутся доступны.' },
            incomplete: { type: 'warning', title: 'Заверши оставшиеся шаги', description: 'После этого подсказки можно будет скрыть.' },
        };
        if (messages[status]) {
            window.showToast?.({ ...messages[status], duration: 4200 });
            const clean = new URL(window.location.href);
            clean.searchParams.delete('onboarding');
            window.history.replaceState({}, '', `${clean.pathname}${clean.search}${clean.hash}`);
        }
        skipButton?.addEventListener('click', () => {
            if (!skipForm) return;
            const submit = async () => {
                const response = await fetch(skipForm.action, { method: 'POST', body: new FormData(skipForm), credentials: 'same-origin', headers: { 'X-Requested-With': 'XMLHttpRequest' }, redirect: 'follow' });
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                window.location.assign(response.url);
            };
            const opened = window.requestConfirmation?.({ title: 'Пропустить настройку?', description: 'Ты сможешь добавить предметы, задачи и расписание позже.', confirmLabel: 'Пропустить', trigger: skipButton, onConfirm: submit });
            if (!opened && window.confirm('Пропустить настройку?')) void submit();
        });
    }

    renderTimeline();
    startDashboardClock();
    initCountUp();
    initLoadSequence();
    initSpotlight();
    initQuickTask();
    initOnboarding();
})();
