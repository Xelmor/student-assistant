(() => {
    const chat = document.getElementById('onboardingChat');
    const status = document.getElementById('onboardingChatStatus')?.dataset.status || '';

    const statusToasts = {
        completed: {
            type: 'success',
            title: 'Профиль настроен',
            description: 'Персональные настройки сохранены.',
        },
        skipped: {
            type: 'info',
            title: 'Настройка пропущена',
            description: 'К ней можно вернуться из профиля.',
        },
    };

    if (statusToasts[status]) {
        window.showToast?.({ ...statusToasts[status], duration: 4400 });
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete('onboarding_chat');
        window.history.replaceState({}, '', `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`);
    }

    if (!chat) {
        return;
    }

    const messages = chat.querySelector('#onboardingChatMessages');
    const composer = chat.querySelector('#onboardingChatComposer');
    const progress = chat.querySelector('#onboardingChatProgress');
    const progressFill = progress?.querySelector('span');
    const stepLabel = chat.querySelector('#onboardingChatStepLabel');
    const stepTitle = chat.querySelector('#onboardingChatStepTitle');
    const skipButton = chat.querySelector('#onboardingChatSkip');
    const closeButton = chat.querySelector('#onboardingChatClose');
    const completeForm = chat.querySelector('#onboardingChatCompleteForm');
    const skipForm = chat.querySelector('#onboardingChatSkipForm');
    const startButton = chat.querySelector('#onboardingChatStart');

    if (
        !messages ||
        !composer ||
        !progress ||
        !progressFill ||
        !stepLabel ||
        !stepTitle ||
        !skipButton ||
        !closeButton ||
        !completeForm ||
        !skipForm ||
        !startButton
    ) {
        console.error('Student Assistant onboarding chat could not initialize.');
        return;
    }

    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    const initialFocus = document.activeElement;
    const restartMode = chat.dataset.restart === 'true';
    let busy = false;
    let currentStepIndex = 0;
    const accentChoices = [
        {
            value: 'purple',
            label: 'Ледяной синий',
            description: 'Фирменный',
            color: '#6C8EFF',
            hover: '#82A0FF',
        },
        {
            value: 'blue',
            label: 'Синий',
            description: 'Спокойный',
            color: '#6C8EFF',
            hover: '#82A0FF',
        },
        {
            value: 'cyan',
            label: 'Голубой',
            description: 'Свежий',
            color: '#8B7CF6',
            hover: '#9E91F8',
        },
        {
            value: 'green',
            label: 'Зелёный',
            description: 'Собранный',
            color: '#55BFA3',
            hover: '#6BCAB0',
        },
        {
            value: 'orange',
            label: 'Оранжевый',
            description: 'Тёплый',
            color: '#D6A85F',
            hover: '#DFB873',
        },
        {
            value: 'pink',
            label: 'Розовый',
            description: 'Мягкий',
            color: '#D87373',
            hover: '#E18686',
        },
    ];

    const state = {
        username: chat.dataset.username || '',
        email: chat.dataset.email || '',
        displayName: chat.dataset.displayName || '',
        groupName: chat.dataset.groupName || '',
        course: chat.dataset.course || '',
        accent: window.StudentAssistantPreferences?.getSettings().accent || 'purple',
        timeFormat: window.StudentAssistantPreferences?.getSettings().timeFormat || '24',
    };

    const wait = (duration) => new Promise((resolve) => {
        window.setTimeout(resolve, reduceMotion ? 0 : duration);
    });

    const scrollMessages = () => {
        requestAnimationFrame(() => {
            messages.scrollTo({
                top: messages.scrollHeight,
                behavior: reduceMotion ? 'auto' : 'smooth',
            });
        });
    };

    const createMessage = (role, paragraphs) => {
        const article = document.createElement('article');
        article.className = `onboarding-chat__message is-${role}`;

        if (role === 'assistant') {
            const avatar = document.createElement('span');
            avatar.className = 'onboarding-chat__bubble-avatar';
            avatar.setAttribute('aria-hidden', 'true');
            avatar.textContent = 'SA';
            article.appendChild(avatar);
        }

        const bubble = document.createElement('div');
        bubble.className = 'onboarding-chat__bubble';
        paragraphs.forEach((paragraph) => {
            const text = document.createElement('p');
            text.textContent = paragraph;
            bubble.appendChild(text);
        });
        article.appendChild(bubble);
        messages.appendChild(article);
        scrollMessages();
    };

    const showTyping = async () => {
        const typing = document.createElement('article');
        typing.className = 'onboarding-chat__message is-assistant is-typing';
        typing.setAttribute('aria-label', 'Помощник печатает');
        typing.innerHTML = `
            <span class="onboarding-chat__bubble-avatar" aria-hidden="true">SA</span>
            <div class="onboarding-chat__bubble" aria-hidden="true"><i></i><i></i><i></i></div>
        `;
        messages.appendChild(typing);
        scrollMessages();
        await wait(460);
        typing.remove();
    };

    const setComposer = (...nodes) => {
        composer.replaceChildren(...nodes);
        requestAnimationFrame(() => {
            composer.querySelector('.is-selected, input, button')?.focus();
            scrollMessages();
        });
    };

    const createButton = (label, className = 'onboarding-chat__primary') => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = className;
        button.textContent = label;
        return button;
    };

    const createInputForm = ({
        label,
        placeholder,
        value = '',
        maxLength,
        inputType = 'text',
        min,
        max,
        optional = false,
        emptyError = 'Заполни поле, чтобы продолжить.',
        submitLabel = 'Дальше',
        skipLabel = 'Пропустить',
        onSubmit,
        onSkip,
    }) => {
        const form = document.createElement('form');
        form.className = 'onboarding-chat__answer-form';

        const field = document.createElement('label');
        field.className = 'onboarding-chat__field';
        const labelText = document.createElement('span');
        labelText.textContent = label;
        const input = document.createElement('input');
        input.type = inputType;
        input.placeholder = placeholder;
        input.value = value;
        if (maxLength !== undefined) input.maxLength = maxLength;
        input.autocomplete = 'off';
        input.required = !optional;
        if (min !== undefined) input.min = String(min);
        if (max !== undefined) input.max = String(max);
        const error = document.createElement('small');
        error.className = 'onboarding-chat__field-error';
        error.setAttribute('role', 'alert');
        field.append(labelText, input, error);

        const actions = document.createElement('div');
        actions.className = 'onboarding-chat__composer-actions';
        const submit = createButton(submitLabel);
        submit.type = 'submit';
        actions.appendChild(submit);
        if (onSkip) {
            const skip = createButton(skipLabel, 'onboarding-chat__secondary');
            skip.addEventListener('click', onSkip);
            actions.prepend(skip);
        }

        form.append(field, actions);
        form.addEventListener('submit', (event) => {
            event.preventDefault();
            const answer = input.value.trim();
            if (!optional && !answer) {
                error.textContent = emptyError;
                input.focus();
                return;
            }
            if (inputType === 'number' && answer) {
                const numericValue = Number(answer);
                if (
                    !Number.isInteger(numericValue) ||
                    (min !== undefined && numericValue < min) ||
                    (max !== undefined && numericValue > max)
                ) {
                    error.textContent = `Укажи число от ${min} до ${max}.`;
                    input.focus();
                    return;
                }
            }
            error.textContent = '';
            onSubmit(answer);
        });
        return form;
    };

    const createChoices = (choices, selectedValue, onSelect, columns = false) => {
        const wrap = document.createElement('div');
        wrap.className = `onboarding-chat__choices${columns ? ' has-columns' : ''}`;
        choices.forEach((choice) => {
            const button = createButton(choice.label, 'onboarding-chat__choice');
            button.dataset.value = choice.value;
            button.setAttribute('aria-pressed', String(choice.value === selectedValue));
            button.classList.toggle('is-selected', choice.value === selectedValue);
            if (choice.color) {
                const swatch = document.createElement('span');
                swatch.className = 'onboarding-chat__choice-swatch';
                swatch.style.setProperty('--choice-color', choice.color);
                button.prepend(swatch);
            }
            button.addEventListener('click', async () => {
                if (busy) return;
                wrap.querySelectorAll('button').forEach((item) => {
                    const selected = item === button;
                    item.classList.toggle('is-selected', selected);
                    item.setAttribute('aria-pressed', String(selected));
                });
                await onSelect(choice);
            });
            wrap.appendChild(button);
        });
        return wrap;
    };

    const createAccentPalette = () => {
        const panel = document.createElement('section');
        panel.className = 'onboarding-chat__palette';
        panel.setAttribute('aria-label', 'Выбор цвета интерфейса');

        const heading = document.createElement('div');
        heading.className = 'onboarding-chat__palette-heading';
        const headingCopy = document.createElement('div');
        const title = document.createElement('strong');
        title.textContent = 'Палитра акцента';
        const description = document.createElement('span');
        description.textContent = 'Все доступные цвета интерфейса';
        const count = document.createElement('small');
        count.textContent = `${accentChoices.length} вариантов`;
        headingCopy.append(title, description);
        heading.append(headingCopy, count);

        const grid = document.createElement('div');
        grid.className = 'onboarding-chat__color-grid';
        grid.setAttribute('role', 'radiogroup');
        grid.setAttribute('aria-label', 'Цвет акцента');

        let selectedChoice = accentChoices.find((choice) => choice.value === state.accent)
            || accentChoices[0];

        const selectChoice = (button, choice) => {
            selectedChoice = choice;
            state.accent = choice.value;
            grid.querySelectorAll('.onboarding-chat__color-option').forEach((item) => {
                const selected = item === button;
                item.classList.toggle('is-selected', selected);
                item.setAttribute('aria-checked', String(selected));
                item.setAttribute('tabindex', selected ? '0' : '-1');
            });
            window.StudentAssistantPreferences?.saveSetting('accent', choice.value);
        };

        accentChoices.forEach((choice) => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'onboarding-chat__color-option';
            button.dataset.value = choice.value;
            button.setAttribute('role', 'radio');
            button.setAttribute('aria-label', choice.label);
            button.style.setProperty('--choice-color', choice.color);
            button.style.setProperty('--choice-hover', choice.hover);

            const visual = document.createElement('span');
            visual.className = 'onboarding-chat__color-visual';
            visual.appendChild(document.createElement('i'));

            const copy = document.createElement('span');
            copy.className = 'onboarding-chat__color-copy';
            const label = document.createElement('strong');
            label.textContent = choice.label;
            const note = document.createElement('small');
            note.textContent = choice.description;
            copy.append(label, note);

            const check = document.createElement('span');
            check.className = 'onboarding-chat__color-check';
            check.textContent = '✓';
            check.setAttribute('aria-hidden', 'true');

            button.append(visual, copy, check);
            const selected = choice.value === selectedChoice.value;
            button.classList.toggle('is-selected', selected);
            button.setAttribute('aria-checked', String(selected));
            button.setAttribute('tabindex', selected ? '0' : '-1');
            button.addEventListener('click', () => selectChoice(button, choice));
            button.addEventListener('keydown', (event) => {
                if (!['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
                    return;
                }
                event.preventDefault();
                const buttons = [...grid.querySelectorAll('.onboarding-chat__color-option')];
                const currentIndex = buttons.indexOf(button);
                const direction = ['ArrowRight', 'ArrowDown'].includes(event.key) ? 1 : -1;
                const nextButton = buttons[(currentIndex + direction + buttons.length) % buttons.length];
                const nextChoice = accentChoices.find(
                    (item) => item.value === nextButton.dataset.value,
                );
                if (nextChoice) {
                    selectChoice(nextButton, nextChoice);
                    nextButton.focus();
                }
            });
            grid.appendChild(button);
        });

        const actions = document.createElement('div');
        actions.className = 'onboarding-chat__palette-actions';
        const hint = document.createElement('span');
        hint.textContent = 'Предпросмотр применяется сразу';
        const submit = createButton('Продолжить');
        submit.addEventListener('click', () => {
            void answerAndContinue(selectedChoice.label, () => {
                state.accent = selectedChoice.value;
            });
        });
        actions.append(hint, submit);
        panel.append(heading, grid, actions);
        return panel;
    };

    const answerAndContinue = async (answer, applyAnswer) => {
        if (busy) return;
        busy = true;
        applyAnswer();
        createMessage('user', [answer]);
        await goToStep(currentStepIndex + 1);
    };

    const buildSteps = () => {
        const steps = [
            {
                key: 'intro',
                title: 'Приветствие',
            },
        ];

        if (restartMode || !state.displayName) {
            steps.push({
                key: 'displayName',
                title: 'Имя',
                messages: () => [['Как мне тебя называть?']],
                render: () => {
                    setComposer(createInputForm({
                        label: 'Отображаемое имя',
                        placeholder: 'Например, Максим',
                        value: state.displayName || state.username,
                        maxLength: 40,
                        emptyError: 'Напиши имя, чтобы я знал, как к тебе обращаться.',
                        onSubmit: (answer) => answerAndContinue(answer, () => {
                            state.displayName = answer;
                        }),
                    }));
                },
            });
        }

        if (restartMode || !state.groupName) {
            steps.push({
                key: 'group',
                title: 'Учебная группа',
                messages: () => state.groupName
                    ? [[`Сейчас указана группа ${state.groupName}. Можно оставить её или изменить.`]]
                    : [['Какая у тебя учебная группа?']],
                render: () => {
                    setComposer(createInputForm({
                        label: 'Учебная группа',
                        placeholder: 'Например, ИКБО-42-24',
                        value: state.groupName,
                        maxLength: 50,
                        optional: true,
                        onSubmit: (answer) => answerAndContinue(
                            answer || (state.groupName ? `Оставить ${state.groupName}` : 'Не указывать'),
                            () => {
                                if (answer) state.groupName = answer;
                            },
                        ),
                        onSkip: () => answerAndContinue(
                            state.groupName ? `Оставить ${state.groupName}` : 'Не указывать',
                            () => {},
                        ),
                        skipLabel: state.groupName ? 'Оставить как есть' : 'Пропустить',
                    }));
                },
            });
        }

        if (restartMode || !state.course) {
            steps.push({
                key: 'course',
                title: 'Курс',
                messages: () => state.course
                    ? [[`Сейчас указан ${state.course} курс. Можно оставить его или выбрать другой.`]]
                    : [['На каком ты курсе?']],
                render: () => {
                    const choices = [1, 2, 3, 4, 5].map((course) => ({
                        value: String(course),
                        label: `${course} курс`,
                    }));
                    choices.push({ value: 'other', label: 'Другое' });
                    setComposer(createChoices(choices, state.course, async (choice) => {
                        if (choice.value === 'other') {
                            setComposer(createInputForm({
                                label: 'Номер курса',
                                placeholder: 'Например, 6',
                                value: Number(state.course) > 5 ? state.course : '',
                                inputType: 'number',
                                min: 1,
                                max: 12,
                                onSubmit: (answer) => answerAndContinue(`${answer} курс`, () => {
                                    state.course = answer;
                                }),
                            }));
                            return;
                        }
                        await answerAndContinue(choice.label, () => {
                            state.course = choice.value;
                        });
                    }, true));
                },
            });
        }

        steps.push(
            {
                key: 'accent',
                title: 'Цвет интерфейса',
                messages: () => [[
                    'Выбери акцент интерфейса. Я сразу покажу, как он выглядит.',
                ]],
                render: () => {
                    setComposer(createAccentPalette());
                },
            },
            {
                key: 'timeFormat',
                title: 'Формат времени',
                messages: () => [['Какой формат времени тебе удобнее?']],
                render: () => {
                    const choices = [
                        { value: '24', label: '24-часовой' },
                        { value: '12', label: '12-часовой' },
                    ];
                    setComposer(createChoices(choices, state.timeFormat, async (choice) => {
                        window.StudentAssistantPreferences?.saveSetting('timeFormat', choice.value);
                        await answerAndContinue(choice.label, () => {
                            state.timeFormat = choice.value;
                        });
                    }));
                },
            },
            {
                key: 'finish',
                title: 'Всё готово',
                messages: () => [
                    ['Готово! Я настроил твой профиль.'],
                    ['Теперь можно добавить первый предмет или перейти на главную.'],
                ],
                render: () => {
                    const actions = document.createElement('div');
                    actions.className = 'onboarding-chat__finish-actions';
                    const addSubject = createButton('Добавить первый предмет');
                    const dashboard = createButton('Перейти на главную', 'onboarding-chat__secondary');
                    const later = createButton('Пропустить', 'onboarding-chat__text-button');
                    addSubject.addEventListener('click', () => finish('/subjects#subject-create'));
                    dashboard.addEventListener('click', () => finish('/dashboard'));
                    later.addEventListener('click', () => finish('/dashboard'));
                    actions.append(addSubject, dashboard, later);
                    setComposer(actions);
                },
            },
        );

        return steps;
    };

    const steps = buildSteps();

    const updateProgress = (nextStepIndex) => {
        currentStepIndex = nextStepIndex;
        const humanStep = nextStepIndex + 1;
        const percent = (humanStep / steps.length) * 100;
        stepLabel.textContent = `Шаг ${humanStep} из ${steps.length}`;
        stepTitle.textContent = steps[nextStepIndex].title;
        progress.setAttribute('aria-valuemax', String(steps.length));
        progress.setAttribute('aria-valuenow', String(humanStep));
        progressFill.style.setProperty('--chat-progress', `${percent}%`);
        skipButton.hidden = nextStepIndex === 0;
    };

    async function goToStep(nextStepIndex) {
        const nextStep = steps[nextStepIndex];
        if (!nextStep) return;

        busy = true;
        chat.dataset.step = nextStep.key;
        composer.classList.add('is-waiting');
        await showTyping();
        updateProgress(nextStepIndex);
        nextStep.messages().forEach((paragraphs) => createMessage('assistant', paragraphs));
        nextStep.render();
        composer.classList.remove('is-waiting');
        busy = false;
    }

    const submitForm = async (form) => {
        const response = await fetch(form.action, {
            method: 'POST',
            body: new FormData(form),
            credentials: 'same-origin',
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok || !payload.ok) {
            throw new Error(payload.error || `HTTP ${response.status}`);
        }
        return payload;
    };

    async function finish(destination) {
        if (busy) return;
        busy = true;
        composer.classList.add('is-waiting');
        const values = {
            display_name: state.displayName,
            group_name: state.groupName,
            course: state.course,
            accent: state.accent,
            time_format: state.timeFormat,
            destination,
        };
        Object.entries(values).forEach(([name, value]) => {
            const field = completeForm.elements.namedItem(name);
            if (field) field.value = value;
        });
        try {
            const payload = await submitForm(completeForm);
            window.StudentAssistantPreferences?.saveSetting('accent', payload.accent);
            window.StudentAssistantPreferences?.saveSetting('timeFormat', payload.timeFormat);
            if (payload.redirect.startsWith('/subjects')) {
                try {
                    window.sessionStorage.setItem('student-assistant-pending-toast', JSON.stringify({
                        type: 'success',
                        title: 'Профиль настроен',
                        description: 'Теперь добавь первый предмет.',
                        duration: 4400,
                        savedAt: Date.now(),
                    }));
                } catch (_) {
                }
            }
            window.location.assign(payload.redirect);
        } catch (error) {
            busy = false;
            composer.classList.remove('is-waiting');
            window.showToast?.({
                type: 'error',
                title: 'Не удалось сохранить настройку',
                description: error.message || 'Попробуй ещё раз.',
                duration: 5200,
            });
        }
    }

    const skipOnboarding = async () => {
        const payload = await submitForm(skipForm);
        window.location.assign(payload.redirect);
    };

    const requestSkip = (trigger) => {
        const opened = window.requestConfirmation?.({
            title: 'Пропустить настройку?',
            description: 'Ты сможешь заполнить профиль и изменить настройки позже.',
            confirmLabel: 'Пропустить',
            trigger,
            onConfirm: skipOnboarding,
        });
        if (!opened && window.confirm('Пропустить настройку?')) {
            void skipOnboarding();
        }
    };

    const trapFocus = (event) => {
        if (event.key !== 'Tab') return;
        const focusable = [...chat.querySelectorAll(
            'button:not([hidden]):not([disabled]), input:not([disabled])',
        )].filter((element) => element.offsetParent !== null);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    };

    updateProgress(0);
    chat.dataset.step = 'intro';
    chat.hidden = false;
    document.body.classList.add('onboarding-chat-open');
    startButton.addEventListener('click', () => goToStep(1));
    skipButton.addEventListener('click', () => requestSkip(skipButton));
    closeButton.addEventListener('click', () => requestSkip(closeButton));
    chat.addEventListener('keydown', trapFocus);
    document.addEventListener('keydown', (event) => {
        if (
            event.key === 'Escape' &&
            !document.getElementById('confirmDialog')?.classList.contains('is-visible')
        ) {
            event.preventDefault();
            requestSkip(closeButton);
        }
    });
    window.addEventListener('pagehide', () => {
        document.body.classList.remove('onboarding-chat-open');
        if (initialFocus instanceof HTMLElement) initialFocus.focus();
    }, { once: true });
    requestAnimationFrame(() => startButton.focus());
})();
