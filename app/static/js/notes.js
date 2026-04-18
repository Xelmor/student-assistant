window.toggleNoteEdit = function toggleNoteEdit(noteId) {
    const desktopBlock = document.getElementById(`note-edit-${noteId}`);
    const mobileBlock = document.getElementById(`note-mobile-edit-${noteId}`);
    const currentBlock = mobileBlock || desktopBlock;
    if (!currentBlock) {
        return;
    }

    const shouldOpen = currentBlock.classList.contains('d-none');

    document.querySelectorAll('[id^="note-edit-"], [id^="note-mobile-edit-"]').forEach((element) => {
        element.classList.add('d-none');
    });

    if (!shouldOpen) {
        return;
    }

    if (desktopBlock) {
        desktopBlock.classList.remove('d-none');
    }

    if (mobileBlock) {
        mobileBlock.classList.remove('d-none');
        const scrollTarget = document.getElementById(`note-mobile-card-${noteId}`) || mobileBlock;
        scrollTarget.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }
};
