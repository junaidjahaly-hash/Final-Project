const API_URL = window.location.origin;
let currentToken = localStorage.getItem('token');
let currentUser = localStorage.getItem('username');
let currentRole = localStorage.getItem('role');
let currentSessionId = null;
let currentAuthTab = 'login';
let currentBISummary = null;
let currentBIChartBase64 = '';

// Toast notification system
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    if (!container) return;

    const icons = {
        success: '✅',
        error: '❌',
        warning: '⚠️',
        info: 'ℹ️'
    };

    const toast = document.createElement('div');
    toast.className = `toast-card ${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || 'ℹ️'}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
    `;

    container.appendChild(toast);

    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(40px)';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

function escapeHtml(text) {
    if (!text) return '';
    return text.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

// Initialization
function init() {
    if (currentToken) {
        document.getElementById('loginScreen').style.display = 'none';
        document.getElementById('mainApp').style.display = 'flex';
        
        const badge = document.getElementById('userBadge');
        if (badge) badge.innerHTML = `<span class="user-initial">${escapeHtml((currentUser || 'U').slice(0, 1).toUpperCase())}</span>${escapeHtml(currentUser)} <span style="font-size:9px; opacity:0.8;">${escapeHtml(currentRole)}</span>`;
        
        if (currentRole === 'admin') {
            document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'flex');
        } else {
            document.querySelectorAll('.admin-only').forEach(el => el.style.display = 'none');
        }
        
        loadTickets();
        loadReminders();
        startWorkflowPolling();
        loadDataFiles();
        loadChatHistory(true);
        if (currentRole === 'admin') loadAuditLogs();
    } else {
        document.getElementById('loginScreen').style.display = 'flex';
        document.getElementById('mainApp').style.display = 'none';
    }
}

// Auth system
function switchAuthTab(tab) {
    currentAuthTab = tab;
    document.getElementById('tabLoginBtn').classList.toggle('active', tab === 'login');
    document.getElementById('tabRegisterBtn').classList.toggle('active', tab === 'register');
    document.getElementById('registerRoleGroup').style.display = tab === 'register' ? 'block' : 'none';
    document.getElementById('authSubmitBtn').textContent = tab === 'login' ? 'Sign In' : 'Create Account';
    document.getElementById('loginError').textContent = '';
}

async function handleAuthSubmit() {
    if (currentAuthTab === 'login') {
        await handleLogin();
    } else {
        await handleRegister();
    }
}

async function handleLogin() {
    const u = document.getElementById('loginUser').value.trim();
    const p = document.getElementById('loginPass').value;
    if (!u || !p) return showToast('Please enter both username and password', 'warning');
    
    try {
        const res = await fetch(`${API_URL}/auth/login`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username: u, password: p})
        });
        const data = await res.json();
        if (res.ok) {
            localStorage.setItem('token', data.token);
            localStorage.setItem('username', data.username);
            localStorage.setItem('role', data.role);
            currentToken = data.token;
            currentUser = data.username;
            currentRole = data.role;
            showToast(`Welcome back, ${currentUser}!`, 'success');
            init();
        } else {
            document.getElementById('loginError').textContent = data.error || 'Login failed';
            showToast(data.error || 'Login failed', 'error');
        }
    } catch(e) {
        showToast('Connection error to auth server', 'error');
    }
}

async function handleRegister() {
    const u = document.getElementById('loginUser').value.trim();
    const p = document.getElementById('loginPass').value;
    const r = document.getElementById('registerRole').value;
    if (!u || !p) return showToast('Please provide a username and password', 'warning');
    
    try {
        const res = await fetch(`${API_URL}/auth/register`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({username: u, password: p, role: r})
        });
        const data = await res.json();
        if (res.ok) {
            showToast('Registration successful! Please sign in.', 'success');
            switchAuthTab('login');
        } else {
            document.getElementById('loginError').textContent = data.error || 'Registration failed';
            showToast(data.error || 'Registration failed', 'error');
        }
    } catch(e) {
        showToast('Connection error during registration', 'error');
    }
}

function logout() {
    stopWorkflowPolling();
    clearChatImage();
    ['token', 'username', 'role'].forEach(key => localStorage.removeItem(key));
    currentToken = null;
    currentUser = null;
    currentRole = null;
    currentSessionId = null;
    clearWorkflowViews();
    showToast('Logged out successfully', 'info');
    init();
}

// Navigation
function switchTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(el => {
        el.classList.remove('active');
        el.style.display = 'none';
    });
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));
    
    const targetTab = document.getElementById(`tab-${tabName}`);
    const targetNav = document.getElementById(`nav-${tabName}`);
    if (targetTab) {
        targetTab.classList.add('active');
        targetTab.style.display = (tabName === 'bi') ? 'block' : 'flex';
        if (tabName === 'bi') loadBIDatasets();
        if (tabName === 'tickets') loadTickets();
        if (tabName === 'tasks') loadTasks();
        if (tabName === 'reminders') loadReminders();
        if (tabName === 'notifications') loadNotifications();
    }
    if (targetNav) targetNav.classList.add('active');
}

async function loadBIDatasets() {
    await loadDataFiles();
    onBIDatasetChange();
}

