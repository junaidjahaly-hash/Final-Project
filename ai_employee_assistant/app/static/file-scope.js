// Keep file selection within this visit and drop files that no longer exist.
let fileScopeMode = 'auto';
let selectedFiles = new Set();
let workspaceFiles = [];

function setFileScope(mode) {
    if (!['auto', 'all', 'selected'].includes(mode)) return;
    fileScopeMode = mode;
    renderFileScope();
    if (mode === 'selected' && !selectedFiles.size) openFileScope();
}

function clearFileScope() {
    fileScopeMode = 'selected';
    selectedFiles.clear();
    renderFileScope();
}

function openFileScope() {
    const dialog = document.getElementById('fileScopeDialog');
    renderFileScope();
    if (!dialog.open) dialog.showModal();
}

function updateWorkspaceFiles(files) {
    workspaceFiles = files;
    const available = new Set(files.map(file => file.filename));
    selectedFiles = new Set([...selectedFiles].filter(name => available.has(name)));
    renderFileScope();
}

function fileScopeRequest() {
    if (fileScopeMode === 'selected' && !selectedFiles.size) {
        showToast('Select at least one file, or choose All files / Auto.', 'warning');
        openFileScope();
        return null;
    }
    return { file_scope: fileScopeMode, selected_files: fileScopeMode === 'selected' ? [...selectedFiles] : [] };
}

function renderFileScope() {
    const focusKey = document.activeElement?.dataset.scopeKey;
    const all = fileScopeMode === 'all';
    const count = all ? workspaceFiles.length : selectedFiles.size;
    document.getElementById('fileScopeMode').value = fileScopeMode;
    const summary = document.getElementById('fileScopeSummary');
    summary.textContent = fileScopeMode === 'auto' ? 'Choose files' : `${all ? 'All' : 'Selected'} ${count} file${count === 1 ? '' : 's'} · Change`;
    summary.title = all ? 'Every uploaded file is in scope' : [...selectedFiles].join('\n');
    document.getElementById('fileScopeHint').textContent = fileScopeMode === 'auto'
        ? 'Auto chooses the best matching file. Select files to take control.'
        : `${count} file${count === 1 ? '' : 's'} in scope. ${count > 1 ? 'Multi-file analysis can take longer.' : 'Only selected evidence will be used.'}`;
    const search = document.getElementById('fileScopeSearch').value.toLowerCase();
    for (const [id, compact] of [['dataFilesList', true], ['fileScopeList', false]]) {
        const list = document.getElementById(id);
        const previousScroll = list.scrollTop;
        list.replaceChildren();
        const files = workspaceFiles.filter(file => compact || file.filename.toLowerCase().includes(search));
        if (!files.length) {
            const empty = document.createElement('p');
            empty.className = 'sidebar-empty';
            empty.textContent = workspaceFiles.length ? 'No matching files.' : 'Upload a PDF, CSV or Excel file to get started.';
            list.append(empty);
        }
        files.forEach(file => {
            const row = document.createElement('div');
            row.className = 'scope-file-row';
            const label = document.createElement('label');
            const check = document.createElement('input');
            check.type = 'checkbox';
            check.dataset.scopeKey = `${id}:include:${file.filename}`;
            check.checked = all || (fileScopeMode === 'selected' && selectedFiles.has(file.filename));
            check.setAttribute('aria-label', `Include ${file.filename}`);
            check.addEventListener('change', () => {
                if (fileScopeMode === 'all') selectedFiles = new Set(workspaceFiles.map(f => f.filename));
                if (check.checked) selectedFiles.add(file.filename); else selectedFiles.delete(file.filename);
                fileScopeMode = 'selected';
                renderFileScope();
            });
            const name = document.createElement('span');
            name.textContent = file.filename;
            name.title = file.filename;
            label.append(check, name);
            const only = document.createElement('button');
            only.type = 'button';
            only.dataset.scopeKey = `${id}:only:${file.filename}`;
            only.className = 'scope-only';
            only.textContent = 'Only';
            only.setAttribute('aria-label', `Focus only on ${file.filename}`);
            only.addEventListener('click', () => {
                selectedFiles = new Set([file.filename]);
                fileScopeMode = 'selected';
                renderFileScope();
            });
            row.append(label, only);
            if (!compact) {
                const remove = document.createElement('button');
                remove.type = 'button';
                remove.className = 'scope-delete';
                remove.textContent = 'Delete';
                remove.setAttribute('aria-label', `Delete ${file.filename}`);
                remove.addEventListener('click', () => deleteFile(file.filename));
                row.append(remove);
            }
            list.append(row);
        });
        list.scrollTop = previousScroll;
    }
    if (focusKey) [...document.querySelectorAll('[data-scope-key]')].find(element => element.dataset.scopeKey === focusKey)?.focus({preventScroll:true});
}
