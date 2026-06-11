(() => {
    const list = document.getElementById('notesList');
    const searchInput = document.getElementById('notesSearchInput');
    const subjectFilter = document.getElementById('notesSubjectFilter');
    const typeFilter = document.getElementById('notesTypeFilter');
    const sortSelect = document.getElementById('notesSortSelect');
    const resetButton = document.getElementById('notesResetFilters');
    const emptyResetButton = document.getElementById('notesEmptyReset');
    const count = document.getElementById('notesVisibleCount');
    const pagination = document.getElementById('notesPagination');
    const emptyFilter = document.getElementById('notesEmptyFilter');
    const pageSize = 6;
    const pinStorageKey = 'student-assistant-pinned-notes';
    let currentPage = 1;

    const readPinnedNotes = () => {
        try {
            return new Set(JSON.parse(window.localStorage.getItem(pinStorageKey) || '[]').map(String));
        } catch (_) {
            return new Set();
        }
    };

    let pinnedNotes = readPinnedNotes();

    const savePinnedNotes = () => {
        window.localStorage.setItem(pinStorageKey, JSON.stringify(Array.from(pinnedNotes)));
    };

    const getItems = () => Array.from(list?.querySelectorAll('[data-note-item]') || []);

    const matchesFilters = (item) => {
        const query = (searchInput?.value || '').trim().toLocaleLowerCase('ru');
        const subject = subjectFilter?.value || '';
        const type = typeFilter?.value || '';
        const searchable = item.dataset.noteSearch || '';
        const types = (item.dataset.noteTypes || '').split(/\s+/);

        return (!query || searchable.includes(query))
            && (!subject || item.dataset.noteSubject === subject)
            && (!type || types.includes(type));
    };

    const sortItems = (items) => {
        const mode = sortSelect?.value || 'newest';

        return items.sort((left, right) => {
            const leftPinned = pinnedNotes.has(left.dataset.noteId);
            const rightPinned = pinnedNotes.has(right.dataset.noteId);
            if (leftPinned !== rightPinned) {
                return leftPinned ? -1 : 1;
            }

            if (mode === 'title') {
                return (left.dataset.noteTitle || '').localeCompare(right.dataset.noteTitle || '', 'ru');
            }

            const dateDifference = (left.dataset.noteCreated || '').localeCompare(right.dataset.noteCreated || '');
            return mode === 'oldest' ? dateDifference : -dateDifference;
        });
    };

    const createPageButton = (label, page, options = {}) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = `notes-page-button${options.active ? ' is-active' : ''}`;
        button.textContent = label;
        button.disabled = Boolean(options.disabled);
        button.setAttribute('aria-label', options.ariaLabel || `Страница ${page}`);
        if (options.active) {
            button.setAttribute('aria-current', 'page');
        }
        button.addEventListener('click', () => {
            currentPage = page;
            render();
            list?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        });
        return button;
    };

    const renderPagination = (pageCount) => {
        if (!pagination) {
            return;
        }

        pagination.replaceChildren();
        if (pageCount <= 1) {
            return;
        }

        pagination.append(createPageButton('‹', Math.max(1, currentPage - 1), {
            disabled: currentPage === 1,
            ariaLabel: 'Предыдущая страница',
        }));

        for (let page = 1; page <= pageCount; page += 1) {
            pagination.append(createPageButton(String(page), page, { active: page === currentPage }));
        }

        pagination.append(createPageButton('›', Math.min(pageCount, currentPage + 1), {
            disabled: currentPage === pageCount,
            ariaLabel: 'Следующая страница',
        }));
    };

    const render = () => {
        if (!list) {
            return;
        }

        const allItems = getItems();
        allItems.forEach((item) => {
            const isPinned = pinnedNotes.has(item.dataset.noteId);
            item.classList.toggle('is-pinned', isPinned);
            const pinButton = item.querySelector('[data-note-pin]');
            pinButton?.setAttribute('aria-pressed', String(isPinned));
            pinButton?.setAttribute('title', isPinned ? 'Открепить' : 'Закрепить');
        });

        const filteredItems = sortItems(allItems.filter(matchesFilters));
        filteredItems.forEach((item) => list.append(item));

        const pageCount = Math.max(1, Math.ceil(filteredItems.length / pageSize));
        currentPage = Math.min(currentPage, pageCount);
        const pageStart = (currentPage - 1) * pageSize;
        const visibleItems = new Set(filteredItems.slice(pageStart, pageStart + pageSize));
        const revealedItems = [];

        allItems.forEach((item) => {
            const shouldShow = visibleItems.has(item);
            if (item.hidden && shouldShow) {
                revealedItems.push(item);
            }
            item.hidden = !shouldShow;
        });

        if (count) {
            count.textContent = String(filteredItems.length);
        }
        const emptyWasHidden = emptyFilter?.hidden;
        if (emptyFilter) {
            emptyFilter.hidden = filteredItems.length > 0;
        }
        renderPagination(filteredItems.length ? pageCount : 0);
        if (emptyWasHidden && emptyFilter && !emptyFilter.hidden) {
            revealedItems.push(emptyFilter);
        }
        window.animateMotionItems?.(revealedItems);
    };

    window.toggleNoteEdit = (noteId) => {
        const target = document.getElementById(`note-edit-${noteId}`);
        if (!target) {
            return;
        }

        const shouldOpen = target.classList.contains('d-none');
        document.querySelectorAll('[id^="note-edit-"]').forEach((panel) => panel.classList.add('d-none'));

        if (shouldOpen) {
            target.classList.remove('d-none');
            document.getElementById(`note-card-${noteId}`)?.scrollIntoView({
                behavior: 'smooth',
                block: 'nearest',
            });
        }
    };

    [searchInput, subjectFilter, typeFilter, sortSelect].forEach((control) => {
        control?.addEventListener(control === searchInput ? 'input' : 'change', () => {
            currentPage = 1;
            render();
        });
    });

    const resetFilters = () => {
        if (searchInput) searchInput.value = '';
        if (subjectFilter) subjectFilter.value = '';
        if (typeFilter) typeFilter.value = '';
        if (sortSelect) sortSelect.value = 'newest';
        currentPage = 1;
        render();
        searchInput?.focus();
    };

    resetButton?.addEventListener('click', resetFilters);
    emptyResetButton?.addEventListener('click', resetFilters);

    document.querySelectorAll('[data-note-pin]').forEach((button) => {
        button.addEventListener('click', () => {
            const noteId = button.dataset.notePin;
            if (pinnedNotes.has(noteId)) {
                pinnedNotes.delete(noteId);
            } else {
                pinnedNotes.add(noteId);
            }
            savePinnedNotes();
            currentPage = 1;
            render();
        });
    });

    document.querySelector('.notes-new-button')?.addEventListener('click', () => {
        window.setTimeout(() => document.getElementById('noteTitleInput')?.focus(), 350);
    });

    render();
})();