// Markdown renderer
function parseMarkdown(text) {
    if (!text) return '';
    
    if (text.trim().startsWith('<p>') || text.includes('<img src="data:image')) {
        return text;
    }

    let parsed = text;

    parsed = parsed.replace(/```(\w*)\n([\s\S]*?)```/g, (match, lang, code) => {
        const codeId = 'code_' + Math.random().toString(36).substr(2, 9);
        const cleanCode = escapeHtml(code.trim());
        return `
            <div class="code-block-wrapper">
                <div class="code-header">
                    <span>${lang || 'code'}</span>
                    <button class="copy-code-btn" onclick="copyCode('${codeId}')">📋 Copy</button>
                </div>
                <pre id="${codeId}"><code>${cleanCode}</code></pre>
            </div>
        `;
    });

    parsed = parsed.replace(/`([^`]+)`/g, '<code style="background:rgba(255,255,255,0.1); padding:2px 6px; border-radius:4px; font-family:\'JetBrains Mono\',monospace; font-size:12px;">$1</code>');

    parsed = parsed.replace(/^### (.*$)/gim, '<h3>$1</h3>');
    parsed = parsed.replace(/^## (.*$)/gim, '<h2>$1</h2>');
    parsed = parsed.replace(/^# (.*$)/gim, '<h1>$1</h1>');

    parsed = parsed.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    parsed = parsed.replace(/\*(.*?)\*/g, '<em>$1</em>');

    parsed = parsed.replace(/^\s*-\s+(.*$)/gim, '<li>$1</li>');
    parsed = parsed.replace(/(<li>.*<\/li>)/sim, '<ul>$1</ul>');

    const paragraphs = parsed.split(/\n\n+/);
    return paragraphs.map(p => {
        if (p.startsWith('<h') || p.startsWith('<ul') || p.startsWith('<div')) return p;
        return `<p>${p.replace(/\n/g, '<br>')}</p>`;
    }).join('');
}

function copyCode(codeId) {
    const el = document.getElementById(codeId);
    if (!el) return;
    navigator.clipboard.writeText(el.innerText).then(() => {
        showToast('Code copied to clipboard!', 'success');
    }).catch(() => {
        showToast('Failed to copy code', 'error');
    });
}

// Chat & agent
function askPrompt(text) {
    document.getElementById('questionInput').value = text;
    sendQuestion();
}


async function sendQuestion() {
    const input = document.getElementById('questionInput');
    const image = chatImage;
    const question = input.value.trim() || (image ? 'Help me understand and fix the problem shown in this image.' : '');
    if (!question) return;
    if (document.getElementById('sendBtn').disabled) return;
    const scope = image ? {} : fileScopeRequest();
    if (!scope) return;
    document.getElementById('sendBtn').disabled = true;
    document.getElementById('attachImageBtn').disabled = true;

    input.value = '';
    
    const welcome = document.querySelector('.welcome-message');
    if (welcome) welcome.remove();

    addMessage(question, 'user');
    if (image) addChatImagePreview(image);
    await saveMessage('user', image ? `${question}\n[Attached image: ${image.name}]` : question, false);
    loadChatHistory();
    showTyping();
    
    try {
        const imageBody = image ? new FormData() : null;
        if (imageBody) {
            imageBody.append('image', image);
            imageBody.append('question', question);
            if (currentSessionId) imageBody.append('session_id', currentSessionId);
        }
        const res = await fetch(`${API_URL}${image ? '/query/image' : '/query'}`, {
            method: 'POST',
            headers: {
                ...(image ? {} : { 'Content-Type': 'application/json' }),
                'Authorization': `Bearer ${currentToken}`
            },
            body: imageBody || JSON.stringify({ question, session_id: currentSessionId, ...scope })
        });
        
        hideTyping();
        const data = await res.json();
        
        if (res.ok) {
            if (image && chatImage === image) clearChatImage();
            if (['task_plan', 'meeting_summary'].includes(data.mode)) {
                renderWorkflowPlan(data, document.getElementById('chatMessages'));
                await saveMessage('assistant', workflowPlanText(data), false);
            } else if (data.mode === 'pending_approval') {
                renderApproval(data);
                await saveMessage('assistant', data.answer, false);
            } else {
                const text = data.answer || data.analysis || 'Completed action.';
                const modeName = data.mode || 'single_file_priority';
                addMessage(text, 'assistant', !image, data.mode, data.source, data.file_used);
                await saveMessage('assistant', text, !image);
                if (image) addScreenshotTicketAction(question, text);
                loadDataFiles();
            }
        } else {
            if (image) input.value = question;
            addMessage(`❌ Error: ${data.error || data.detail || 'Server processing error'}`, 'assistant');
        }
    } catch (e) {
        if (image) input.value = question;
        hideTyping();
        addMessage(`❌ Connection error: Unable to reach AI agent server`, 'assistant');
    } finally {
        document.getElementById('sendBtn').disabled = false;
        document.getElementById('attachImageBtn').disabled = false;
    }
}

async function sendRLFeedback(modeName, reward, btnEl) {
    if (!modeName) modeName = 'single_file_priority';
    const parentContainer = btnEl.parentElement;
    try {
        const res = await fetch(`${API_URL}/rl/feedback`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentToken}`
            },
            body: JSON.stringify({
                mode_name: modeName,
                reward: reward,
                query_text: "User Chat Interface Feedback"
            })
        });
        const data = await res.json();
        if (res.ok) {
            parentContainer.innerHTML = `<span style="font-size:11px; color:var(--accent-cyan); font-weight:600;">
                ${reward > 0 ? '👍 Thank you! RL Q-Weight +0.10' : '👎 Thank you! RL Q-Weight updated'}
            </span>`;
            showToast(`Reinforcement Learning Feedback logged! (Q-Score: ${data.new_q_value})`, 'success');
        }
    } catch (e) {
        showToast("Unable to record RL feedback", 'warning');
    }
}

function renderApproval(data) {
    const id = `approval-${Number(data.approval_id)}`;
    if (document.getElementById(id)) {
        document.getElementById(id).scrollIntoView({block:'nearest'});
        return;
    }
    const args = data.tool_arguments || {};
    const card = document.createElement('div');
    card.id = id;
    card.className = 'approval-card';
    const email = data.tool_name.endsWith('send_email');
    card.innerHTML = `<h3>${email ? 'Review email before sending' : 'Review requested action'}</h3>
        ${email ? `<p><strong>To:</strong> ${escapeHtml(args.to)}</p><p><strong>Subject:</strong> ${escapeHtml(args.subject)}</p><pre>${escapeHtml(args.body)}</pre>` : `<pre>${escapeHtml(JSON.stringify(args, null, 2))}</pre>`}
        <div class="approval-actions"><button type="button" class="action-btn">${email ? 'Approve & send' : 'Approve action'}</button><button type="button" class="action-btn">Reject</button></div>`;
    const buttons = card.querySelectorAll('button');
    buttons[0].addEventListener('click', () => handleApproval(buttons[0], data.session_id, data.approval_id, true));
    buttons[1].addEventListener('click', () => handleApproval(buttons[1], data.session_id, data.approval_id, false));
    document.getElementById('chatMessages').append(card);
    card.scrollIntoView({block:'nearest'});
}

async function restoreApprovals(sessionId) {
    const res = await fetch(`${API_URL}/query/pending-approvals?session_id=${encodeURIComponent(sessionId)}`, {headers:{'Authorization':`Bearer ${currentToken}`}});
    if (res.ok && currentSessionId === sessionId) (await res.json()).forEach(renderApproval);
}

