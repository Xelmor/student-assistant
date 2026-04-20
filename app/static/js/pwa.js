(() => {
  const installSheet = document.getElementById('installSheet');
  const installAction = document.getElementById('installAction');
  const installLater = document.getElementById('installLater');
  const installClose = document.getElementById('installClose');
  const installText = document.getElementById('installText');
  const installHint = document.getElementById('installHint');
  const installDismissKey = 'student-assistant-install-dismissed';
  const isStandalone = window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone === true;
  const userAgent = window.navigator.userAgent.toLowerCase();
  const isIos = /iphone|ipad|ipod/.test(userAgent);
  const isSafari = isIos && /safari/.test(userAgent) && !/crios|fxios|edgios/.test(userAgent);
  let deferredPrompt = null;

  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/service-worker.js?v=20260420-mobilequick').catch(() => {});
    });
  }

  if (!installSheet || isStandalone || window.localStorage.getItem(installDismissKey) === 'true') {
    return;
  }

  const openSheet = () => {
    installSheet.hidden = false;
    requestAnimationFrame(() => installSheet.classList.add('is-visible'));
  };

  const closeSheet = (remember = false) => {
    installSheet.classList.remove('is-visible');
    window.setTimeout(() => {
      installSheet.hidden = true;
    }, 220);

    if (remember) {
      window.localStorage.setItem(installDismissKey, 'true');
    }
  };

  window.addEventListener('beforeinstallprompt', (event) => {
    event.preventDefault();
    deferredPrompt = event;
    installText.textContent = 'Добавь сайт на экран «Домой» и открывай его как отдельное приложение.';
    installHint.hidden = true;
    installAction.hidden = false;
    openSheet();
  });

  if (isSafari) {
    installText.textContent = 'На iPhone сайт можно добавить на экран «Домой» и открывать почти как обычное приложение.';
    installHint.hidden = false;
    installAction.textContent = 'Понятно';
    openSheet();
  }

  installAction?.addEventListener('click', async () => {
    if (deferredPrompt) {
      deferredPrompt.prompt();
      try {
        await deferredPrompt.userChoice;
      } catch (_) {
      }
      deferredPrompt = null;
      closeSheet(true);
      return;
    }

    closeSheet(true);
  });

  installLater?.addEventListener('click', () => closeSheet(true));
  installClose?.addEventListener('click', () => closeSheet(true));
})();
