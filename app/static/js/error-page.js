(() => {
    document.querySelector('[data-error-back]')?.addEventListener('click', (event) => {
        const button = event.currentTarget;
        const fallbackHref = button.dataset.fallbackHref || '/';
        const referrer = document.referrer;
        let canGoBack = window.history.length > 1;

        if (referrer) {
            try {
                canGoBack = new URL(referrer).origin === window.location.origin;
            } catch (_) {
                canGoBack = false;
            }
        }

        if (canGoBack) {
            window.history.back();
            return;
        }
        window.location.assign(fallbackHref);
    });

    document.querySelector('[data-error-reload]')?.addEventListener('click', () => {
        window.location.reload();
    });
})();