async function handleApproval(btnEl, sessionId, approvalId, approved) {
    const parentDiv = btnEl.parentElement;
    parentDiv.innerHTML = `<span style="font-size:12px; color:var(--text-muted);">⏳ Processing ${approved ? 'Approval' : 'Rejection'}...</span>`;
    
    try {
        const res = await fetch(`${API_URL}/query/approve`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentToken}`
            },
            body: JSON.stringify({ session_id: sessionId, approval_id: approvalId, approved })
        });
        
        const data = await res.json();
        if (res.ok) {
            loadTickets();
            loadNotifications();
            parentDiv.innerHTML = `<span style="font-size:12px; color:${approved ? 'var(--accent-emerald)' : 'var(--accent-rose)'}; font-weight:600;">
                ${approved ? '✅ Action Approved & Executed' : '🚫 Action Cancelled'}
            </span>`;
            if (currentSessionId === sessionId) {
                addMessage(data.answer, 'assistant', false, 'tool_execution');
                await saveMessage('assistant', data.answer, false);
            }
            showToast(approved ? 'Action executed' : 'Action cancelled', approved ? 'success' : 'warning');
        } else {
            parentDiv.innerHTML = `<span style="font-size:12px; color:var(--accent-rose);">❌ Approval Failed: ${escapeHtml(data.error || data.detail)}</span>`;
        }
    } catch(e) {
        parentDiv.innerHTML = `<span style="font-size:12px; color:var(--accent-rose);">❌ Connection error during approval</span>`;
    }
}

function addMessage(content, role, isHtml = false, mode = null, source = null, fileUsed = null) {
    const container = document.getElementById('chatMessages');
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    if (mode === 'image_troubleshooting') msg.classList.add('image-analysis');
    
    const avatar = role === 'assistant' ? '<svg class="icon" aria-hidden="true"><use href="#i-spark"/></svg>' : escapeHtml((currentUser || 'U').slice(0, 1).toUpperCase());
    const formattedContent = isHtml ? parseMarkdown(content) : escapeHtml(content);

    let tagsHtml = '';
    if (mode || source || fileUsed || role === 'assistant') {
        tagsHtml = '<div class="tag-container" style="display:flex; align-items:center; gap:6px; flex-wrap:wrap; margin-top:6px;">';
        if (mode) tagsHtml += `<span class="mode-tag">${escapeHtml(mode)}</span>`;
        if (source) tagsHtml += `<span class="source-tag">${escapeHtml(source)}</span>`;
        if (fileUsed) tagsHtml += `<span class="file-tag">📁 ${escapeHtml(fileUsed)}</span>`;
        if (role === 'assistant') tagsHtml += `<span class="smart-badge">⚡ AI Assistant</span>`;
        tagsHtml += '</div>';
    }

    msg.innerHTML = `
        <div class="message-avatar">${avatar}</div>
        <div class="message-body">
            <div class="message-content">${formattedContent}</div>
            ${tagsHtml}
        </div>
    `;

    container.appendChild(msg);
    container.scrollTop = container.scrollHeight;
}

let typingInterval = null;

function showTyping(initialText = 'Generating response & processing data...') {
    hideTyping();
    const container = document.getElementById('chatMessages');
    const typing = document.createElement('div');
    typing.id = 'typingIndicator';
    typing.className = 'message assistant';
    typing.innerHTML = `
        <div class="message-avatar"><svg class="icon" aria-hidden="true"><use href="#i-spark"/></svg></div>
        <div class="message-body">
            <div class="message-content" style="display:flex; align-items:center; gap:12px; background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.08); padding:12px 18px; border-radius:14px; backdrop-filter:blur(8px);">
                <div class="typing"><span></span><span></span><span></span></div>
                <span id="typingStatusText" style="color:var(--accent-indigo); font-size:13px; font-weight:600; font-family:'Plus Jakarta Sans',sans-serif; letter-spacing:0.3px;">${escapeHtml(initialText)}</span>
            </div>
        </div>
    `;
    container.appendChild(typing);
    container.scrollTop = container.scrollHeight;

    const statuses = [
        '📊 Processing dataset & inspecting columns...',
        '🤖 Executing Python data engine...',
        '📈 Rendering dark-mode visualization...',
        '✨ Formatting final insights...'
    ];
    let step = 0;
    typingInterval = setInterval(() => {
        const textEl = document.getElementById('typingStatusText');
        if (textEl && step < statuses.length) {
            textEl.textContent = statuses[step];
            step++;
        }
    }, 2000);
}

function hideTyping() {
    if (typingInterval) {
        clearInterval(typingInterval);
        typingInterval = null;
    }
    document.getElementById('typingIndicator')?.remove();
}

async function startNewChat() {
    clearChatImage();
    try {
        const res = await fetch(`${API_URL}/chat/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            const data = await res.json();
            currentSessionId = data.session_id || data.id;
        }
    } catch(e) {}

    renderWelcome();
    switchTab('chat');
    await loadChatHistory();
    showToast('New session started', 'info');
}

// Chat sessions & history
async function saveMessage(role, content, isHtml = false) {
    if (!currentSessionId) {
        try {
            const res = await fetch(`${API_URL}/chat/sessions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentToken}` }
            });
            if (res.ok) {
                const data = await res.json();
                currentSessionId = data.session_id || data.id;
            }
        } catch(e) {}
    }

    if (currentSessionId) {
        try {
            await fetch(`${API_URL}/chat/sessions/${currentSessionId}/messages`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentToken}` },
                body: JSON.stringify({ role, content, is_html: isHtml })
            });
            loadChatHistory();
        } catch(e) {}
    }
}

async function loadChatHistory(autoLoadLatest = false) {
    const list = document.getElementById('chatHistoryList');
    if (!list) return;
    try {
        const res = await fetch(`${API_URL}/chat/sessions`, {
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (!res.ok) return;
        const sessions = await res.json();
        
        if (sessions.length === 0) {
            list.innerHTML = '<span class="sidebar-empty">No conversations yet</span>';
        } else {
            list.innerHTML = sessions.map(s => `
                <div class="chat-history-item ${s.id === currentSessionId ? 'active' : ''}">
                    <button type="button" class="chat-session-open" onclick="loadSessionMessages(${s.id})" title="${escapeHtml(s.title)}"><span aria-hidden="true">💬</span><span class="chat-title">${escapeHtml(s.title)}</span></button>
                    <button type="button" class="chat-delete" onclick="deleteChatSession(${s.id})" aria-label="Delete conversation: ${escapeHtml(s.title)}" title="Delete conversation">×</button>
                </div>
            `).join('');

            if (autoLoadLatest && !currentSessionId && sessions.length > 0) {
                loadSessionMessages(sessions[0].id);
            }
        }
    } catch(e) {}
}

function filterChatHistory() {
    const query = document.getElementById('chatSearchInput')?.value.toLowerCase() || '';
    const items = document.querySelectorAll('.chat-history-item');
    items.forEach(item => {
        const text = item.textContent.toLowerCase();
        item.style.display = text.includes(query) ? 'flex' : 'none';
    });
}

async function loadSessionMessages(sessionId) {
    clearChatImage();
    currentSessionId = sessionId;
    const listItems = document.querySelectorAll('.chat-history-item');
    listItems.forEach(el => el.classList.remove('active'));
    
    const container = document.getElementById('chatMessages');
    container.innerHTML = '';
    
    try {
        const res = await fetch(`${API_URL}/chat/sessions/${sessionId}/messages`, {
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            const messages = await res.json();
            if (messages.length === 0) {
                container.innerHTML = `<div style="text-align:center; padding:40px; color:var(--text-muted);">Empty Conversation</div>`;
            } else {
                messages.forEach(m => {
                    addMessage(m.content, m.role, m.is_html);
                });
            }
        }
        await restoreApprovals(sessionId);
        await loadChatHistory();
    } catch(e) {
        showToast('Error loading session messages', 'error');
    }
}

async function deleteChatSession(sessionId) {
    if (!confirm('Delete this conversation?')) return;
    try {
        const res = await fetch(`${API_URL}/chat/sessions/${sessionId}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            if (currentSessionId === sessionId) {
                currentSessionId = null;
                await loadChatHistory(true);
                if (!currentSessionId) startNewChat();
            } else {
                loadChatHistory();
            }
            showToast('Conversation deleted', 'info');
        }
    } catch(e) {}
}

