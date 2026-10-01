(() => {
    const card = document.getElementById('profile-telegram');
    if (!card) {
        return;
    }

    const statusMessages = {
        'rate-limited': {type: 'info', title: 'Слишком много попыток', description: 'Подожди немного и повтори.'},
        'code-created': {
            type: 'success',
            title: 'Код подключения создан',
            description: 'Отправь команду боту в течение указанного времени.',
        },
        'code-error': {
            type: 'error',
            title: 'Не удалось создать код',
            description: 'Попробуй ещё раз через несколько секунд.',
        },
        'already-linked': {
            type: 'info',
            title: 'Telegram уже подключён',
            description: 'Сначала отключи текущую привязку.',
        },
        unlinked: {
            type: 'success',
            title: 'Telegram отключён',
            description: 'Бот больше не связан с этим аккаунтом.',
        },
        'digest-saved': {
            type: 'success',
            title: 'Настройки сводки сохранены',
            description: 'Время сохранено. Отправка зависит от доступности сервиса уведомлений.',
        },
        'digest-error': {
            type: 'error',
            title: 'Не удалось сохранить сводку',
            description: 'Проверь время и часовой пояс.',
        },
        'digest-not-linked': {
            type: 'info',
            title: 'Сначала подключи Telegram',
            description: 'После подключения станут доступны ежедневные сводки.',
        },
        'digest-test-sent': {
            type: 'success',
            title: 'Тестовая сводка отправлена',
            description: 'Проверь личный чат с ботом.',
        },
        'digest-test-error': {
            type: 'error',
            title: 'Не удалось отправить сводку',
            description: 'Не удалось отправить тестовую сводку. Попробуй ещё раз.',
        },
        'notifications-saved': {
            type: 'success',
            title: 'Настройки уведомлений сохранены',
            description: 'Сводка и напоминания обновлены.',
        },
        'notifications-error': {
            type: 'error',
            title: 'Не удалось сохранить настройки',
            description: 'Проверь время и выбранный интервал напоминания.',
        },
        'notifications-not-linked': {
            type: 'info',
            title: 'Telegram не подключён',
            description: 'Сначала подключи бота, чтобы включить уведомления.',
        },
    };

    const status = card.dataset.telegramStatus || '';
    if (statusMessages[status]) {
        window.showToast?.({ ...statusMessages[status], duration: 4400 });
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete('telegram_status');
        window.history.replaceState(
            {},
            '',
            `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`,
        );
    }

    let timer;
    const deadline = Date.now() + 10 * 60 * 1000;
    let waiting = card.dataset.telegramWaiting === 'true';
    const label = document.getElementById('telegramConnectionStatus');
    const poll = async () => {
        clearTimeout(timer);
        if (!waiting || document.hidden) return;
        if (Date.now() >= deadline) {
            waiting = false;
            if (label) label.textContent = 'Проверка завершена. Обнови страницу, чтобы проверить связь.';
            return;
        }
        try {
            const response = await fetch('/profile/telegram/status', {
                headers: {Accept: 'application/json'}, cache: 'no-store',
                signal: AbortSignal.timeout(5000),
            });
            if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('status');
            const data = await response.json();
            if (data.state === 'linked') {
                waiting = false;
                window.location.reload();
                return;
            }
            if (data.state === 'expired' || data.state === 'unlinked') {
                waiting = false;
                document.querySelector('.profile-telegram-code-wrap')?.remove();
                if (label) label.textContent = 'Код истёк или отменён. Создай новый код.';
                return;
            }
            if (label) label.textContent = 'Ожидаем подключения в личном чате с ботом…';
        } catch (_) {
            if (label) label.textContent = 'Не удалось проверить связь. Повторим проверку.';
        }
        if (waiting && !document.hidden) timer = setTimeout(poll, 3000);
    };
    document.addEventListener('visibilitychange', () => {
        clearTimeout(timer);
        if (!document.hidden) poll();
    });
    window.addEventListener('pagehide', () => { waiting = false; clearTimeout(timer); });
    poll();

    const copyButton = document.getElementById('telegramCopyCode');
    const command = document.getElementById('telegramLinkCommand');
    copyButton?.addEventListener('click', async () => {
        const value = command?.textContent?.trim();
        if (!value) {
            return;
        }
        try {
            await navigator.clipboard.writeText(value);
            const label = copyButton.querySelector('span');
            if (label) {
                label.textContent = 'Скопировано';
                window.setTimeout(() => {
                    label.textContent = 'Копировать';
                }, 1600);
            }
            window.showToast?.({
                type: 'success',
                title: 'Команда скопирована',
                description: 'Теперь отправь её боту в Telegram.',
                duration: 3000,
            });
        } catch (_) {
            window.showToast?.({
                type: 'error',
                title: 'Не удалось скопировать',
                description: 'Выдели команду и скопируй её вручную.',
                duration: 4200,
            });
        }
    });
})();
