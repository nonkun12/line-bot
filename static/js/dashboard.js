document.addEventListener('DOMContentLoaded', () => {
    // --- Elements ---
    const refreshBtn = document.getElementById('refreshBtn');
    const searchInput = document.getElementById('searchInput');
    const notesTableBody = document.getElementById('notesTableBody');
    const loadingState = document.getElementById('loadingState');
    const emptyState = document.getElementById('emptyState');
    const errorAlert = document.getElementById('errorAlert');
    const errorMessage = document.getElementById('errorMessage');
    const userIdDisplay = document.getElementById('userIdDisplay');

    // Modal Elements
    const newNoteBtn = document.getElementById('newNoteBtn');
    const newNoteModal = document.getElementById('newNoteModal');
    const closeModalBtn = document.getElementById('closeModalBtn');
    const cancelModalBtn = document.getElementById('cancelModalBtn');
    const newNoteForm = document.getElementById('newNoteForm');
    const noteTitle = document.getElementById('noteTitle');
    const noteCategory = document.getElementById('noteCategory');
    const noteBody = document.getElementById('noteBody');
    const modalErrorAlert = document.getElementById('modalErrorAlert');
    const modalErrorMessage = document.getElementById('modalErrorMessage');
    const submitNoteBtn = document.getElementById('submitNoteBtn');

    // --- State ---
    let allNotes = [];
    const userId = getTargetUserId();

    // Initialize UI displaying user_id
    if (userIdDisplay && userId) {
        userIdDisplay.textContent = userId.length > 12 ? `${userId.substring(0, 12)}...` : userId;
        userIdDisplay.title = userId;
    }

    // --- Helpers ---
    function getTargetUserId() {
        const meta = document.querySelector('meta[name="user-id"]');
        return meta ? meta.getAttribute('content') : '';
    }

    function classifyCategoryClass(category) {
        const cat = String(category || '').toLowerCase();
        if (cat.includes('予定') || cat.includes('schedule')) return 'cat-schedule';
        if (cat.includes('技術') || cat.includes('tech') || cat.includes('python')) return 'cat-tech';
        if (cat.includes('学習') || cat.includes('study') || cat.includes('勉強')) return 'cat-study';
        if (cat.includes('生活') || cat.includes('life') || cat.includes('買')) return 'cat-life';
        return 'cat-general';
    }

    function escapeHtml(str) {
        if (!str) return '';
        return str
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
    }

    function showGlobalError(msg) {
        errorMessage.textContent = msg;
        errorAlert.classList.remove('hidden');
    }

    function hideGlobalError() {
        errorAlert.classList.add('hidden');
    }

    function showModalError(msg) {
        modalErrorMessage.textContent = msg;
        modalErrorAlert.classList.remove('hidden');
    }

    function hideModalError() {
        modalErrorAlert.classList.add('hidden');
    }

    // --- UI Render ---
    function renderNotes(notes) {
        notesTableBody.innerHTML = '';

        if (notes.length === 0) {
            emptyState.classList.remove('hidden');
            return;
        }

        emptyState.classList.add('hidden');

        notes.forEach(note => {
            const tr = document.createElement('tr');

            // Format ID safely
            const noteId = note.id !== undefined && note.id !== null ? note.id : '-';
            const category = note.category || '一般';
            const title = note.title || 'LINEメモ';
            const body = note.body || '';

            const catClass = classifyCategoryClass(category);

            tr.innerHTML = `
                <td class="col-id">${escapeHtml(String(noteId))}</td>
                <td class="col-category">
                    <span class="cat-badge ${catClass}">${escapeHtml(category)}</span>
                </td>
                <td class="col-title">${escapeHtml(title)}</td>
                <td class="col-body">${escapeHtml(body).replace(/\n/g, '<br>')}</td>
                <td class="col-actions">
                    <button class="btn btn-danger delete-btn" data-id="${escapeHtml(String(noteId))}">削除</button>
                </td>
            `;
            notesTableBody.appendChild(tr);
        });

        // Add event listeners to delete buttons
        document.querySelectorAll('.delete-btn').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const noteId = e.currentTarget.getAttribute('data-id');
                handleDeleteNote(noteId);
            });
        });
    }

    // --- API Interactions ---

    // 1. Fetch Notes
    async function fetchNotes() {
        // Reset states
        hideGlobalError();
        emptyState.classList.add('hidden');
        notesTableBody.innerHTML = '';
        loadingState.classList.remove('hidden');
        refreshBtn.disabled = true;

        const url = `/api/dashboard/notes?user_id=${encodeURIComponent(userId)}`;

        try {
            const response = await fetch(url);
            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP error! status: ${response.status}`);
            }

            if (data.ok) {
                allNotes = data.notes || [];
                renderNotes(allNotes);
                filterNotes(); // Trigger filter once for existing input
            } else {
                throw new Error(data.error || 'Failed to fetch notes.');
            }
        } catch (err) {
            console.error('Fetch error:', err);
            showGlobalError(`メモの取得に失敗しました: ${err.message}`);
            emptyState.classList.add('hidden');
        } finally {
            loadingState.classList.add('hidden');
            refreshBtn.disabled = false;
        }
    }

    // 2. Add Note
    async function handleAddNote(title, body, category) {
        hideModalError();
        submitNoteBtn.disabled = true;

        const url = `/api/dashboard/notes?user_id=${encodeURIComponent(userId)}`;
        const payload = {
            title: title,
            body: body,
            category: category
        };

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP error! status: ${response.status}`);
            }

            if (data.ok) {
                closeModal();
                fetchNotes(); // Reload list
            } else {
                throw new Error(data.error || 'Failed to save note.');
            }
        } catch (err) {
            console.error('Save error:', err);
            showModalError(`メモの追加に失敗しました: ${err.message}`);
        } finally {
            submitNoteBtn.disabled = false;
        }
    }

    // 3. Delete Note
    async function handleDeleteNote(noteId) {
        if (!noteId || noteId === '-') return;

        const confirmDelete = confirm('このメモを削除してよろしいですか？');
        if (!confirmDelete) return;

        hideGlobalError();
        const url = `/api/dashboard/notes/${encodeURIComponent(noteId)}?user_id=${encodeURIComponent(userId)}`;

        try {
            const response = await fetch(url, {
                method: 'DELETE'
            });

            const data = await response.json();

            if (!response.ok) {
                throw new Error(data.error || `HTTP error! status: ${response.status}`);
            }

            if (data.ok) {
                fetchNotes(); // Reload list
            } else {
                throw new Error(data.error || 'Failed to delete note.');
            }
        } catch (err) {
            console.error('Delete error:', err);
            showGlobalError(`メモの削除に失敗しました: ${err.message}`);
        }
    }

    // --- Client-side Filter ---
    function filterNotes() {
        const query = searchInput.value.toLowerCase().trim();
        if (!query) {
            renderNotes(allNotes);
            return;
        }

        const filtered = allNotes.filter(note => {
            const title = (note.title || '').toLowerCase();
            const body = (note.body || '').toLowerCase();
            const category = (note.category || '').toLowerCase();
            const id = String(note.id || '').toLowerCase();

            return title.includes(query) ||
                   body.includes(query) ||
                   category.includes(query) ||
                   id.includes(query);
        });

        // Use a variant of render that does not re-register events if possible,
        // but renderNotes handles events registering correctly.
        renderNotes(filtered);
    }

    // --- Modal Controls ---
    function openModal() {
        newNoteForm.reset();
        hideModalError();
        newNoteModal.classList.remove('hidden');
        noteTitle.focus();
    }

    function closeModal() {
        newNoteModal.classList.add('hidden');
    }

    // --- Event Listeners ---
    refreshBtn.addEventListener('click', fetchNotes);
    searchInput.addEventListener('input', filterNotes);

    // Modal events
    newNoteBtn.addEventListener('click', openModal);
    closeModalBtn.addEventListener('click', closeModal);
    cancelModalBtn.addEventListener('click', closeModal);

    // Close modal when clicking outside content
    window.addEventListener('click', (e) => {
        if (e.target === newNoteModal) {
            closeModal();
        }
    });

    // Form submission
    newNoteForm.addEventListener('submit', (e) => {
        e.preventDefault();
        const title = noteTitle.value.trim();
        const body = noteBody.value.trim();
        const category = noteCategory.value;

        if (!title || !body) {
            showModalError('タイトルと内容を入力してください。');
            return;
        }

        handleAddNote(title, body, category);
    });

    // --- Initial Load ---
    fetchNotes();
});