// File upload & data files
document.getElementById('fileInput')?.addEventListener('change', async (e) => {
    for (let f of e.target.files) await uploadFile(f);
    e.target.value = '';
});

async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    showToast(`Uploading ${file.name}...`, 'info');
    
    try {
        const res = await fetch(`${API_URL}/upload`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${currentToken}` },
            body: formData
        });
        if (res.ok) {
            const data = await res.json();
            showToast(`${file.name} uploaded successfully!`, 'success');
            await loadDataFiles();
            onBIDatasetChange();
        } else {
            const err = await res.json();
            showToast(`Upload failed: ${err.detail || 'Unknown error'}`, 'error');
        }
    } catch (e) {
        showToast(`Upload failed: Connection error`, 'error');
    }
}

async function loadDataFiles(overrideSelectedFile = null) {
    const list = document.getElementById('dataFilesList');
    const biSelect = document.getElementById('biDatasetSelect');
    if (!list) return;
    try {
        const res = await fetch(`${API_URL}/data/files`, { headers: { 'Authorization': `Bearer ${currentToken}` } });
        if (!res.ok) return;
        const files = await res.json();
        
        if (files.length === 0) {
            list.innerHTML = '<span class="sidebar-empty">No files uploaded</span>';
            if (biSelect) biSelect.innerHTML = '<option value="">📂 No Datasets Uploaded</option>';
            
            const revEl = document.getElementById('bi-kpi-revenue');
            const recEl = document.getElementById('bi-kpi-records');
            const riskEl = document.getElementById('bi-kpi-risk');
            if (revEl) revEl.textContent = '$0.00';
            if (recEl) recEl.textContent = '0 Records';
            if (riskEl) {
                riskEl.textContent = 'No Active Datasets';
                riskEl.style.color = 'var(--text-muted)';
            }

            const chartContainer = document.getElementById('biChartContainer');
            const chartTitle = document.getElementById('bi-chart-title');
            if (chartTitle) chartTitle.textContent = 'Executive Analytics Visualization';
            if (chartContainer) {
                chartContainer.innerHTML = `
                    <div style="color:var(--text-muted); text-align:center; padding:60px;">
                        <div style="font-size:42px; margin-bottom:12px;">📂</div>
                        <div style="font-size:15px; color:var(--text-main); font-weight:600;">No Datasets Uploaded</div>
                        <div style="font-size:13px; color:var(--text-muted); margin-top:6px;">Upload a CSV, Excel, or PDF document to unlock real-time BI analytics, Benford fraud audits & charts.</div>
                    </div>
                `;
            }
        } else {
            if (biSelect) {
                const prevVal = biSelect.value;
                biSelect.innerHTML = files.map((f, idx) => {
                    const badge = '';
                    return `<option value="${escapeHtml(f.filename)}">${f.type === 'pdf' ? '📄' : '📊'} ${escapeHtml(f.filename)}${badge}</option>`;
                }).join('');
                
                const targetFile = overrideSelectedFile || (files.some(f => f.filename === prevVal) ? prevVal : files[0].filename);
                biSelect.value = targetFile;
            }
        }
        updateWorkspaceFiles(files);
        updateMeetingFiles(files);
    } catch(e) {}
}

async function onBIDatasetChange() {
    const biSelect = document.getElementById('biDatasetSelect');
    if (!biSelect || !biSelect.value) return;
    const selectedFile = biSelect.value;
    showToast(`BI Studio synced to: ${selectedFile}`, 'info');
    
    try {
        const res = await fetch(`${API_URL}/data/summary/${encodeURIComponent(selectedFile)}`, {
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            const data = await res.json();
            const revEl = document.getElementById('bi-kpi-revenue');
            const recEl = document.getElementById('bi-kpi-records');
            const riskEl = document.getElementById('bi-kpi-risk');
            
            if (revEl) revEl.textContent = data.revenue || 'N/A';
            if (recEl) recEl.textContent = data.records || '0 Records';
            currentBISummary = { ...data, filename: selectedFile };
            renderCalculationDetails(data.explanation, selectedFile);
            currentBIChartBase64 = '';
            if (riskEl) {
                riskEl.textContent = data.risk_status || 'Not assessed';
                riskEl.style.color = data.risk_color || '#10b981';
            }

            const solBox = document.getElementById('biSolutionsBox');
            const solList = document.getElementById('biSolutionsList');
            if (solBox && solList) {
                if (data.solutions && data.solutions.length > 0) {
                    solList.innerHTML = data.solutions.map(s => `<div style="padding:4px 0;">${escapeHtml(s)}</div>`).join('');
                    solBox.style.display = 'block';
                } else {
                    solBox.style.display = 'none';
                }
            }
        }
    } catch(e) {}

    if (typeof changeBIChart === 'function') {
        changeBIChart('bar');
    }
}

function printRemediationBriefing() {
    const biSelect = document.getElementById('biDatasetSelect');
    const selectedFile = biSelect ? biSelect.value : 'Dataset';
    const solList = document.getElementById('biSolutionsList');
    const solutionsHtml = solList ? solList.innerHTML : 'No active action items.';

    const win = window.open('', '_blank');
    win.document.write(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>Client Forensic Action Plan — ${escapeHtml(selectedFile)}</title>
            <style>
                body { font-family: 'Segoe UI', system-ui, sans-serif; padding: 40px; color: #0f172a; max-width: 800px; margin: 0 auto; }
                h1 { font-size: 24px; color: #4f46e5; border-bottom: 2px solid #e2e8f0; padding-bottom: 12px; }
                .subtitle { font-size: 14px; color: #64748b; margin-bottom: 24px; }
                .card { background: #f8fafc; border: 1px solid #cbd5e1; border-radius: 8px; padding: 20px; margin-bottom: 24px; }
                .card-title { font-size: 16px; font-weight: 700; color: #0f172a; margin-bottom: 12px; }
                .solution-item { font-size: 14px; padding: 8px 0; border-bottom: 1px solid #e2e8f0; }
                .solution-item:last-child { border-bottom: none; }
                .footer { font-size: 12px; color: #94a3b8; margin-top: 40px; text-align: center; border-top: 1px solid #e2e8f0; padding-top: 16px; }
            </style>
        </head>
        <body>
            <h1>📊 Client Forensic Action Plan & Remediation</h1>
            <div class="subtitle">Dataset Focus: <strong>${escapeHtml(selectedFile)}</strong> | Generated: ${new Date().toLocaleString()}</div>
            
            <div class="card">
                <div class="card-title">💡 Recommended Executive Action Items</div>
                ${solutionsHtml}
            </div>

            <div class="footer">
                Generated by AI Employee Assistant
            </div>
            <script>window.onload = function() { window.print(); }</script>
        </body>
        </html>
    `);
    win.document.close();
}

