window.toggleSubjectEdit = function toggleSubjectEdit(subjectId) {
    const panel = document.getElementById(`subject-edit-${subjectId}`);
    if (!panel) {
        return;
    }

    const shouldOpen = panel.classList.contains('d-none');
    document.querySelectorAll('.subject-edit-panel').forEach((element) => {
        element.classList.add('d-none');
    });

    if (!shouldOpen) {
        return;
    }

    panel.classList.remove('d-none');
    document.getElementById(`subject-card-${subjectId}`)?.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
    });
};

(() => {
    const catalogPanel = document.querySelector('.subjects-catalog-panel');
    const catalog = document.getElementById('subjectsCatalog');
    const emptyState = document.getElementById('subjectsEmptyFilter');
    const resetButton = document.getElementById('subjectsResetFilters');
    const searchInput = document.getElementById('subjectSearchInput');
    const sortSelect = document.getElementById('subjectSortSelect');
    const filterButtons = [...document.querySelectorAll('[data-subject-filter]')];
    const sortButtons = [...document.querySelectorAll('[data-subject-sort]')];
    const viewButtons = [...document.querySelectorAll('[data-subject-view]')];
    let activeFilter = 'all';

    const subjectItems = () => [...document.querySelectorAll('[data-subject-item]')];

    document.querySelectorAll('[data-color-palette]').forEach((palette) => {
        const target = document.getElementById(palette.dataset.colorTarget || '');
        const swatches = [...palette.querySelectorAll('[data-color]')];
        const customColor = palette.querySelector('[data-custom-color]');

        const setColor = (color, activeSwatch = null) => {
            if (target) {
                target.value = color;
            }
            swatches.forEach((swatch) => swatch.classList.toggle('is-active', swatch === activeSwatch));
        };

        swatches.forEach((swatch) => {
            swatch.addEventListener('click', () => setColor(swatch.dataset.color, swatch));
        });

        customColor?.addEventListener('input', () => setColor(customColor.value));
    });

    const matchesFilter = (item) => {
        if (activeFilter === 'notes') {
            return item.dataset.subjectNotes === 'true';
        }
        if (activeFilter === 'no-room') {
            return item.dataset.subjectRoom !== 'true';
        }
        if (activeFilter === 'main') {
            return item.dataset.subjectMain === 'true';
        }
        return true;
    };

    const applyFilters = () => {
        const query = (searchInput?.value || '').trim().toLocaleLowerCase('ru');
        let visibleCount = 0;
        const revealedItems = [];

        subjectItems().forEach((item) => {
            const matchesQuery = !query || (item.dataset.subjectSearch || '').includes(query);
            const shouldShow = matchesFilter(item) && matchesQuery;
            if (item.hidden && shouldShow) {
                revealedItems.push(item);
            }
            item.hidden = !shouldShow;
            if (!item.hidden) {
                visibleCount += 1;
            }
        });

        const emptyWasHidden = emptyState?.hidden;
        if (emptyState) {
            emptyState.hidden = visibleCount !== 0 || subjectItems().length === 0;
        }
        if (catalog) {
            catalog.hidden = visibleCount === 0 && subjectItems().length > 0;
        }
        if (emptyWasHidden && emptyState && !emptyState.hidden) {
            revealedItems.push(emptyState);
        }
        window.animateMotionItems?.(revealedItems);
    };

    filterButtons.forEach((button) => {
        button.addEventListener('click', () => {
            activeFilter = button.dataset.subjectFilter || 'all';
            filterButtons.forEach((item) => item.classList.toggle('is-active', item === button));
            applyFilters();
        });
    });

    searchInput?.addEventListener('input', applyFilters);
    resetButton?.addEventListener('click', () => {
        activeFilter = 'all';
        if (searchInput) {
            searchInput.value = '';
        }
        filterButtons.forEach((button) => {
            button.classList.toggle('is-active', button.dataset.subjectFilter === 'all');
        });
        sortSubjects('name');
        applyFilters();
        searchInput?.focus();
    });

    const sortSubjects = (mode) => {
        if (!catalog) {
            return;
        }
        const addMore = document.getElementById('subjectAddMore');
        const items = subjectItems().sort((left, right) => {
            if (mode === 'color') {
                return (left.dataset.subjectColor || '').localeCompare(right.dataset.subjectColor || '');
            }
            return (left.dataset.subjectName || '').localeCompare(right.dataset.subjectName || '', 'ru');
        });
        items.forEach((item) => catalog.insertBefore(item, addMore));
        if (sortSelect) {
            sortSelect.value = mode;
        }
        sortButtons.forEach((button) => {
            button.classList.toggle('is-active', button.dataset.subjectSort === mode);
        });
    };

    sortButtons.forEach((button) => {
        button.addEventListener('click', () => sortSubjects(button.dataset.subjectSort || 'name'));
    });
    sortSelect?.addEventListener('change', () => sortSubjects(sortSelect.value));

    viewButtons.forEach((button) => {
        button.addEventListener('click', () => {
            catalogPanel?.classList.toggle('is-list-view', button.dataset.subjectView === 'list');
            viewButtons.forEach((item) => item.classList.toggle('is-active', item === button));
        });
    });

    document.getElementById('subjectAddMore')?.addEventListener('click', () => {
        const createPanel = document.getElementById('subject-create');
        const nameInput = document.getElementById('subjectNameInput');
        createPanel?.scrollIntoView({ behavior: 'smooth', block: 'start' });
        window.setTimeout(() => nameInput?.focus(), 450);
    });
})();
