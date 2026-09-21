(() => {
    const root = document.getElementById('entryExperience');
    if (!root || root.dataset.initialized === 'true') return;
    root.dataset.initialized = 'true';

    const setup = document.getElementById('entrySetup');
    const form = document.getElementById('entryStartForm');
    const nameInput = document.getElementById('entryDisplayName');
    const nameError = document.getElementById('entryNameError');
    const progress = document.getElementById('entrySetupProgress');
    const next = document.getElementById('entryNextStep');
    const back = document.getElementById('entryBackStep');
    const unitInput = document.getElementById('entryScheduleUnit');
    const launch = document.getElementById('entryLaunch');
    const launchName = document.getElementById('entryLaunchName');
    const particles = document.getElementById('entryParticles');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    let activeStep = 1;
    let submitTimer = null;

    const createParticles = () => {
        if (!particles) return;
        const count = window.innerWidth < 600 ? 22 : 42;
        const fragment = document.createDocumentFragment();
        for (let index = 0; index < count; index += 1) {
            const dot = document.createElement('i');
            dot.className = 'entry-particle';
            dot.style.left = `${(index * 47 + 13) % 100}%`;
            dot.style.top = `${(index * 71 + 9) % 100}%`;
            dot.style.setProperty('--size', `${1 + (index % 3) * 0.6}px`);
            dot.style.setProperty('--alpha', `${0.22 + (index % 5) * 0.09}`);
            dot.style.setProperty('--duration', `${3.6 + (index % 7) * 0.55}s`);
            dot.style.setProperty('--delay', `${-((index % 9) * 0.4)}s`);
            fragment.appendChild(dot);
        }
        particles.replaceChildren(fragment);
    };

    const setStep = (step) => {
        activeStep = step;
        root.querySelectorAll('[data-entry-step]').forEach((section) => {
            const selected = Number(section.dataset.entryStep) === step;
            section.classList.toggle('is-active', selected);
            section.setAttribute('aria-hidden', String(!selected));
        });
        if (progress) progress.style.width = step === 1 ? '50%' : '100%';
        window.setTimeout(() => {
            if (step === 1) nameInput?.focus();
            else root.querySelector('[data-entry-step="2"] input:not([type="hidden"])')?.focus();
        }, reduceMotion ? 0 : 220);
    };

    const openSetup = () => {
        root.classList.add('is-configuring');
        setup?.classList.add('is-open');
        setup?.setAttribute('aria-hidden', 'false');
        document.body.classList.add('entry-modal-open');
        setStep(root.dataset.startError ? 2 : 1);
    };

    const closeSetup = () => {
        if (submitTimer) return;
        root.classList.remove('is-configuring');
        setup?.classList.remove('is-open');
        setup?.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('entry-modal-open');
        window.history.replaceState({}, '', window.location.pathname);
    };

    const validateName = () => {
        const value = nameInput?.value.trim() || '';
        if (!value) {
            if (nameError) nameError.textContent = 'Напиши имя, чтобы продолжить.';
            nameInput?.focus();
            return false;
        }
        if (value.length > 40) {
            if (nameError) nameError.textContent = 'Имя должно быть короче 40 символов.';
            nameInput?.focus();
            return false;
        }
        if (nameError) nameError.textContent = '';
        return true;
    };

    root.querySelectorAll('[data-entry-open]').forEach((control) => {
        control.addEventListener('click', (event) => {
            event.preventDefault();
            window.history.replaceState({}, '', `${window.location.pathname}#start`);
            openSetup();
        });
    });

    root.querySelectorAll('[data-entry-close]').forEach((control) => {
        control.addEventListener('click', closeSetup);
    });

    next?.addEventListener('click', () => {
        if (validateName()) setStep(2);
    });
    back?.addEventListener('click', () => setStep(1));
    nameInput?.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') {
            event.preventDefault();
            if (validateName()) setStep(2);
        }
    });

    root.querySelectorAll('[data-unit]').forEach((button) => {
        button.addEventListener('click', () => {
            const value = button.dataset.unit || 'pair';
            if (unitInput) unitInput.value = value;
            root.querySelectorAll('[data-unit]').forEach((item) => {
                item.classList.toggle('is-selected', item === button);
            });
        });
    });

    form?.addEventListener('submit', (event) => {
        if (!validateName()) {
            event.preventDefault();
            setStep(1);
            return;
        }
        if (reduceMotion) return;
        event.preventDefault();
        const displayName = nameInput?.value.trim() || 'студент';
        if (launchName) launchName.textContent = displayName;
        setup?.classList.remove('is-open');
        launch?.classList.add('is-active');
        launch?.setAttribute('aria-hidden', 'false');
        submitTimer = window.setTimeout(() => HTMLFormElement.prototype.submit.call(form), 900);
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && setup?.classList.contains('is-open')) closeSetup();
    });

    if (finePointer && !reduceMotion) {
        const layers = root.querySelectorAll('[data-entry-layer]');
        let frame = null;
        let px = 0;
        let py = 0;
        root.addEventListener('pointermove', (event) => {
            const rect = root.getBoundingClientRect();
            px = (event.clientX - rect.left) / rect.width - 0.5;
            py = (event.clientY - rect.top) / rect.height - 0.5;
            if (frame) return;
            frame = requestAnimationFrame(() => {
                layers.forEach((layer) => {
                    const depth = Number(layer.dataset.entryLayer || 0.2);
                    layer.style.transform = `translate3d(${px * depth * 22}px, ${py * depth * 16}px, 0)`;
                });
                frame = null;
            });
        });
        root.addEventListener('pointerleave', () => {
            layers.forEach((layer) => { layer.style.transform = ''; });
        });
    }

    const clock = document.getElementById('entryClock');
    const updateClock = () => {
        if (!clock) return;
        clock.textContent = new Intl.DateTimeFormat('ru-RU', {hour:'2-digit', minute:'2-digit'}).format(new Date());
    };
    updateClock();
    window.setInterval(updateClock, 30000);

    const productWindow = document.getElementById('productWindow');
    const visual = document.getElementById('entryVisual');
    if (productWindow && visual && finePointer && !reduceMotion) {
        visual.addEventListener('pointermove', (event) => {
            const rect = visual.getBoundingClientRect();
            const x = (event.clientX - rect.left) / rect.width - 0.5;
            const y = (event.clientY - rect.top) / rect.height - 0.5;
            productWindow.style.transform = `translate(-50%,-50%) rotateY(${(-6 + x * 5).toFixed(2)}deg) rotateX(${(3 - y * 4).toFixed(2)}deg) translate3d(${(x*7).toFixed(1)}px,${(y*5).toFixed(1)}px,0)`;
        });
        visual.addEventListener('pointerleave', () => {
            productWindow.style.transform = '';
        });
    }

    createParticles();
    if (root.dataset.openStart === 'true' || window.location.hash === '#start') openSetup();
})();
