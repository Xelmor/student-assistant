window.toggleSubjectEdit = function toggleSubjectEdit(subjectId) {
    const desktopCard = document.getElementById(`subject-edit-${subjectId}`);
    const mobileCard = document.getElementById(`subject-mobile-edit-${subjectId}`);
    const currentBlock = mobileCard || desktopCard;
    if (!currentBlock) {
        return;
    }

    const shouldOpen = currentBlock.classList.contains('d-none');

    document.querySelectorAll('[id^="subject-edit-"], [id^="subject-mobile-edit-"]').forEach((element) => {
        element.classList.add('d-none');
    });

    if (!shouldOpen) {
        return;
    }

    if (desktopCard) {
        desktopCard.classList.remove('d-none');
    }

    if (mobileCard) {
        mobileCard.classList.remove('d-none');
        const scrollTarget = document.getElementById(`subject-mobile-card-${subjectId}`) || mobileCard;
        scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
};
