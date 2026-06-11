window.toggleTaskEdit = function toggleTaskEdit(taskId) {
    const panel = document.getElementById(`task-edit-${taskId}`);
    if (!panel) {
        return;
    }

    const shouldOpen = panel.classList.contains('d-none');
    document.querySelectorAll('[id^="task-edit-"]').forEach((element) => {
        element.classList.add('d-none');
    });

    if (!shouldOpen) {
        return;
    }

    panel.classList.remove('d-none');
    const row = document.getElementById(`task-row-${taskId}`);
    if (row) {
        row.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
};

(() => {
    const listPanel = document.querySelector('.tasks-list-panel');
    const groupsRoot = document.getElementById('tasksGroups');
    const searchInput = document.getElementById('taskSearchInput');
    const emptyState = document.getElementById('tasksEmptyFilter');
    const resetButton = document.getElementById('tasksResetFilters');
    const sortSelect = document.getElementById('taskSortSelect');
    const filterButtons = [...document.querySelectorAll('[data-task-filter]')];
    const viewButtons = [...document.querySelectorAll('[data-task-view]')];
    let activeFilter = 'all';

    const taskItems = () => [...document.querySelectorAll('[data-task-item]')];
    const taskGroups = () => [...document.querySelectorAll('[data-task-group]')];

    const updateGroupCount = (group) => {
        const visibleItems = [...group.querySelectorAll('[data-task-item]')].filter((item) => !item.hidden);
        const count = group.querySelector('[data-group-count]');
        if (count) {
            count.textContent = `${visibleItems.length} ${visibleItems.length === 1 ? 'задача' : 'задач'}`;
        }
        group.hidden = visibleItems.length === 0;
        return visibleItems.length;
    };

    const applyFilters = () => {
        if (!groupsRoot) {
            return;
        }

        const query = (searchInput?.value || '').trim().toLocaleLowerCase('ru');
        const revealedItems = [];
        taskItems().forEach((item) => {
            const matchesFilter = activeFilter === 'all' || item.dataset.taskStatus === activeFilter;
            const matchesQuery = !query || (item.dataset.taskTitle || '').includes(query);
            const shouldShow = matchesFilter && matchesQuery;
            if (item.hidden && shouldShow) {
                revealedItems.push(item);
            }
            item.hidden = !shouldShow;
        });

        const visibleCount = taskGroups().reduce((total, group) => total + updateGroupCount(group), 0);
        const emptyWasHidden = emptyState?.hidden;
        if (emptyState) {
            emptyState.hidden = visibleCount !== 0;
        }
        if (groupsRoot) {
            groupsRoot.hidden = visibleCount === 0;
        }
        if (emptyWasHidden && emptyState && !emptyState.hidden) {
            revealedItems.push(emptyState);
        }
        window.animateMotionItems?.(revealedItems);
    };

    filterButtons.forEach((button) => {
        button.addEventListener('click', () => {
            activeFilter = button.dataset.taskFilter || 'all';
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
        if (sortSelect) {
            sortSelect.value = 'deadline';
        }
        filterButtons.forEach((button) => {
            button.classList.toggle('is-active', button.dataset.taskFilter === 'all');
        });
        applyFilters();
        searchInput?.focus();
    });

    document.querySelectorAll('[data-task-group-toggle]').forEach((button) => {
        button.addEventListener('click', () => {
            const group = button.closest('[data-task-group]');
            if (!group) {
                return;
            }
            const isCollapsed = group.classList.toggle('is-collapsed');
            button.setAttribute('aria-expanded', String(!isCollapsed));
        });
    });

    viewButtons.forEach((button) => {
        button.addEventListener('click', () => {
            const compact = button.dataset.taskView === 'compact';
            listPanel?.classList.toggle('is-compact-view', compact);
            viewButtons.forEach((item) => item.classList.toggle('is-active', item === button));
        });
    });

    const sortGroup = (group, mode) => {
        const body = group.querySelector('.tasks-group-body');
        if (!body) {
            return;
        }
        const rows = [...body.querySelectorAll(':scope > [data-task-item]')];
        rows.sort((left, right) => {
            if (mode === 'priority') {
                return Number(right.dataset.taskPriority || 0) - Number(left.dataset.taskPriority || 0);
            }
            if (mode === 'title') {
                return (left.dataset.taskTitle || '').localeCompare(right.dataset.taskTitle || '', 'ru');
            }
            return (left.dataset.taskDeadline || '').localeCompare(right.dataset.taskDeadline || '');
        });
        rows.forEach((row) => body.appendChild(row));
    };

    sortSelect?.addEventListener('change', () => {
        taskGroups().forEach((group) => sortGroup(group, sortSelect.value));
    });

    const selectedTaskNode = document.getElementById('selected-task-id');
    const selectedTaskId = selectedTaskNode?.dataset.taskId;
    if (selectedTaskId) {
        const target = document.getElementById(`task-row-${selectedTaskId}`);
        if (target) {
            target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    }
})();
