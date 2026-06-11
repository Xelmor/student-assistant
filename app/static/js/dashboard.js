function startDashboardClock() {
    const clock = document.getElementById('dashboard-live-clock');
    const liveDate = document.getElementById('dashboard-live-date');
    const remainingChip = document.getElementById('dashboard-lesson-remaining');
    if (!clock) {
        return;
    }

    function formatRemaining(totalSeconds) {
        const safeSeconds = Math.max(0, Math.floor(totalSeconds));
        const hours = Math.floor(safeSeconds / 3600);
        const minutes = Math.floor((safeSeconds % 3600) / 60);
        const seconds = safeSeconds % 60;

        if (hours > 0) {
            return `До конца: ${hours} ч ${minutes} мин`;
        }
        if (minutes > 0) {
            return `До конца: ${minutes} мин ${seconds} сек`;
        }
        return `До конца: ${seconds} сек`;
    }

    function renderTime() {
        const now = new Date();
        const settings = window.StudentAssistantPreferences?.getSettings?.() || {};
        const timeZone = settings.timezone && settings.timezone !== 'system'
            ? settings.timezone
            : undefined;
        const time = now.toLocaleTimeString('ru-RU', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
            hour12: settings.timeFormat === '12',
            timeZone,
        });
        clock.textContent = time;

        if (liveDate) {
            const browserDate = now.toLocaleDateString('ru-RU', { timeZone });
            liveDate.textContent = `Сегодня: ${browserDate}`;

            const isoBrowserDate = [
                now.getFullYear(),
                String(now.getMonth() + 1).padStart(2, '0'),
                String(now.getDate()).padStart(2, '0'),
            ].join('-');

            if (!timeZone && liveDate.dataset.serverDate && liveDate.dataset.serverDate !== isoBrowserDate) {
                window.location.reload();
            }
        }
    }

    function startLessonCountdown() {
        if (!remainingChip) {
            return;
        }

        let remainingSeconds = Number.parseInt(remainingChip.dataset.remainingSeconds || '0', 10);
        if (Number.isNaN(remainingSeconds)) {
            remainingSeconds = 0;
        }

        function renderRemaining() {
            remainingChip.textContent = formatRemaining(remainingSeconds);
            remainingSeconds = Math.max(0, remainingSeconds - 1);
        }

        renderRemaining();
        window.setInterval(renderRemaining, 1000);
    }

    renderTime();
    startLessonCountdown();
    window.setInterval(renderTime, 1000);
    document.addEventListener('studentAssistantPreferencesChanged', renderTime);
}

function initDashboardQuickTask() {
    const card = document.getElementById('dashboardQuickTaskCard');
    const form = document.getElementById('dashboardQuickTaskForm');
    const input = document.getElementById('dashboard-quick-task-title');
    const status = document.getElementById('dashboardQuickTaskStatus');
    const pendingCount = document.getElementById('dashboardPendingCount');
    const pendingCopy = document.getElementById('dashboardPendingCopy');
    let isSubmitting = false;

    if (!card || !form || !input || !status) {
        return;
    }

    card.addEventListener('click', (event) => {
        if (event.target.closest('form')) {
            return;
        }
        input.focus();
        input.select();
    });

    async function submitQuickTask() {
        if (isSubmitting) {
            return;
        }

        const title = input.value.trim();
        if (!title) {
            status.textContent = 'Введите название задачи';
            status.dataset.state = 'error';
            window.showToast?.({
                type: 'warning',
                title: 'Введите название задачи',
                description: 'Название нужно заполнить перед сохранением.',
                duration: 3600,
            });
            input.focus();
            return;
        }

        isSubmitting = true;
        form.classList.add('is-submitting');
        form.setAttribute('aria-busy', 'true');
        form.querySelector('[type="submit"]')?.classList.add('form-loading-button');
        status.textContent = 'Сохраняю...';
        status.dataset.state = 'loading';

        const formData = new FormData(form);
        formData.set('title', title);

        try {
            const response = await fetch(form.action, {
                method: 'POST',
                body: formData,
                headers: {
                    'X-Requested-With': 'XMLHttpRequest',
                },
            });

            const payload = await response.json();
            if (!response.ok || !payload.ok) {
                throw new Error(payload.error || 'request');
            }

            input.value = '';
            status.textContent = 'Задача добавлена';
            status.dataset.state = 'success';
            window.showToast?.({
                type: 'success',
                title: 'Задача добавлена',
                description: 'Новая задача появилась в списке.',
                duration: 4200,
            });

            if (pendingCount && typeof payload.pending_count === 'number') {
                pendingCount.textContent = String(payload.pending_count);
            }

            if (pendingCopy && typeof payload.pending_count === 'number') {
                if (payload.pending_count === 0) {
                    pendingCopy.textContent = 'Сейчас список чист. Можно добавить новую задачу.';
                } else if (payload.pending_count === 1) {
                    pendingCopy.textContent = 'Сейчас в работе одна задача.';
                } else {
                    pendingCopy.textContent = `Сейчас в работе ${payload.pending_count} задач.`;
                }
            }
        } catch (error) {
            status.textContent = 'Не удалось добавить задачу';
            status.dataset.state = 'error';
            window.showToast?.({
                type: 'error',
                title: 'Не удалось добавить задачу',
                description: 'Проверьте соединение и попробуйте ещё раз.',
                duration: 5200,
            });
        } finally {
            isSubmitting = false;
            form.classList.remove('is-submitting');
            form.removeAttribute('aria-busy');
            form.querySelector('[type="submit"]')?.classList.remove('form-loading-button');
        }
    }

    form.addEventListener('submit', async (event) => {
        event.preventDefault();
        await submitQuickTask();
    });

    input.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            void submitQuickTask();
        }
    });
}

startDashboardClock();
initDashboardQuickTask();
