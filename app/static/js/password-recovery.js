(() => {
    const forms = document.querySelectorAll('[data-recovery-form]');

    const setFieldError = (input, message) => {
        if (!(input instanceof HTMLInputElement)) {
            return;
        }
        const field = input.closest('.password-recovery-field');
        const error = field?.querySelector('.password-recovery-field-error');
        field?.classList.toggle('is-invalid', Boolean(message));
        input.setAttribute('aria-invalid', String(Boolean(message)));
        if (error) {
            error.textContent = message;
            error.hidden = !message;
        }
    };

    forms.forEach((form) => {
        const type = form.dataset.recoveryForm;
        const submitButton = form.querySelector('[data-recovery-submit]');
        const submitLabel = submitButton?.querySelector('[data-submit-label]');
        if (submitButton instanceof HTMLButtonElement && submitLabel) {
            submitButton.dataset.defaultLabel = submitLabel.textContent;
        }

        form.querySelectorAll('input:not([type="hidden"])').forEach((input) => {
            input.addEventListener('input', () => setFieldError(input, ''));
        });

        form.addEventListener('submit', (event) => {
            let firstInvalid = null;

            if (type === 'email') {
                const email = form.elements.email;
                const valid = email instanceof HTMLInputElement && email.validity.valid;
                if (!valid) {
                    setFieldError(email, 'Введите корректный email.');
                    firstInvalid = email;
                }
            }

            if (type === 'password') {
                const password = form.elements.new_password;
                const confirmation = form.elements.confirm_password;
                if (
                    !(password instanceof HTMLInputElement)
                    || password.value.length < 8
                    || password.value.length > 128
                ) {
                    setFieldError(password, 'Пароль должен содержать от 8 до 128 символов.');
                    firstInvalid = password;
                }
                if (!(confirmation instanceof HTMLInputElement) || confirmation.value !== password.value) {
                    setFieldError(confirmation, 'Пароли не совпадают.');
                    firstInvalid ||= confirmation;
                }
            }

            if (firstInvalid) {
                event.preventDefault();
                firstInvalid.focus();
                return;
            }

            if (submitButton instanceof HTMLButtonElement) {
                const label = submitButton.querySelector('[data-submit-label]');
                submitButton.disabled = true;
                submitButton.classList.add('is-loading');
                submitButton.setAttribute('aria-busy', 'true');
                if (label) {
                    label.textContent = submitButton.dataset.loadingLabel || 'Отправляем...';
                }
            }
        });
    });

    window.addEventListener('pageshow', () => {
        document.querySelectorAll('[data-recovery-submit]').forEach((button) => {
            if (!(button instanceof HTMLButtonElement)) {
                return;
            }
            button.disabled = false;
            button.classList.remove('is-loading');
            button.removeAttribute('aria-busy');
            const label = button.querySelector('[data-submit-label]');
            if (label && button.dataset.defaultLabel) {
                label.textContent = button.dataset.defaultLabel;
            }
        });
    });
})();