async function cleanDatasetOutliers() {
    const biSelect = document.getElementById('biDatasetSelect');
    if (!biSelect || !biSelect.value) return;
    const selectedFile = biSelect.value;
    showToast(`Cleaning extreme outliers in ${selectedFile}...`, 'info');
    
    try {
        const res = await fetch(`${API_URL}/data/clean/${encodeURIComponent(selectedFile)}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            const data = await res.json();
            showToast(data.message || 'Outliers cleaned successfully!', 'success');
            await loadDataFiles(data.cleaned_filename);
            onBIDatasetChange();
        } else {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.error || errData.detail || 'Failed to clean dataset.';
            showToast(errMsg, 'error');
        }
    } catch(e) {
        showToast('Connection error during dataset cleaning.', 'error');
    }
}

async function openRLModal() {
    const modal = document.getElementById('rlModal');
    const container = document.getElementById('rlPolicyContainer');
    if (!modal || !container) return;

    modal.style.display = 'flex';
    container.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:20px;">Loading response-routing feedback...</div>';

    try {
        const res = await fetch(`${API_URL}/rl/stats`, {
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            const data = await res.json();
            const policy = data.policy || {};
            const keys = Object.keys(policy);

            if (keys.length === 0) {
                container.innerHTML = '<div style="color:var(--text-muted); text-align:center; padding:20px;">RL policy initialized. Awaiting user interaction queries.</div>';
                return;
            }

            container.innerHTML = keys.map(stateKey => {
                const actions = policy[stateKey];
                const bestAction = Object.keys(actions).reduce((a, b) => actions[a] > actions[b] ? a : b);
                return `
                    <div style="background:rgba(15,23,42,0.6); border:1px solid rgba(255,255,255,0.08); border-radius:8px; padding:12px 16px;">
                        <div style="font-size:13px; font-weight:700; color:var(--accent-cyan); margin-bottom:6px;">📌 State Context: ${escapeHtml(stateKey)}</div>
                        <div style="display:flex; flex-direction:column; gap:4px;">
                            ${Object.entries(actions).map(([act, qVal]) => {
                                const isBest = act === bestAction;
                                return `
                                    <div style="display:flex; justify-content:space-between; font-size:12px; color:${isBest ? '#a855f7' : 'var(--text-muted)'}; font-weight:${isBest ? '700' : '400'};">
                                        <span>${isBest ? '👑 ' : ''}${escapeHtml(act)}</span>
                                        <span>Q-Value: ${qVal.toFixed(3)}</span>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                `;
            }).join('');
        }
    } catch(e) {
        container.innerHTML = '<div style="color:var(--accent-pink); text-align:center; padding:20px;">Failed to load RL Policy stats.</div>';
    }
}

function closeRLModal() {
    const modal = document.getElementById('rlModal');
    if (modal) modal.style.display = 'none';
}

async function promoteFilePriority(filename) {
    try {
        const res = await fetch(`${API_URL}/data/files/${encodeURIComponent(filename)}/promote`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            showToast(`Promoted ${filename} to Top Priority #1!`, 'success');
            await loadDataFiles(filename);
            onBIDatasetChange();
        }
    } catch(e) {}
}

async function deleteFile(filename) {
    if (!confirm(`Are you sure you want to delete ${filename}?`)) return;
    try {
        const res = await fetch(`${API_URL}/data/files/${encodeURIComponent(filename)}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            showToast(`Deleted ${filename}`, 'info');
            await loadDataFiles();
            onBIDatasetChange();
        } else {
            showToast(`Failed to delete ${filename}`, 'error');
        }
    } catch (e) {
        showToast('Connection error while deleting file', 'error');
    }
}

// Tickets
function showNewTicket() {
    const el = document.getElementById('newTicketForm');
    el.style.display = el.style.display === 'none' ? 'flex' : 'none';
}

async function createTicket() {
    const sub = document.getElementById('ticketSubject').value.trim();
    const desc = document.getElementById('ticketDesc').value.trim();
    const prio = document.getElementById('ticketPriority').value;
    if (!sub || !desc) return showToast('Please fill out all fields', 'warning');
    
    try {
        const res = await fetch(`${API_URL}/tickets`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentToken}` },
            body: JSON.stringify({subject: sub, description: desc, priority: prio})
        });
        if (res.ok) {
            document.getElementById('ticketSubject').value = '';
            document.getElementById('ticketDesc').value = '';
            showNewTicket();
            loadTickets();
            showToast('Support ticket created!', 'success');
        }
    } catch(e) {
        showToast('Error creating ticket', 'error');
    }
}

async function loadTickets() {
    return loadTicketWorkspace();
}

// Reminders
function showNewReminder() {
    const el = document.getElementById('newReminderForm');
    el.style.display = el.style.display === 'none' ? 'flex' : 'none';
}

