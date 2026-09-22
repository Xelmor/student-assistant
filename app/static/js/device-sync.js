(() => {
  const pairingInput = document.querySelector('[data-pairing-code]');
  if (pairingInput) {
    const formatCode = () => {
      const digits = pairingInput.value.replace(/\D/g, '').slice(0, 6);
      pairingInput.value = digits.length > 3 ? `${digits.slice(0, 3)} ${digits.slice(3)}` : digits;
    };
    pairingInput.addEventListener('input', formatCode);
    pairingInput.addEventListener('paste', () => window.setTimeout(formatCode, 0));
    formatCode();
  }

  const recoveryInput = document.querySelector('[data-recovery-input]');
  if (recoveryInput) {
    recoveryInput.addEventListener('input', () => {
      recoveryInput.value = recoveryInput.value.toUpperCase().replace(/[^A-Z0-9-]/g, '');
    });
  }

  if (window.location.pathname === '/link-device' && window.location.search) {
    window.history.replaceState({}, document.title, '/link-device');
  }

  const recoveryKey = document.querySelector('[data-recovery-key]');
  const copyButton = document.querySelector('[data-copy-recovery]');
  const downloadButton = document.querySelector('[data-download-recovery]');
  if (recoveryKey && copyButton) {
    copyButton.addEventListener('click', async () => {
      await navigator.clipboard.writeText(recoveryKey.textContent.trim());
      copyButton.textContent = 'Скопировано';
    });
  }
  if (recoveryKey && downloadButton) {
    downloadButton.addEventListener('click', () => {
      const content = `Student Assistant — ключ восстановления\n\n${recoveryKey.textContent.trim()}\n\nХраните ключ в надёжном месте.`;
      const link = document.createElement('a');
      link.href = URL.createObjectURL(new Blob([content], { type: 'text/plain;charset=utf-8' }));
      link.download = 'student-assistant-recovery-key.txt';
      link.click();
      URL.revokeObjectURL(link.href);
    });
  }

  document.addEventListener('submit', (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.matches('[data-device-confirm]')) return;
    if (form.dataset.deviceConfirmed === 'true') {
      delete form.dataset.deviceConfirmed;
      return;
    }
    event.preventDefault();
    const confirmAction = () => {
      const currentConfirmation = form.querySelector('input[name="confirm_current"]');
      if (currentConfirmation) currentConfirmation.value = 'ОТКЛЮЧИТЬ';
      form.dataset.deviceConfirmed = 'true';
      form.requestSubmit(event.submitter || undefined);
    };
    const options = {
      title: form.dataset.deviceConfirmTitle || 'Подтвердить действие?',
      description: form.dataset.deviceConfirmDescription || 'Проверьте действие перед продолжением.',
      confirmLabel: form.dataset.deviceConfirmLabel || 'Подтвердить',
      onConfirm: confirmAction,
      trigger: event.submitter,
    };
    if (typeof window.requestConfirmation === 'function') {
      window.requestConfirmation(options);
    } else if (window.confirm(`${options.title}\n\n${options.description}`)) {
      confirmAction();
    }
  });

  const openButton = document.getElementById('profileConnectDevice');
  const modal = document.getElementById('deviceLinkModal');
  if (!openButton || !modal) return;

  const closeButtons = modal.querySelectorAll('[data-device-modal-close]');
  const loading = modal.querySelector('[data-device-link-loading]');
  const content = modal.querySelector('[data-device-link-content]');
  const error = modal.querySelector('[data-device-link-error]');
  const code = modal.querySelector('[data-device-link-code]');
  const qr = modal.querySelector('[data-device-link-qr]');
  const countdown = modal.querySelector('[data-device-link-countdown]');
  let timer = null;

  const closeModal = () => {
    modal.hidden = true;
    document.body.classList.remove('device-modal-open');
    openButton.focus();
    if (timer) window.clearInterval(timer);
  };
  closeButtons.forEach((button) => button.addEventListener('click', closeModal));
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && !modal.hidden) closeModal();
  });

  openButton.addEventListener('click', async () => {
    modal.hidden = false;
    document.body.classList.add('device-modal-open');
    loading.hidden = false;
    content.hidden = true;
    error.hidden = true;
    try {
      const csrf = document.querySelector('input[name="csrf_token"]')?.value || '';
      const endpoint = openButton.dataset.linkSessionUrl;
      if (!endpoint) throw new Error('Адрес подключения не настроен. Обновите страницу.');
      const body = new FormData();
      body.append('csrf_token', csrf);
      const response = await fetch(endpoint, {
        method: 'POST',
        body,
        credentials: 'same-origin',
        headers: { Accept: 'application/json' },
      });
      const contentType = response.headers.get('content-type') || '';
      const isJson = contentType.toLowerCase().includes('application/json');
      if (!response.ok) {
        let message = `Сервер вернул ошибку ${response.status}.`;
        if (isJson) {
          const problem = await response.json();
          message = problem.error || problem.detail || message;
        }
        throw new Error(message);
      }
      if (!isJson) {
        throw new Error('Сервер вернул неожиданный формат ответа. Обновите страницу и попробуйте снова.');
      }
      const payload = await response.json();
      if (!payload.code || !payload.qr_data_uri || !payload.link_url) {
        throw new Error('Ответ сервера не содержит данных для подключения.');
      }
      code.textContent = payload.formatted_code;
      qr.src = payload.qr_data_uri;
      loading.hidden = true;
      content.hidden = false;
      const expiresAt = Date.now() + (payload.expires_in_seconds * 1000);
      const tick = () => {
        const seconds = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
        countdown.textContent = seconds ? `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}` : 'Код истёк';
        if (!seconds && timer) window.clearInterval(timer);
      };
      tick();
      timer = window.setInterval(tick, 1000);
    } catch (requestError) {
      loading.hidden = true;
      error.hidden = false;
      error.textContent = requestError.message;
    }
  });
})();
