(() => {
    const card = document.getElementById('profile-telegram');
    if (!card) {
        return;
    }

    const statusMessages = {
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
            description: 'Бот отправит её в выбранное время.',
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
