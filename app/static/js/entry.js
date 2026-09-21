(() => {
    const root = document.getElementById('entryExperience');
    if (!root || root.dataset.initialized === 'true') return;
    root.dataset.initialized = 'true';

    const setup = document.getElementById('entrySetup');
    const form = document.getElementById('entryStartForm');
    const nameInput = document.getElementById('entryDisplayName');
    const nameError = document.getElementById('entryNameError');
    const progress = document.getElementById('entrySetupProgress');
    const nextButton = document.getElementById('entryNextStep');
    const backButton = document.getElementById('entryBackStep');
    const unitInput = document.getElementById('entryScheduleUnit');
    const launch = document.getElementById('entryLaunch');
    const launchName = document.getElementById('entryLaunchName');
    const hero = root.querySelector('.entry-v3-hero');
    const particles = document.getElementById('entryParticles');
    const productStage = document.getElementById('entryProductStage');
    const productFrame = document.getElementById('entryProductFrame');
    const tasksDemo = root.querySelector('[data-tasks-demo]');
    const scheduleDemo = root.querySelector('[data-schedule-demo]');
    const telegramDemo = root.querySelector('[data-telegram-demo]');
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const finePointer = window.matchMedia('(hover: hover) and (pointer: fine)').matches;
    let submitTimer = null;

    if (particles && !particles.childElementCount) {
        const fragment = document.createDocumentFragment();
        for (let index = 0; index < 28; index += 1) {
            const particle = document.createElement('i');
            const size = 1 + (index % 3) * 0.55;
            particle.style.setProperty('--particle-x', `${(index * 37 + 11) % 98}%`);
            particle.style.setProperty('--particle-y', `${(index * 53 + 7) % 94}%`);
            particle.style.setProperty('--particle-size', `${size.toFixed(2)}px`);
            particle.style.setProperty('--particle-alpha', (0.24 + (index % 5) * 0.1).toFixed(2));
            particle.style.setProperty('--particle-duration', `${15 + (index % 10)}s`);
            particle.style.setProperty('--particle-delay', `${-(index % 8) * 1.7}s`);
            particle.style.setProperty('--particle-drift-x', `${(index % 2 ? 1 : -1) * (5 + index % 7)}px`);
            particle.style.setProperty('--particle-drift-y', `${-7 - index % 9}px`);
            if (index % 3 === 0) particle.classList.add('is-moving');
            fragment.appendChild(particle);
        }
        particles.appendChild(fragment);
    }

    const setStep = (step) => {
        root.querySelectorAll('[data-entry-step]').forEach((section) => {
            const active = Number(section.dataset.entryStep) === step;
            section.classList.toggle('is-active', active);
            section.setAttribute('aria-hidden', String(!active));
        });
        if (progress) progress.style.width = step === 1 ? '50%' : '100%';
        window.setTimeout(() => {
            if (step === 1) nameInput?.focus();
            else root.querySelector('[data-entry-step="2"] input:not([type="hidden"])')?.focus();
        }, reduceMotion ? 0 : 180);
    };

    const openSetup = () => {
        setup?.classList.add('is-open');
        setup?.setAttribute('aria-hidden', 'false');
        document.body.classList.add('entry-modal-open');
        const hasError = Boolean(root.dataset.startError);
        setStep(hasError ? 2 : 1);
    };

    const closeSetup = () => {
        if (submitTimer) return;
        setup?.classList.remove('is-open');
        setup?.setAttribute('aria-hidden', 'true');
        document.body.classList.remove('entry-modal-open');
        if (window.location.hash === '#start') {
            window.history.replaceState({}, '', window.location.pathname);
        }
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

    nextButton?.addEventListener('click', () => {
        if (validateName()) setStep(2);
    });
    backButton?.addEventListener('click', () => setStep(1));
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
        submitTimer = window.setTimeout(() => HTMLFormElement.prototype.submit.call(form), 950);
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && setup?.classList.contains('is-open')) closeSetup();
    });

    const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add('is-in');
                observer.unobserve(entry.target);
            }
        });
    }, {threshold: 0.18, rootMargin: '0px 0px -6%'});
    root.querySelectorAll('.observe-reveal').forEach((item) => observer.observe(item));

    if (tasksDemo) {
        const tasksStepClasses = [
            'is-step-dashboard',
            'is-step-tasks',
            'is-step-form',
            'is-step-fill',
            'is-step-add',
            'is-step-create',
            'is-step-complete',
            'is-step-toast',
        ];
        const setTasksStep = (step) => {
            tasksDemo.classList.remove(...tasksStepClasses);
            if (step) tasksDemo.classList.add(`is-step-${step}`);
        };
        const showTasksFinalState = () => {
            tasksDemo.classList.add(
                'is-in',
                'is-form-visible',
                'is-form-filled',
                'is-created',
                'is-details-visible',
                'is-complete',
                'is-toast-visible',
            );
        };

        if (reduceMotion) {
            showTasksFinalState();
        } else {
            const tasksObserver = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (!entry.isIntersecting || tasksDemo.dataset.demoPlayed === 'true') return;

                    tasksDemo.dataset.demoPlayed = 'true';
                    tasksDemo.classList.add('is-in');
                    setTasksStep('dashboard');
                    tasksObserver.unobserve(tasksDemo);

                    window.setTimeout(() => setTasksStep('tasks'), 800);
                    window.setTimeout(() => {
                        tasksDemo.classList.add('is-form-visible');
                        setTasksStep('form');
                    }, 1780);
                    window.setTimeout(() => {
                        tasksDemo.classList.add('is-form-filled');
                        setTasksStep('fill');
                    }, 2550);
                    window.setTimeout(() => {
                        tasksDemo.classList.add('is-add-pressed');
                        setTasksStep('add');
                    }, 3650);
                    window.setTimeout(() => {
                        tasksDemo.classList.add('is-created');
                        setTasksStep('create');
                    }, 4080);
                    window.setTimeout(() => tasksDemo.classList.add('is-details-visible'), 4250);
                    window.setTimeout(() => {
                        tasksDemo.classList.add('is-complete');
                        setTasksStep('complete');
                    }, 4780);
                    window.setTimeout(() => {
                        tasksDemo.classList.add('is-toast-visible');
                        setTasksStep('toast');
                    }, 5220);
                    window.setTimeout(() => setTasksStep(null), 5800);
                });
            }, {threshold: 0.3, rootMargin: '0px 0px -8%'});

            tasksObserver.observe(tasksDemo);
        }
    }

    if (tasksDemo && finePointer && !reduceMotion) {
        const tasksStage = tasksDemo.querySelector('.entry-tasks-v2__stage');
        let tasksFrame = null;
        let tasksX = 0;
        let tasksY = 0;
        let spotlightFrame = null;
        let spotlightX = 0.72;
        let spotlightY = 0.44;
        let spotlightOpacity = 0.105;
        let spotlightTargetX = spotlightX;
        let spotlightTargetY = spotlightY;
        let spotlightTargetOpacity = spotlightOpacity;

        const renderTasksSpotlight = () => {
            spotlightX += (spotlightTargetX - spotlightX) * 0.12;
            spotlightY += (spotlightTargetY - spotlightY) * 0.12;
            spotlightOpacity += (spotlightTargetOpacity - spotlightOpacity) * 0.1;
            tasksDemo.style.setProperty('--tasks-spot-x', `${(spotlightX * 100).toFixed(2)}%`);
            tasksDemo.style.setProperty('--tasks-spot-y', `${(spotlightY * 100).toFixed(2)}%`);
            tasksDemo.style.setProperty('--tasks-spot-opacity', spotlightOpacity.toFixed(3));

            const unsettled = Math.abs(spotlightTargetX - spotlightX) > 0.001
                || Math.abs(spotlightTargetY - spotlightY) > 0.001
                || Math.abs(spotlightTargetOpacity - spotlightOpacity) > 0.001;
            spotlightFrame = unsettled ? requestAnimationFrame(renderTasksSpotlight) : null;
        };

        const queueTasksSpotlight = () => {
            if (!spotlightFrame) spotlightFrame = requestAnimationFrame(renderTasksSpotlight);
        };

        const renderTasksDepth = () => {
            tasksStage?.style.setProperty('--tasks-panel-x', `${(tasksX * 7).toFixed(2)}px`);
            tasksStage?.style.setProperty('--tasks-panel-y', `${(tasksY * 5).toFixed(2)}px`);
            tasksStage?.style.setProperty('--tasks-tilt-x', `${(-tasksY * 1.4).toFixed(2)}deg`);
            tasksStage?.style.setProperty('--tasks-tilt-y', `${(tasksX * 1.4).toFixed(2)}deg`);
            tasksStage?.style.setProperty('--tasks-form-x', `${(-tasksX * 9).toFixed(2)}px`);
            tasksStage?.style.setProperty('--tasks-form-y', `${(-tasksY * 7).toFixed(2)}px`);
            tasksStage?.style.setProperty('--tasks-toast-x', `${(-tasksX * 11).toFixed(2)}px`);
            tasksStage?.style.setProperty('--tasks-toast-y', `${(-tasksY * 8).toFixed(2)}px`);
            tasksFrame = null;
        };

        tasksStage?.addEventListener('pointermove', (event) => {
            const rect = tasksStage.getBoundingClientRect();
            tasksX = (event.clientX - rect.left) / rect.width - 0.5;
            tasksY = (event.clientY - rect.top) / rect.height - 0.5;
            if (!tasksFrame) tasksFrame = requestAnimationFrame(renderTasksDepth);
        });
        tasksStage?.addEventListener('pointerleave', () => {
            if (tasksFrame) cancelAnimationFrame(tasksFrame);
            tasksFrame = null;
            tasksX = 0;
            tasksY = 0;
            renderTasksDepth();
        });

        tasksDemo.addEventListener('pointermove', (event) => {
            const rect = tasksDemo.getBoundingClientRect();
            spotlightTargetX = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
            spotlightTargetY = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
            spotlightTargetOpacity = 0.16;
            queueTasksSpotlight();
        });
        tasksDemo.addEventListener('pointerleave', () => {
            spotlightTargetX = 0.72;
            spotlightTargetY = 0.44;
            spotlightTargetOpacity = 0.105;
            queueTasksSpotlight();
        });
    }

    if (scheduleDemo) {
        const showScheduleFinalState = () => {
            scheduleDemo.classList.add(
                'is-schedule-in',
                'is-schedule-cards',
                'is-schedule-day',
                'is-schedule-line',
                'is-schedule-next-shown',
                'is-schedule-today',
                'is-schedule-copy',
                'is-schedule-timeline',
                'is-schedule-space-note',
                'is-schedule-settled',
            );
        };

        if (reduceMotion) {
            showScheduleFinalState();
        } else {
            const scheduleObserver = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (!entry.isIntersecting || scheduleDemo.dataset.demoPlayed === 'true') return;

                    scheduleDemo.dataset.demoPlayed = 'true';
                    scheduleDemo.classList.add('is-schedule-in');
                    scheduleObserver.unobserve(scheduleDemo);

                    window.setTimeout(() => scheduleDemo.classList.add('is-schedule-cards'), 900);
                    window.setTimeout(() => scheduleDemo.classList.add('is-schedule-day'), 2050);
                    window.setTimeout(() => scheduleDemo.classList.add('is-schedule-line'), 2500);
                    window.setTimeout(() => {
                        scheduleDemo.classList.add('is-schedule-active', 'is-schedule-next-shown', 'is-schedule-today');
                    }, 3500);
                    window.setTimeout(() => {
                        scheduleDemo.classList.remove('is-schedule-active');
                        scheduleDemo.classList.add('is-schedule-copy');
                    }, 4500);
                    window.setTimeout(() => scheduleDemo.classList.add('is-schedule-timeline'), 5250);
                    window.setTimeout(() => scheduleDemo.classList.add('is-schedule-space-note'), 6000);
                    window.setTimeout(() => scheduleDemo.classList.add('is-schedule-settled'), 6900);
                });
            }, {threshold: 0.28, rootMargin: '0px 0px -8%'});

            scheduleObserver.observe(scheduleDemo);
        }
    }

    if (scheduleDemo && finePointer && !reduceMotion) {
        const scheduleBoard = scheduleDemo.querySelector('.entry-schedule-v2__board');
        let scheduleFrame = null;
        let scheduleX = 0;
        let scheduleY = 0;
        let scheduleSpotFrame = null;
        let scheduleSpotX = 0.34;
        let scheduleSpotY = 0.46;
        let scheduleSpotOpacity = 0.1;
        let scheduleTargetX = scheduleSpotX;
        let scheduleTargetY = scheduleSpotY;
        let scheduleTargetOpacity = scheduleSpotOpacity;

        const renderScheduleDepth = () => {
            scheduleDemo.style.setProperty('--schedule-shift-x', `${(scheduleX * 7).toFixed(2)}px`);
            scheduleDemo.style.setProperty('--schedule-shift-y', `${(scheduleY * 5).toFixed(2)}px`);
            scheduleFrame = null;
        };

        const renderScheduleSpotlight = () => {
            scheduleSpotX += (scheduleTargetX - scheduleSpotX) * 0.12;
            scheduleSpotY += (scheduleTargetY - scheduleSpotY) * 0.12;
            scheduleSpotOpacity += (scheduleTargetOpacity - scheduleSpotOpacity) * 0.1;
            scheduleDemo.style.setProperty('--schedule-spot-x', `${(scheduleSpotX * 100).toFixed(2)}%`);
            scheduleDemo.style.setProperty('--schedule-spot-y', `${(scheduleSpotY * 100).toFixed(2)}%`);
            scheduleDemo.style.setProperty('--schedule-spot-opacity', scheduleSpotOpacity.toFixed(3));

            const unsettled = Math.abs(scheduleTargetX - scheduleSpotX) > 0.001
                || Math.abs(scheduleTargetY - scheduleSpotY) > 0.001
                || Math.abs(scheduleTargetOpacity - scheduleSpotOpacity) > 0.001;
            scheduleSpotFrame = unsettled ? requestAnimationFrame(renderScheduleSpotlight) : null;
        };

        const queueScheduleSpotlight = () => {
            if (!scheduleSpotFrame) scheduleSpotFrame = requestAnimationFrame(renderScheduleSpotlight);
        };

        scheduleDemo.addEventListener('pointermove', (event) => {
            const sectionRect = scheduleDemo.getBoundingClientRect();
            scheduleTargetX = Math.min(1, Math.max(0, (event.clientX - sectionRect.left) / sectionRect.width));
            scheduleTargetY = Math.min(1, Math.max(0, (event.clientY - sectionRect.top) / sectionRect.height));
            scheduleTargetOpacity = 0.15;
            queueScheduleSpotlight();

            if (!scheduleBoard) return;
            const boardRect = scheduleBoard.getBoundingClientRect();
            scheduleX = Math.min(0.5, Math.max(-0.5, (event.clientX - boardRect.left) / boardRect.width - 0.5));
            scheduleY = Math.min(0.5, Math.max(-0.5, (event.clientY - boardRect.top) / boardRect.height - 0.5));
            if (!scheduleFrame) scheduleFrame = requestAnimationFrame(renderScheduleDepth);
        });
        scheduleDemo.addEventListener('pointerleave', () => {
            scheduleTargetX = 0.34;
            scheduleTargetY = 0.46;
            scheduleTargetOpacity = 0.1;
            queueScheduleSpotlight();
            scheduleX = 0;
            scheduleY = 0;
            if (scheduleFrame) cancelAnimationFrame(scheduleFrame);
            scheduleFrame = null;
            renderScheduleDepth();
        });
    }

    if (telegramDemo) {
        const telegramStepClasses = [
            'is-telegram-in',
            'is-telegram-today',
            'is-telegram-typing',
            'is-telegram-schedule',
            'is-telegram-deadline',
            'is-telegram-done-command',
            'is-telegram-done-confirm',
            'is-telegram-synced',
            'is-telegram-settled',
        ];
        const showTelegramFinalState = () => telegramDemo.classList.add(...telegramStepClasses);

        if (reduceMotion) {
            showTelegramFinalState();
        } else {
            const telegramObserver = new IntersectionObserver((entries) => {
                entries.forEach((entry) => {
                    if (!entry.isIntersecting || telegramDemo.dataset.demoPlayed === 'true') return;

                    telegramDemo.dataset.demoPlayed = 'true';
                    telegramDemo.classList.add('is-telegram-in');
                    telegramObserver.unobserve(telegramDemo);

                    window.setTimeout(() => telegramDemo.classList.add('is-telegram-today'), 800);
                    window.setTimeout(() => telegramDemo.classList.add('is-telegram-typing'), 1500);
                    window.setTimeout(() => telegramDemo.classList.add('is-telegram-schedule'), 2050);
                    window.setTimeout(() => telegramDemo.classList.add('is-telegram-deadline'), 3250);
                    window.setTimeout(() => telegramDemo.classList.add('is-telegram-done-command'), 4500);
                    window.setTimeout(() => telegramDemo.classList.add('is-telegram-done-confirm'), 5550);
                    window.setTimeout(() => telegramDemo.classList.add('is-telegram-synced'), 6600);
                    window.setTimeout(() => telegramDemo.classList.add('is-telegram-settled'), 7150);
                });
            }, {threshold: 0.26, rootMargin: '0px 0px -7%'});

            telegramObserver.observe(telegramDemo);
        }
    }

    if (telegramDemo && finePointer && !reduceMotion) {
        const telegramStage = telegramDemo.querySelector('.entry-telegram-v2__stage');
        let telegramFrame = null;
        let telegramSpotFrame = null;
        let telegramX = 0;
        let telegramY = 0;
        let telegramSpotX = 0.72;
        let telegramSpotY = 0.48;
        let telegramSpotOpacity = 0.115;
        let telegramTargetX = telegramSpotX;
        let telegramTargetY = telegramSpotY;
        let telegramTargetOpacity = telegramSpotOpacity;

        const renderTelegramDepth = () => {
            telegramDemo.style.setProperty('--telegram-shift-x', `${(telegramX * 5).toFixed(2)}px`);
            telegramDemo.style.setProperty('--telegram-shift-y', `${(telegramY * 4).toFixed(2)}px`);
            telegramFrame = null;
        };
        const renderTelegramSpotlight = () => {
            telegramSpotX += (telegramTargetX - telegramSpotX) * 0.12;
            telegramSpotY += (telegramTargetY - telegramSpotY) * 0.12;
            telegramSpotOpacity += (telegramTargetOpacity - telegramSpotOpacity) * 0.1;
            telegramDemo.style.setProperty('--telegram-spot-x', `${(telegramSpotX * 100).toFixed(2)}%`);
            telegramDemo.style.setProperty('--telegram-spot-y', `${(telegramSpotY * 100).toFixed(2)}%`);
            telegramDemo.style.setProperty('--telegram-spot-opacity', telegramSpotOpacity.toFixed(3));
            const unsettled = Math.abs(telegramTargetX - telegramSpotX) > 0.001
                || Math.abs(telegramTargetY - telegramSpotY) > 0.001
                || Math.abs(telegramTargetOpacity - telegramSpotOpacity) > 0.001;
            telegramSpotFrame = unsettled ? requestAnimationFrame(renderTelegramSpotlight) : null;
        };
        const queueTelegramSpotlight = () => {
            if (!telegramSpotFrame) telegramSpotFrame = requestAnimationFrame(renderTelegramSpotlight);
        };

        telegramDemo.addEventListener('pointermove', (event) => {
            const rect = telegramDemo.getBoundingClientRect();
            telegramTargetX = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
            telegramTargetY = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
            telegramTargetOpacity = 0.16;
            queueTelegramSpotlight();
            if (!telegramStage) return;
            const stageRect = telegramStage.getBoundingClientRect();
            telegramX = Math.min(0.5, Math.max(-0.5, (event.clientX - stageRect.left) / stageRect.width - 0.5));
            telegramY = Math.min(0.5, Math.max(-0.5, (event.clientY - stageRect.top) / stageRect.height - 0.5));
            if (!telegramFrame) telegramFrame = requestAnimationFrame(renderTelegramDepth);
        });
        telegramDemo.addEventListener('pointerleave', () => {
            telegramTargetX = 0.72;
            telegramTargetY = 0.48;
            telegramTargetOpacity = 0.115;
            queueTelegramSpotlight();
            telegramX = 0;
            telegramY = 0;
            if (telegramFrame) cancelAnimationFrame(telegramFrame);
            telegramFrame = null;
            renderTelegramDepth();
        });
    }

    const clock = document.getElementById('entryClock');
    const updateClock = () => {
        if (!clock) return;
        clock.textContent = new Intl.DateTimeFormat('ru-RU', {
            hour: '2-digit',
            minute: '2-digit',
        }).format(new Date());
    };
    updateClock();
    window.setInterval(updateClock, 30000);

    if (!reduceMotion) {
        const counters = root.querySelectorAll('.entry-v3-metrics article > b');
        counters.forEach((counter) => {
            const target = Number.parseInt(counter.textContent || '0', 10);
            if (!Number.isFinite(target)) return;
            counter.textContent = '0';
            window.setTimeout(() => {
                const startedAt = performance.now();
                const duration = 620;
                const tick = (now) => {
                    const progressValue = Math.min((now - startedAt) / duration, 1);
                    const eased = 1 - Math.pow(1 - progressValue, 3);
                    counter.textContent = String(Math.round(target * eased));
                    if (progressValue < 1) requestAnimationFrame(tick);
                };
                requestAnimationFrame(tick);
            }, 1080);
        });
    }

    if (hero && finePointer && !reduceMotion) {
        let spotlightFrame = null;
        let pointerX = 0;
        let pointerY = 0;
        const renderSpotlight = () => {
            const rect = hero.getBoundingClientRect();
            root.style.setProperty('--spotlight-x', `${pointerX - rect.left}px`);
            root.style.setProperty('--spotlight-y', `${pointerY - rect.top}px`);
            spotlightFrame = null;
        };
        hero.addEventListener('pointermove', (event) => {
            pointerX = event.clientX;
            pointerY = event.clientY;
            root.classList.add('is-pointer-active');
            if (!spotlightFrame) spotlightFrame = requestAnimationFrame(renderSpotlight);
        });
        hero.addEventListener('pointerleave', () => {
            root.classList.remove('is-pointer-active');
            if (spotlightFrame) cancelAnimationFrame(spotlightFrame);
            spotlightFrame = null;
        });
    }

    if (productStage && productFrame && finePointer && !reduceMotion) {
        let frame = null;
        let x = 0;
        let y = 0;
        const renderTilt = () => {
            const tx = (x * 8).toFixed(1);
            const ty = (y * 6).toFixed(1);
            const tiltX = (-y * 3).toFixed(2);
            const tiltY = (x * 3).toFixed(2);
            productFrame.style.setProperty('--parallax-x', `${tx}px`);
            productFrame.style.setProperty('--parallax-y', `${ty}px`);
            productFrame.style.setProperty('--tilt-x', `${tiltX}deg`);
            productFrame.style.setProperty('--tilt-y', `${tiltY}deg`);
            frame = null;
        };
        productStage.addEventListener('pointermove', (event) => {
            const rect = productStage.getBoundingClientRect();
            x = (event.clientX - rect.left) / rect.width - 0.5;
            y = (event.clientY - rect.top) / rect.height - 0.5;
            if (!frame) frame = requestAnimationFrame(renderTilt);
        });
        productStage.addEventListener('pointerleave', () => {
            if (frame) cancelAnimationFrame(frame);
            frame = null;
            productFrame.style.setProperty('--parallax-x', '0px');
            productFrame.style.setProperty('--parallax-y', '0px');
            productFrame.style.setProperty('--tilt-x', '0deg');
            productFrame.style.setProperty('--tilt-y', '0deg');
        });
    }

    document.querySelectorAll('.public-topbar a[href^="#"], .entry-v3 a[href^="#"]:not([data-entry-open])').forEach((anchor) => {
        anchor.addEventListener('click', (event) => {
            const targetId = anchor.getAttribute('href');
            if (!targetId || targetId === '#') return;
            const target = document.querySelector(targetId);
            if (!target) return;
            event.preventDefault();
            target.scrollIntoView({behavior: reduceMotion ? 'auto' : 'smooth', block: 'start'});
        });
    });

    if (root.dataset.openStart === 'true' || window.location.hash === '#start') openSetup();
})();