async function createReminder() {
    const msg = document.getElementById('reminderMsg').value.trim();
    const due = document.getElementById('reminderDue').value;
    if (!msg) return showToast('Please enter a reminder description', 'warning');
    
    try {
        const res = await fetch(`${API_URL}/reminders`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${currentToken}` },
            body: JSON.stringify({message: msg, due_date: due ? new Date(due).toISOString() : null})
        });
        if (res.ok) {
            document.getElementById('reminderMsg').value = '';
            showNewReminder();
            loadReminders();
            showToast('Reminder created!', 'success');
        }
    } catch(e) {
        showToast('Error creating reminder', 'error');
    }
}

async function loadReminders() {
    try {
        const res = await fetch(`${API_URL}/reminders`, { headers: { 'Authorization': `Bearer ${currentToken}` } });
        if (!res.ok) return;
        const reminders = await res.json();
        const list = document.getElementById('reminderList');
        if (!list) return;
        
        if (reminders.length === 0) {
            list.innerHTML = '<div class="sidebar-empty">No task reminders set</div>';
        } else {
            list.innerHTML = reminders.map(r => `
                <div class="item-card" style="display:flex; justify-content:space-between; align-items:center;">
                    <div>
                        <div style="font-weight:600; font-size:14px;">${escapeHtml(r.message)}</div>
                        <div style="font-size:11px; color:var(--text-muted); margin-top:2px;">Due: ${r.due_date ? new Date(r.due_date).toLocaleString() : 'No date set'}</div>
                    </div>
                    <button class="action-btn" style="background:rgba(244,63,94,0.15); color:var(--accent-rose); border:1px solid rgba(244,63,94,0.3); padding:5px 10px; font-size:11px;" onclick="deleteReminder(${r.id})">Complete</button>
                </div>
            `).join('');
        }
    } catch(e) {}
}

async function deleteReminder(id) {
    try {
        const res = await fetch(`${API_URL}/reminders/${id}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${currentToken}` }
        });
        if (res.ok) {
            loadReminders();
            showToast('Reminder completed', 'info');
        }
    } catch(e) {}
}

// Audit logs
let currentAuditLogs = [];

async function loadAuditLogs() {
    const list = document.getElementById('auditList');
    if (!list) return;
    try {
        const res = await fetch(`${API_URL}/audit-logs`, { headers: { 'Authorization': `Bearer ${currentToken}` } });
        if (!res.ok) {
            const res2 = await fetch(`${API_URL}/audit`, { headers: { 'Authorization': `Bearer ${currentToken}` } });
            if (res2.ok) currentAuditLogs = await res2.json();
        } else {
            currentAuditLogs = await res.json();
        }
        
        renderAuditLogs(currentAuditLogs);
    } catch(e) {
        showToast('Failed to load audit logs', 'error');
    }
}

function renderAuditLogs(logs) {
    const list = document.getElementById('auditList');
    if (!list) return;
    
    if (logs.length === 0) {
        list.innerHTML = '<div class="sidebar-empty">No security audit logs recorded yet</div>';
        return;
    }

    list.innerHTML = logs.map(l => {
        const dateStr = new Date(l.timestamp).toLocaleString();
        const username = l.username || l.user || 'system';
        const action = (l.action || 'action').toUpperCase();
        
        let riskColor = 'var(--accent-cyan)';
        let riskLabel = 'AUDITED';
        if (action.includes('DELETE') || action.includes('REJECT')) {
            riskColor = 'var(--accent-rose)';
            riskLabel = 'HIGH RISK';
        } else if (action.includes('UPLOAD') || action.includes('ANALYZE')) {
            riskColor = 'var(--accent-indigo)';
            riskLabel = 'DATA ACCESS';
        }

        return `
            <div class="item-card audit-log-card" style="padding:14px 18px; border-left:4px solid ${riskColor}; margin-bottom:10px;">
                <div style="font-size:12px; display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                    <div style="display:flex; align-items:center; gap:8px;">
                        <span style="font-weight:700; color:var(--text-main);">👤 ${escapeHtml(username)}</span>
                        <span class="status-pill" style="background:rgba(99,102,241,0.15); color:${riskColor}; border:1px solid ${riskColor}; font-size:10px; padding:2px 8px;">${escapeHtml(action)}</span>
                        <span class="status-pill" style="background:rgba(255,255,255,0.05); color:var(--text-dim); font-size:9px;">${riskLabel}</span>
                    </div>
                    <span style="font-size:11px; color:var(--text-muted); font-family:'JetBrains Mono',monospace;">🕒 ${dateStr}</span>
                </div>
                <div style="font-size:13px; color:var(--text-main); font-family:'JetBrains Mono',monospace; background:rgba(0,0,0,0.25); padding:8px 12px; border-radius:6px; word-break:break-word;">
                    ${escapeHtml(l.details || 'No additional details')}
                </div>
            </div>
        `;
    }).join('');
}

function filterAuditLogs() {
    const query = document.getElementById('auditSearchInput')?.value.toLowerCase() || '';
    const filtered = currentAuditLogs.filter(l => {
        const user = (l.username || l.user || '').toLowerCase();
        const action = (l.action || '').toLowerCase();
        const details = (l.details || '').toLowerCase();
        return user.includes(query) || action.includes(query) || details.includes(query);
    });
    renderAuditLogs(filtered);
}

async function exportAuditLogsCSV() {
    showToast('Preparing audit trail CSV...', 'info');
    
    let logsToExport = currentAuditLogs;
    if (!logsToExport || logsToExport.length === 0) {
        try {
            const res = await fetch(`${API_URL}/audit-logs`, { headers: { 'Authorization': `Bearer ${currentToken}` } });
            if (res.ok) {
                logsToExport = await res.json();
            }
        } catch(e) {}
    }

    if (!logsToExport || logsToExport.length === 0) {
        return showToast('No audit logs available to export', 'warning');
    }
    
    let csv = 'Timestamp,User,Action,Details\n';
    logsToExport.forEach(l => {
        const time = `"${l.timestamp || ''}"`;
        const user = `"${l.username || l.user || 'system'}"`;
        const action = `"${l.action || ''}"`;
        const details = `"${(l.details || '').replace(/"/g, '""')}"`;
        csv += `${time},${user},${action},${details}\n`;
    });

    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = `audit_logs_${new Date().toISOString().slice(0,10)}.csv`;
    
    document.body.appendChild(a);
    a.click();
    
    setTimeout(() => {
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    }, 200);
    
    showToast('Audit CSV report downloaded successfully!', 'success');
}

