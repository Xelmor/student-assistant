(() => {
    const form = document.getElementById('profileLogoutForm');
    if (!form) return;

    form.addEventListener('submit', (event) => {
        event.preventDefault();
        const title = 'Выйти из Student Assistant?';
        const submit = () => HTMLFormElement.prototype.submit.call(form);
        const opened = window.requestConfirmation?.({
            title,
            description: 'Задачи, расписание и заметки сохранятся. Автоматический вход на этом устройстве будет отключён.',
            confirmLabel: 'Выйти',
            trigger: event.submitter,
            onConfirm: submit,
        });
        if (!opened && window.confirm(title)) submit();
    });
})();
