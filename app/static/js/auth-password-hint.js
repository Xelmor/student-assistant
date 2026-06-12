(() => {
    const button = document.querySelector('[data-password-hint-request]');
    const result = document.querySelector('[data-password-hint-result]');
    const usernameInput = document.getElementById('login-username');
    const form = button?.closest('form');

    if (
        !(button instanceof HTMLButtonElement)
        || !(result instanceof HTMLElement)
        || !(usernameInput instanceof HTMLInputElement)
        || !(form instanceof HTMLFormElement)
    ) {
        return;
    }

    const showMessage = (message, isError = false) => {
        result.textContent = message;
        result.hidden = false;
        result.classList.toggle('is-error', isError);
        button.setAttribute('aria-expanded', 'true');
    };

    button.addEventListener('click', async () => {
        const username = usernameInput.value.trim();
        if (!username) {
            showMessage('Сначала введи логин или email.', true);
            usernameInput.focus();
            return;
        }

        const csrfInput = form.elements.csrf_token;
        const csrfToken = csrfInput instanceof HTMLInputElement ? csrfInput.value : '';
        button.disabled = true;
        button.classList.add('is-loading');
        button.querySelector('span').textContent = 'Ищем подсказку...';

        try {
            const response = await fetch('/password-hint', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
                },
                body: new URLSearchParams({
                    username,
                    csrf_token: csrfToken,
                }),
            });
            const payload = await response.json();
            showMessage(
                payload.message || payload.detail || 'Не удалось получить подсказку.',
                !response.ok,
            );
        } catch {
            showMessage('Не удалось получить подсказку. Попробуй ещё раз.', true);
        } finally {
            button.disabled = false;
            button.classList.remove('is-loading');
            button.querySelector('span').textContent = 'Показать подсказку к паролю';
        }
    });

    usernameInput.addEventListener('input', () => {
        result.hidden = true;
        result.textContent = '';
        result.classList.remove('is-error');
        button.setAttribute('aria-expanded', 'false');
    });
})();
