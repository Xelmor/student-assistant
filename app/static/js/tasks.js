window.toggleTaskEdit = function toggleTaskEdit(taskId) {
    const desktopRow = document.getElementById(`task-edit-${taskId}`);
    const mobilePanel = document.getElementById(`task-mobile-edit-${taskId}`);
    const currentPanel = mobilePanel || desktopRow;
    if (!currentPanel) {
        return;
    }

    const shouldOpen = currentPanel.classList.contains('d-none');

    document.querySelectorAll('[id^="task-edit-"], [id^="task-mobile-edit-"]').forEach((element) => {
        element.classList.add('d-none');
    });

    if (!shouldOpen) {
        return;
    }

    if (desktopRow) {
        desktopRow.classList.remove('d-none');
    }

    if (mobilePanel) {
        mobilePanel.classList.remove('d-none');
    }

    const mobileCard = document.getElementById(`task-mobile-card-${taskId}`);
    const scrollTarget = window.innerWidth < 768 ? (mobileCard || mobilePanel) : (desktopRow || mobilePanel);
    if (scrollTarget) {
        scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
};

(() => {
    const selectedTaskNode = document.getElementById('selected-task-id');
    const selectedTaskId = selectedTaskNode ? selectedTaskNode.dataset.taskId : null;
    if (!selectedTaskId) {
        return;
    }

    const desktopRow = document.getElementById(`task-row-${selectedTaskId}`);
    const mobileCard = document.getElementById(`task-mobile-card-${selectedTaskId}`);
    const target = window.innerWidth < 768 ? mobileCard : desktopRow;
    if (!target) {
        return;
    }

    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
})();