// Voice dictation
let recognition = null;
let isRecording = false;

function toggleVoiceInput() {
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
        return showToast('Voice dictation not supported in this browser. Use Chrome or Safari.', 'warning');
    }

    const micBtn = document.getElementById('micBtn');
    const input = document.getElementById('questionInput');

    if (isRecording && recognition) {
        recognition.stop();
        isRecording = false;
        if (micBtn) {
            micBtn.style.background = 'rgba(255,255,255,0.06)';
            micBtn.style.color = 'var(--accent-cyan)';
            micBtn.textContent = '🎙️';
        }
        showToast('Voice dictation stopped', 'info');
        return;
    }

    recognition = new SpeechRecognition();
    recognition.continuous = false;
    recognition.interimResults = true;
    recognition.lang = 'en-US';

    recognition.onstart = () => {
        isRecording = true;
        if (micBtn) {
            micBtn.style.background = 'rgba(244,63,94,0.3)';
            micBtn.style.color = 'var(--accent-rose)';
            micBtn.textContent = '⏹️';
        }
        showToast('Listening... Speak your prompt now', 'info');
    };

    recognition.onresult = (event) => {
        let transcript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
            transcript += event.results[i][0].transcript;
        }
        if (input) input.value = transcript;
    };

    recognition.onerror = (event) => {
        isRecording = false;
        if (micBtn) {
            micBtn.style.background = 'rgba(255,255,255,0.06)';
            micBtn.style.color = 'var(--accent-cyan)';
            micBtn.textContent = '🎙️';
        }
        showToast(`Voice error: ${event.error}`, 'error');
    };

    recognition.onend = () => {
        isRecording = false;
        if (micBtn) {
            micBtn.style.background = 'rgba(255,255,255,0.06)';
            micBtn.style.color = 'var(--accent-cyan)';
            micBtn.textContent = '🎙️';
        }
    };

    recognition.start();
}

// Executive deck & fraud watchdog
function getCurrentBIExportData() {
    const biSelect = document.getElementById('biDatasetSelect');
    const datasetName = biSelect && biSelect.value ? biSelect.value : 'Selected dataset';
    const summary = currentBISummary || {};
    const lines = [
        `Dataset: ${datasetName}`,
        `Records: ${summary.records || 'Not available'}`,
        `Calculated value: ${summary.revenue || 'Not available'}`,
        `Statistical review: ${summary.risk_status || 'Not assessed'}`
    ];
    if (typeof currentProfitLoss !== 'undefined' && currentProfitLoss?.filename === datasetName) {
        const result = currentProfitLoss;
        lines.unshift(`Profit / loss assessment: ${result.outcome}; result ${result.profit_loss}; income ${result.revenue}; expenses ${result.expenses}; units ${result.units}`,
            `Financial formula: ${result.formula}`,
            `Reporting scope: ${JSON.stringify(result.filters)}; rows used: ${result.rows_used}`,
            result.note);
    } else {
        lines.unshift('Profit / loss: not assessed. Select and calculate income and expenses in BI Studio.');
    }
    return {
        datasetName,
        summaryText: lines.join('\n'),
        chartBase64: currentBIChartBase64 || ''
    };
}

async function triggerPPTExport() {
    showToast('Generating 5-slide Executive PowerPoint presentation...', 'info');
    try {
        const exportData = getCurrentBIExportData();
        const res = await fetch(`${API_URL}/export-ppt`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentToken}`
            },
            body: JSON.stringify({
                title: `Dataset Analysis: ${exportData.datasetName}`,
                summary_text: exportData.summaryText,
                chart_base64: exportData.chartBase64
            })
        });

        if (!res.ok) throw new Error("Failed to generate PowerPoint deck.");

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `Executive_Briefing_Deck_${new Date().toISOString().slice(0,10)}.pptx`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }, 200);

        showToast('PowerPoint Executive Deck (.pptx) downloaded!', 'success');
    } catch(e) {
        showToast(e.message, 'error');
    }
}

async function runBenfordWatchdog() {
    const biSelect = document.getElementById('biDatasetSelect');
    const selectedFile = biSelect ? biSelect.value : null;

    showToast('Executing Benford\'s Law Forensic Fraud Audit...', 'info');
    try {
        const res = await fetch(`${API_URL}/run-fraud-audit`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentToken}`
            },
            body: JSON.stringify({ file_name: selectedFile })
        });
        const data = await res.json();

        if (data.error) return showToast(data.error, 'warning');

        const kpiRisk = document.getElementById('bi-kpi-risk');
        if (kpiRisk) {
            kpiRisk.textContent = data.risk_level;
            kpiRisk.style.color = data.status_color || '#10b981';
        }

        const chartContainer = document.getElementById('biChartContainer');
        const chartTitle = document.getElementById('bi-chart-title');
        if (chartTitle) chartTitle.textContent = `Forensic Benford's Audit (${selectedFile || 'Dataset'}): ${data.column_audited} (${data.records_audited.toLocaleString()} records)`;

        if (chartContainer && data.chart_base64) {
            currentBIChartBase64 = data.chart_base64;
            chartContainer.innerHTML = `
                <div style="width:100%;">
                    <div style="font-size:13px; color:var(--text-light); margin-bottom:10px; background:rgba(0,0,0,0.3); padding:10px 14px; border-radius:8px;">
                        <b>Verdict:</b> ${escapeHtml(data.verdict)} | <b>MAD Score:</b> ${data.mad_score}
                    </div>
                    <img src="data:image/png;base64,${data.chart_base64}" style="width:100%; border-radius:10px;">
                </div>
            `;
        }

        showToast('Benford\'s Law Fraud Audit completed!', 'success');
    } catch(e) {
        showToast(e.message, 'error');
    }
}

