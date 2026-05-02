window.toggleSubjectEdit = function toggleSubjectEdit(subjectId) {
    const desktopCard = document.getElementById(`subject-edit-${subjectId}`);
    const mobileCard = document.getElementById(`subject-mobile-edit-${subjectId}`);
    const isMobileViewport = window.innerWidth < 768;
    const targetBlock = isMobileViewport ? (mobileCard || desktopCard) : (desktopCard || mobileCard);

    if (!targetBlock) {
        return;
    }

    const closePanel = (panel) => {
        if (!panel || panel.classList.contains('d-none')) {
            return;
        }

        panel.classList.remove('is-open');
        panel.classList.add('is-closing');

        window.setTimeout(() => {
            panel.classList.add('d-none');
            panel.classList.remove('is-closing');
        }, 240);
    };

    const openPanel = (panel) => {
        panel.classList.remove('d-none');
        panel.classList.remove('is-closing');
        window.requestAnimationFrame(() => {
            panel.classList.add('is-open');
        });
    };

    const shouldOpen = targetBlock.classList.contains('d-none');

    document.querySelectorAll('.subject-edit-panel').forEach((element) => {
        if (element === targetBlock) {
            return;
        }
        closePanel(element);
    });

    if (!shouldOpen) {
        closePanel(targetBlock);
        return;
    }

    openPanel(targetBlock);

    if (isMobileViewport && mobileCard) {
        const scrollTarget = document.getElementById(`subject-mobile-card-${subjectId}`) || targetBlock;
        scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
};