async function changeBIChart(type) {
    const biSelect = document.getElementById('biDatasetSelect');
    const selectedFile = biSelect ? biSelect.value : null;

    if (!selectedFile) {
        return showToast('No dataset selected in Executive BI Studio.', 'warning');
    }

    const chartContainer = document.getElementById('biChartContainer');
    const chartTitle = document.getElementById('bi-chart-title');
    
    const chartLabel = type === 'line' ? 'Line Graph' : type === 'pie' ? 'Pie Chart' : 'Bar Chart';
    if (chartTitle) chartTitle.textContent = `Executive Analytics (${selectedFile}): ${chartLabel}`;
    
    if (chartContainer) {
        chartContainer.innerHTML = `
            <div style="color:var(--text-muted); text-align:center; padding:60px;">
                <div style="font-size:36px; margin-bottom:10px;">⏳</div>
                <div style="font-size:15px; color:var(--text-main);">Generating live Executive ${chartLabel} for <b>${escapeHtml(selectedFile)}</b>...</div>
            </div>
        `;
    }

    try {
        const queryText = `Plot top categories or variables by total value on a ${chartLabel.toLowerCase()}`;

        const res = await fetch(`${API_URL}/analyze`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentToken}`
            },
            body: JSON.stringify({
                filename: selectedFile,
                question: queryText
            })
        });

        if (!res.ok) throw new Error("Failed to generate BI chart visualization.");

        const data = await res.json();
        
        if (chartContainer && (data.chart || data.analysis)) {
            currentBIChartBase64 = data.chart || '';
            const chartImg = data.chart ? `<img src="data:image/png;base64,${data.chart}" style="width:100%; max-height:500px; object-fit:contain; border-radius:12px; border:1px solid rgba(255,255,255,0.08); box-shadow: 0 10px 30px rgba(0,0,0,0.5);">` : '';
            const analysisText = data.analysis ? parseMarkdown(data.analysis) : '';
            const trace = data.explanation;
            const explanationHtml = trace ? `<details class="evidence-details" style="text-align:left;"><summary>How this chart was produced</summary><p>${escapeHtml(trace.method || '')}</p><p>${escapeHtml(trace.notes || '')}</p><pre>${escapeHtml(trace.code || '')}</pre></details>` : '';
            
            chartContainer.innerHTML = `
                <div style="width:100%; text-align:center;">
                    ${analysisText ? `<div style="font-size:13px; color:var(--text-light); margin-bottom:15px; background:rgba(0,0,0,0.3); padding:12px 18px; border-radius:10px; text-align:left; line-height:1.6;">${analysisText}</div>` : ''}
                    ${chartImg}
                    ${explanationHtml}
                </div>
            `;
            showToast(`Loaded Executive ${chartLabel} for ${selectedFile}!`, 'success');
        } else {
            chartContainer.innerHTML = `<div style="color:var(--text-muted); padding:40px;">No chart visualization returned for ${escapeHtml(selectedFile)}.</div>`;
        }
    } catch(e) {
        showToast(e.message, 'error');
        if (chartContainer) {
            chartContainer.innerHTML = `<div style="color:var(--accent-rose); padding:40px;">Error generating visualization: ${escapeHtml(e.message)}</div>`;
        }
    }
}

async function triggerPDFExport() {
    showToast('Generating dataset analysis PDF...', 'info');
    try {
        const exportData = getCurrentBIExportData();
        const res = await fetch(`${API_URL}/export-pdf`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentToken}`
            },
            body: JSON.stringify({
                title: `Dataset Analysis: ${exportData.datasetName}`,
                summary_text: exportData.summaryText,
                chart_base64: exportData.chartBase64,
                dataset_name: exportData.datasetName
            })
        });

        if (!res.ok) throw new Error("Failed to generate PDF Briefing.");

        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `Executive_Audit_Briefing_${new Date().toISOString().slice(0,10)}.pdf`;
        document.body.appendChild(a);
        a.click();
        setTimeout(() => {
            document.body.removeChild(a);
            window.URL.revokeObjectURL(url);
        }, 200);

        showToast('Executive PDF Audit Briefing downloaded!', 'success');
    } catch(e) {
        showToast(e.message, 'error');
    }
}

async function runVarianceAnalysis() {
    const datasetSelect = document.getElementById('biDatasetSelect');
    const selectedFile = datasetSelect ? datasetSelect.value : null;

    const prevSel = document.getElementById('biPrevYearSelect');
    const currSel = document.getElementById('biCurrYearSelect');
    const vsLbl = document.getElementById('biVsLabel');

    const prevYear = prevSel ? prevSel.value : null;
    const currYear = currSel ? currSel.value : null;

    showToast('Executing Period-over-Period Variance Analysis...', 'info');
    try {
        const res = await fetch(`${API_URL}/run-variance-analysis`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${currentToken}`
            },
            body: JSON.stringify({
                file_name: selectedFile,
                prev_year: prevYear,
                curr_year: currYear
            })
        });
        const data = await res.json();

        if (data.error) return showToast(data.error, 'warning');

        if (data.years_available && data.years_available.length >= 2 && prevSel && currSel) {
            prevSel.style.display = 'inline-block';
            currSel.style.display = 'inline-block';
            if (vsLbl) vsLbl.style.display = 'inline-block';

            if (prevSel.options.length === 0) {
                prevSel.innerHTML = data.years_available.map(y => `<option value="${y}">Period ${y}</option>`).join('');
                currSel.innerHTML = data.years_available.map(y => `<option value="${y}">Period ${y}</option>`).join('');
            }
            if (data.period_prev) prevSel.value = data.period_prev;
            if (data.period_curr) currSel.value = data.period_curr;
        }

        const chartContainer = document.getElementById('biChartContainer');
        const chartTitle = document.getElementById('bi-chart-title');
        if (chartTitle) chartTitle.textContent = `Period Variance Analysis (${data.period_prev} vs ${data.period_curr})`;

        if (chartContainer && data.chart_base64) {
            currentBIChartBase64 = data.chart_base64;
            const unit = data.unit_label || '$ Millions';
            const varSign = data.total_variance >= 0 ? '+' : '';
            const pctSign = data.total_pct_change >= 0 ? '+' : '';
            
            chartContainer.innerHTML = `
                <div style="width:100%; text-align:center;">
                    <div style="font-size:13px; color:var(--text-light); margin-bottom:12px; background:rgba(0,0,0,0.3); padding:10px 16px; border-radius:10px; text-align:left;">
                        <b>Total Variance Growth:</b> ${varSign}$${data.total_variance.toLocaleString()} (${unit}) (${pctSign}${data.total_pct_change}%) | <b>Period ${data.period_curr}:</b> $${data.total_curr.toLocaleString()} (${unit})
                    </div>
                    <img src="data:image/png;base64,${data.chart_base64}" style="width:100%; max-height:500px; object-fit:contain; border-radius:12px; border:1px solid rgba(255,255,255,0.08); box-shadow: 0 10px 30px rgba(0,0,0,0.5);">
                </div>
            `;
        }

        showToast(`Variance Analysis loaded (${data.period_prev} vs ${data.period_curr})!`, 'success');
    } catch(e) {
        showToast(e.message, 'error');
    }
}

document.addEventListener('DOMContentLoaded', init);
