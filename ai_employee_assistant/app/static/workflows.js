let workflowPoll = null;
let notificationIds = null;
let activeTicketId = null;
let ticketAssignees = [];

async function workflowRequest(path, options = {}) {
    const response = await fetch(`${API_URL}${path}`, {
        ...options,
        headers: { 'Authorization': `Bearer ${currentToken}`, ...(options.body ? {'Content-Type': 'application/json'} : {}), ...options.headers }
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || data.detail || 'Request failed');
    return data;
}

function workflowError(error) {
    showToast(typeof error.message === 'string' ? error.message : 'Please check the request and retry.', 'error');
}

function startWorkflowPolling() {
    stopWorkflowPolling();
    notificationIds = null;
    loadNotifications();
    workflowPoll = setInterval(() => {
        if (!currentToken) return;
        loadNotifications();
        if (document.getElementById('tab-tickets').classList.contains('active')) loadTickets();
        if (document.getElementById('tab-tasks').classList.contains('active')) loadTasks();
    }, 20000);
}

function stopWorkflowPolling() {
    if (workflowPoll) clearInterval(workflowPoll);
    workflowPoll = null;
    notificationIds = null;
    document.getElementById('notificationCount').textContent = '0';
    document.getElementById('ticketDialog').close();
    activeTicketId = null;
    ticketAssignees = [];
}

function clearWorkflowViews() {
    currentProfitLoss = null;
    profitLossRenderVersion++;
    document.getElementById('biProfitLoss')?.replaceChildren();
    for (const id of ['taskList','notificationList','meetingResult','ticketList','ticketConversation']) document.getElementById(id).replaceChildren();
    for (const id of ['meetingNotes','ticketReply','taskTitle','taskDetails','taskDue','ticketSubject','ticketDesc']) document.getElementById(id).value = '';
    renderWelcome();
    switchTab('chat');
}

async function loadTicketWorkspace() {
    const token = currentToken;
    try {
        const tickets = await workflowRequest('/tickets');
        if (currentRole === 'admin') ticketAssignees = await workflowRequest('/users/assignees');
        if (token !== currentToken) return;
        const list = document.getElementById('ticketList');
        tickets.sort((a, b) => ({high:0, medium:1, low:2}[a.priority] - {high:0, medium:1, low:2}[b.priority]) || b.id - a.id);
        list.innerHTML = tickets.length ? tickets.map(ticket => `
            <article class="item-card workflow-card">
                <div class="item-meta"><span>Ticket #${ticket.id}</span><span class="status-pill pill-${escapeHtml(ticket.priority)}">${escapeHtml(ticket.priority)}</span><span>${escapeHtml(ticket.status)}</span></div>
                <h3>${escapeHtml(ticket.subject)}</h3><p>${escapeHtml(ticket.description)}</p>
                <p class="workflow-hint">Created by ${escapeHtml(ticket.created_by)} · Assigned to ${escapeHtml(ticket.assigned_to || 'Unassigned')}</p>
                <button type="button" class="action-btn" data-ticket-open="${ticket.id}">Conversation & updates</button>
                ${canDeleteTicket(ticket) ? `<button type="button" class="action-btn ticket-delete-btn" data-ticket-delete="${ticket.id}">Delete ticket</button>` : ''}
            </article>`).join('') : '<p class="sidebar-empty">No support tickets yet.</p>';
        list.querySelectorAll('[data-ticket-open]').forEach(button => button.addEventListener('click', () => openTicket(Number(button.dataset.ticketOpen))));
        list.querySelectorAll('[data-ticket-delete]').forEach(button => button.addEventListener('click', () => deleteTicket(Number(button.dataset.ticketDelete), button)));
    } catch (error) { workflowError(error); }
}

async function openTicket(id) {
    try {
        const ticket = await workflowRequest(`/tickets/${id}/conversation`);
        activeTicketId = id;
        const dialog = document.getElementById('ticketDialog');
        document.getElementById('ticketDialogTitle').textContent = `Ticket #${id}: ${ticket.subject}`;
        const conversation = document.getElementById('ticketConversation');
        const statusOptions = ['open','in_progress','resolved','escalated'].map(status => `<option value="${status}" ${status === ticket.status ? 'selected' : ''}>${status.replace('_',' ')}</option>`).join('');
        const assignmentOptions = '<option value="">Unassigned</option>' + ticketAssignees.map(user => `<option value="${escapeHtml(user.username)}" ${user.username === ticket.assigned_to ? 'selected' : ''}>${escapeHtml(user.username)} (${escapeHtml(user.role)})</option>`).join('');
        conversation.innerHTML = `<p class="workflow-prewrap">${escapeHtml(ticket.description)}</p><p class="workflow-hint">${escapeHtml(ticket.status)} · ${escapeHtml(ticket.priority)} priority · Assigned to ${escapeHtml(ticket.assigned_to || 'Unassigned')}</p>
            ${canDeleteTicket(ticket) ? '<button type="button" class="action-btn ticket-delete-btn" id="deleteTicketBtn">Delete ticket</button>' : ''}
            ${currentRole === 'admin' ? `<form id="ticketAdminForm" class="form-card"><label>Status<select id="ticketStatus" class="form-select">${statusOptions}</select></label><label>Assign to<select id="ticketAssignee" class="form-select">${assignmentOptions}</select></label><button class="action-btn" type="submit">Save ticket updates</button></form>` : ''}
            <div class="ticket-replies">${ticket.replies.map(reply => `<article class="workflow-card"><strong>${escapeHtml(reply.username)}</strong><time>${new Date(reply.created_at).toLocaleString()}</time><p class="workflow-prewrap">${escapeHtml(reply.body)}</p></article>`).join('') || '<p class="workflow-hint">No replies yet. Start the conversation below.</p>'}</div>`;
        document.getElementById('ticketAdminForm')?.addEventListener('submit', event => {event.preventDefault();updateTicket(event.target);});
        document.getElementById('deleteTicketBtn')?.addEventListener('click', event => deleteTicket(ticket.id, event.currentTarget));
        if (!dialog.open) {
            document.getElementById('ticketReply').value = '';
            dialog.showModal();
        }
    } catch (error) { workflowError(error); }
}

async function updateTicket(form) {
    const button = form.querySelector('button');
    button.disabled = true;
    try {
        await workflowRequest(`/tickets/${activeTicketId}`, {method:'PUT', body:JSON.stringify({status:document.getElementById('ticketStatus').value, assigned_to:document.getElementById('ticketAssignee').value})});
        await openTicket(activeTicketId);
        loadTickets();
        loadNotifications();
        showToast('Ticket updated', 'success');
    } catch (error) { workflowError(error); }
    finally { button.disabled = false; }
}

async function replyToTicket(form) {
    const input = document.getElementById('ticketReply');
    if (!input.value.trim()) return;
    const button = form.querySelector('button');
    button.disabled = true;
    try {
        await workflowRequest(`/tickets/${activeTicketId}/replies`, {method:'POST', body:JSON.stringify({body:input.value.trim()})});
        input.value = '';
        await openTicket(activeTicketId);
        showToast('Reply sent', 'success');
    } catch (error) { workflowError(error); }
    finally { button.disabled = false; }
}

function addScreenshotTicketAction(question, answer) {
    const card = document.createElement('div');
    card.className = 'workflow-card';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'action-btn';
    button.textContent = 'Create support ticket from this problem';
    button.addEventListener('click', () => {
        switchTab('tickets');
        document.getElementById('newTicketForm').style.display = 'flex';
        document.getElementById('ticketSubject').value = 'Screenshot troubleshooting request';
        document.getElementById('ticketDesc').value = `Employee question:\n${question}\n\nAI troubleshooting suggestions:\n${answer}`.slice(0,10000);
        document.getElementById('ticketSubject').focus();
    });
    card.append(button);
    document.getElementById('chatMessages').append(card);
}

async function loadNotifications() {
    const token = currentToken;
    if (!token) return;
    try {
        const data = await workflowRequest('/notifications');
        if (token !== currentToken) return;
        document.getElementById('notificationCount').textContent = data.unread;
        const list = document.getElementById('notificationList');
        list.innerHTML = data.items.map(item => `<article class="workflow-card ${item.is_read ? '' : 'notification-unread'}"><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.body)}</p><time>${new Date(item.created_at).toLocaleString()}</time><div class="workflow-actions"><button type="button" class="action-btn" data-notification-open="${item.id}">Open ${escapeHtml(item.kind)}</button>${item.is_read ? '' : `<button type="button" class="action-btn secondary" data-notification-read="${item.id}">Mark read</button>`}</div></article>`).join('') || '<p class="sidebar-empty">You are all caught up.</p>';
        list.querySelectorAll('[data-notification-open]').forEach(button => button.addEventListener('click', async () => {
            const item = data.items.find(item => item.id === Number(button.dataset.notificationOpen));
            await markNotificationRead(item.id);
            if (item.kind === 'ticket') {switchTab('tickets'); await loadTickets(); openTicket(item.resource_id);}
            else switchTab(item.kind === 'task' ? 'tasks' : 'reminders');
        }));
        list.querySelectorAll('[data-notification-read]').forEach(button => button.addEventListener('click', () => markNotificationRead(Number(button.dataset.notificationRead))));
        if (notificationIds) {
            for (const item of data.items.filter(item => !item.is_read && !notificationIds.has(item.id))) {
                showToast(`${item.title}: ${item.body}`, 'info');
                if ('Notification' in window && Notification.permission === 'granted' && document.hidden) new Notification(item.title, {body:item.body});
            }
        }
        notificationIds = new Set(data.items.map(item => item.id));
    } catch (error) { /* Retry on the next poll without interrupting ongoing work. */ }
}

async function markNotificationRead(id) {
    try { await workflowRequest(`/notifications/${id}/read`, {method:'PUT'}); await loadNotifications(); }
    catch (error) { workflowError(error); }
}

async function markAllNotificationsRead() {
    try { await workflowRequest('/notifications/read-all', {method:'POST'}); await loadNotifications(); }
    catch (error) { workflowError(error); }
}

async function enableDesktopAlerts() {
    if (!('Notification' in window)) return showToast('This browser does not support desktop alerts.', 'warning');
    const permission = await Notification.requestPermission();
    showToast(permission === 'granted' ? 'Desktop alerts enabled while this workspace is open.' : 'You can still read updates in Notifications.', 'info');
}

async function loadTasks() {
    const token = currentToken;
    try {
        const tasks = await workflowRequest('/tasks');
        if (token !== currentToken) return;
        const list = document.getElementById('taskList');
        list.innerHTML = tasks.map(task => `<article class="workflow-card ${task.is_done ? 'task-complete' : ''}"><h3>${escapeHtml(task.title)}</h3><p class="workflow-prewrap">${escapeHtml(task.details)}</p><p class="workflow-hint">${task.due_date ? `Due ${new Date(task.due_date).toLocaleString()}` : 'No deadline'} · ${escapeHtml(task.source)}</p><div class="workflow-actions"><button type="button" class="action-btn" data-task-toggle="${task.id}">${task.is_done ? 'Reopen' : 'Complete'}</button><button type="button" class="action-btn secondary" data-task-delete="${task.id}">Delete</button></div></article>`).join('') || '<p class="sidebar-empty">No tasks yet. Add one here or ask chat to create a task.</p>';
        list.querySelectorAll('[data-task-toggle]').forEach(button => button.addEventListener('click', async () => {
            const task = tasks.find(task => task.id === Number(button.dataset.taskToggle));
            button.disabled = true;
            try {await workflowRequest(`/tasks/${task.id}`, {method:'PUT',body:JSON.stringify({is_done:!task.is_done})});await loadTasks();}
            catch(error) {workflowError(error);button.disabled=false;}
        }));
        list.querySelectorAll('[data-task-delete]').forEach(button => button.addEventListener('click', async () => {
            button.disabled = true;
            try {await workflowRequest(`/tasks/${button.dataset.taskDelete}`, {method:'DELETE'});await loadTasks();}
            catch(error) {workflowError(error);button.disabled=false;}
        }));
    } catch(error) {workflowError(error);}
}

async function createPersonalTask(form) {
    const button = form.querySelector('button');
    button.disabled = true;
    try {
        const due = document.getElementById('taskDue').value;
        await workflowRequest('/tasks', {method:'POST',body:JSON.stringify({title:document.getElementById('taskTitle').value.trim(),details:document.getElementById('taskDetails').value,due_date:due ? new Date(due).toISOString() : null})});
        form.reset();
        await loadTasks();
        showToast('Task added', 'success');
    } catch(error) {workflowError(error);}
    finally {button.disabled=false;}
}

function updateMeetingFiles(files) {
    const select = document.getElementById('meetingPdf');
    const previous = select.value;
    select.innerHTML = '<option value="">No PDF selected</option>' + files.filter(file => file.filename.toLowerCase().endsWith('.pdf')).map(file => `<option value="${escapeHtml(file.filename)}">${escapeHtml(file.filename)}</option>`).join('');
    if ([...select.options].some(option => option.value === previous)) select.value = previous;
}

async function loadMeetingText(file) {
    if (!file) return;
    if (file.size > 200000 || !/\.(txt|md)$/i.test(file.name)) return showToast('Choose a text or Markdown notes file under 200 KB.', 'warning');
    const text = await file.text();
    if (text.length > 50000) return showToast('Notes must be shorter than 50,000 characters.', 'warning');
    document.getElementById('meetingNotes').value = text;
}

function workflowPlanText(plan) {
    return [plan.summary, ...(plan.decisions || []).map(item => `Decision: ${item}`), ...(plan.tasks || []).map(task => `Suggested task: ${task.title}${task.due_date ? ` — due ${task.due_date}` : ''}`)].join('\n');
}

function renderWorkflowPlan(plan, container) {
    const card = document.createElement('section');
    card.className = 'workflow-card plan-card';
    card.innerHTML = `<h3>${plan.mode === 'meeting_summary' ? 'Meeting summary' : 'Suggested tasks'}</h3><p class="workflow-prewrap">${escapeHtml(plan.summary || '')}</p><h4>Decisions</h4><ul>${(plan.decisions || []).map(item => `<li>${escapeHtml(item)}</li>`).join('') || '<li>No decisions identified.</li>'}</ul><h4>Suggested tasks · review before adding</h4><div class="plan-task-list"></div>`;
    const tasks = card.querySelector('.plan-task-list');
    for (const task of plan.tasks || []) {
        const row = document.createElement('article');
        row.className = 'workflow-card';
        row.innerHTML = `<h4>${escapeHtml(task.title)}</h4><p>${escapeHtml(task.details || '')}</p><p class="workflow-hint">${task.due_date ? `Due ${new Date(task.due_date).toLocaleString()}` : 'No deadline specified'}</p><button type="button" class="action-btn">Add to my tasks</button>`;
        const button = row.querySelector('button');
        button.addEventListener('click', async () => {
            button.disabled = true;
            try {
                await workflowRequest('/tasks', {method:'POST',body:JSON.stringify(task)});
                button.textContent = 'Added to My Tasks';
                showToast('Task added', 'success');
            } catch(error) {workflowError(error);button.disabled=false;}
        });
        tasks.append(row);
    }
    if (!(plan.tasks || []).length) tasks.textContent = 'No actionable tasks identified.';
    container.append(card);
    if (container.id === 'chatMessages') container.scrollTop = container.scrollHeight;
}

async function analyzeMeeting(form) {
    const button = form.querySelector('button');
    button.disabled = true;
    button.textContent = 'Analyzing notes…';
    try {
        const plan = await workflowRequest('/meetings/analyze', {method:'POST',body:JSON.stringify({notes:document.getElementById('meetingNotes').value,filename:document.getElementById('meetingPdf').value || null})});
        const result = document.getElementById('meetingResult');
        result.replaceChildren();
        renderWorkflowPlan(plan, result);
    } catch(error) {workflowError(error);}
    finally {button.disabled=false;button.textContent='Summarize & extract tasks';}
}

let currentProfitLoss = null;
let profitLossRenderVersion = 0;

async function renderProfitLoss(filename) {
    const container = document.getElementById('biProfitLoss');
    if (!container) return;
    const version = ++profitLossRenderVersion;
    currentProfitLoss = null;
    container.replaceChildren();
    try {
        const data = await workflowRequest(`/data/profit-loss/${encodeURIComponent(filename)}`);
        if (version !== profitLossRenderVersion) return;
        const options = columns => columns.map(column => `<option value="${escapeHtml(column)}">${escapeHtml(column)}</option>`).join('');
        container.innerHTML = `<details class="evidence-details"><summary>Profit or loss assessment</summary><p>Select total income and total expenses for the same reporting scope. This calculation does not provide an audit opinion.</p><form id="profitLossForm"><label>Dataset layout<select id="profitLayout" class="form-select"><option value="columns">Revenue and expenses in separate columns</option><option value="rows">Financial measures in labelled rows</option></select></label><div id="profitColumnFields" class="workflow-actions"><label>Revenue / total income<select id="profitRevenue" class="form-select">${options(data.numeric_columns)}</select></label><label>Total expenses<select id="profitExpenses" class="form-select">${options(data.numeric_columns)}</select></label></div><div id="profitRowFields" class="workflow-actions" hidden><label>Financial label column<select id="profitLabel" class="form-select">${options(Object.keys(data.categories))}</select></label><label>Amount column<select id="profitValue" class="form-select">${options(data.numeric_columns)}</select></label><label>Income label<select id="profitIncomeLabel" class="form-select"></select></label><label>Expenditure label<select id="profitExpenseLabel" class="form-select"></select></label></div><h4>Reporting scope</h4><div id="profitFilters" class="workflow-actions"></div><p>Choose one period, industry and size band where applicable. Use complete expenses as positive costs; do not combine totals with their component rows.</p><label><input id="profitConfirm" type="checkbox" required> I have checked that the selected figures cover the same scope and do not overlap.</label><p><button type="submit" class="action-btn">Calculate profit / loss</button></p></form><div id="profitResult" aria-live="polite"></div></details>`;
        const choose = (id, pattern) => {
            const select = document.getElementById(id);
            const match = [...select.options].find(option => pattern.test(option.value));
            if (match) select.value = match.value;
            return Boolean(match);
        };
        choose('profitRevenue', /^(total[ _])?(revenue|income|sales)$/i);
        choose('profitExpenses', /^(total[ _])?(expenses?|expenditure|costs?)$/i);
        choose('profitLabel', /^(variable|measure|description|account)$/i);
        choose('profitValue', /^(value|amount)$/i);
        function refreshFields() {
            currentProfitLoss = null;
            document.getElementById('profitResult').replaceChildren();
            const rows = document.getElementById('profitLayout').value === 'rows';
            document.getElementById('profitColumnFields').hidden = rows;
            document.getElementById('profitColumnFields').style.display = rows ? 'none' : '';
            document.getElementById('profitRowFields').hidden = !rows;
            document.getElementById('profitRowFields').style.display = rows ? '' : 'none';
            const label = document.getElementById('profitLabel').value;
            if (rows) {
                const labels = data.categories[label] || [];
                document.getElementById('profitIncomeLabel').innerHTML = options(labels);
                document.getElementById('profitExpenseLabel').innerHTML = options(labels);
                choose('profitIncomeLabel', /^total income$/i);
                choose('profitExpenseLabel', /^total expenditure$/i);
            }
            const excluded = rows ? [label, document.getElementById('profitValue').value] : [document.getElementById('profitRevenue').value, document.getElementById('profitExpenses').value];
            document.getElementById('profitFilters').innerHTML = Object.entries(data.categories)
                .filter(([column]) => !excluded.includes(column) && (/year|period|industry|size|currency|^units?$/i.test(column) || !data.numeric_columns.includes(column)))
                .map(([column, values]) => `<label>${escapeHtml(column)}<select class="form-select" data-profit-filter="${escapeHtml(column)}"><option value="">All values</option>${options(values)}</select></label>`).join('');
        }
        if (data.columns.some(column => /^variable$/i.test(column)) && data.columns.some(column => /^value$/i.test(column))) document.getElementById('profitLayout').value = 'rows';
        ['profitLayout', 'profitLabel', 'profitValue', 'profitRevenue', 'profitExpenses'].forEach(id => document.getElementById(id).addEventListener('change', refreshFields));
        refreshFields();
        let formRevision = 0;
        document.getElementById('profitLossForm').addEventListener('change', () => {
            formRevision++;
            currentProfitLoss = null;
            document.getElementById('profitResult').replaceChildren();
        });
        document.getElementById('profitLossForm').addEventListener('submit', async event => {
            event.preventDefault();
            const button = event.target.querySelector('button');
            button.disabled = true;
            currentProfitLoss = null;
            const submittedRevision = formRevision;
            const request = {mode:document.getElementById('profitLayout').value,
                revenue_column:document.getElementById('profitRevenue').value, expense_column:document.getElementById('profitExpenses').value,
                label_column:document.getElementById('profitLabel').value, value_column:document.getElementById('profitValue').value,
                income_label:document.getElementById('profitIncomeLabel').value, expense_label:document.getElementById('profitExpenseLabel').value, filters:{}};
            container.querySelectorAll('[data-profit-filter]').forEach(select => {if (select.value !== '') request.filters[select.dataset.profitFilter] = select.value;});
            try {
                const result = await workflowRequest(`/data/profit-loss/${encodeURIComponent(filename)}`, {method:'POST',body:JSON.stringify(request)});
                if (version !== profitLossRenderVersion || submittedRevision !== formRevision) return;
                currentProfitLoss = {filename, ...result};
                const amount = value => Number(value).toLocaleString(undefined, {maximumFractionDigits:2});
                document.getElementById('profitResult').innerHTML = `<h3>${escapeHtml(result.outcome)}: ${amount(result.profit_loss)}</h3><p>Total income: ${amount(result.revenue)} · Total expenses: ${amount(result.expenses)}</p><p>Units: ${escapeHtml(result.units)} · Margin: ${result.margin_percent === null ? 'Not applicable' : amount(result.margin_percent) + '%'}</p><p>Formula: ${escapeHtml(result.formula)}</p><p>Scope: ${escapeHtml(JSON.stringify(result.filters))} · Rows used: ${result.rows_used}</p><p>${escapeHtml(result.note)}</p><p>This result will be included in the next PDF or PowerPoint export.</p>`;
            } catch(error) {workflowError(error);}
            finally {button.disabled = false;}
        });
    } catch(error) {
        if (version === profitLossRenderVersion) container.textContent = 'Profit / loss assessment requires a readable CSV or Excel dataset.';
    }
}

function renderCalculationDetails(data, filename) {
    renderProfitLoss(filename);
    const container = document.getElementById('biCalculationDetails');
    if (!container) return;
    if (!data?.value_column) {container.innerHTML = '<p class="workflow-hint">Numeric calculation details are unavailable for this file.</p>';return;}
    container.innerHTML = `<details class="evidence-details"><summary>Calculation details · ${escapeHtml(data.formula)}</summary><p>File: ${escapeHtml(filename)}</p><p>Rows used: ${data.rows_used} of ${data.rows}; excluded: ${data.rows_excluded}</p><p>Units: ${escapeHtml(data.units)}</p><p>Filters: ${escapeHtml(data.filters)}</p><p>${escapeHtml(data.numeric_cleaning)}</p><ul>${data.warnings.map(item=>`<li>${escapeHtml(item)}</li>`).join('')}</ul><form id="calculationForm" class="workflow-actions"><label>Measure<select id="calculationMeasure" class="form-select">${data.numeric_columns.map(col=>`<option ${col===data.value_column?'selected':''}>${escapeHtml(col)}</option>`).join('')}</select></label><label>Group by<select id="calculationGroup" class="form-select"><option value="">No grouping</option>${data.columns.map(col=>`<option ${col===data.group_column?'selected':''}>${escapeHtml(col)}</option>`).join('')}</select></label><label>Calculation<select id="calculationOperation" class="form-select">${['sum','mean','count','min','max'].map(op=>`<option ${op===data.operation?'selected':''}>${op}</option>`).join('')}</select></label><button class="action-btn" type="submit">Calculate</button></form><p>Result: ${data.result === null ? 'Withheld: incompatible units' : Number(data.result).toLocaleString()}</p>${data.groups?.length ? `<table class="calculation-table"><thead><tr><th>Group</th><th>Value</th></tr></thead><tbody>${data.groups.map(row=>`<tr><td>${escapeHtml(row.group)}</td><td>${Number(row.value).toLocaleString()}</td></tr>`).join('')}</tbody></table>` : ''}</details>`;
    document.getElementById('calculationForm').addEventListener('submit', async event => {
        event.preventDefault();
        const button = event.target.querySelector('button');
        button.disabled = true;
        try {
            const params = new URLSearchParams({value_column:document.getElementById('calculationMeasure').value,operation:document.getElementById('calculationOperation').value});
            if (document.getElementById('calculationGroup').value) params.set('group_column',document.getElementById('calculationGroup').value);
            const result = await workflowRequest(`/data/explanation/${encodeURIComponent(filename)}?${params}`);
            renderCalculationDetails(result, filename);
            container.querySelector('details').open = true;
        } catch(error) {workflowError(error);button.disabled=false;}
    });
}

// Open source PDFs with the account token, then jump to the cited page.
document.addEventListener('click', async event => {
    const button = event.target.closest('[data-document]');
    if (!button) return;
    const viewer = window.open('', '_blank');
    try {
        const response = await fetch(`${API_URL}/documents/${encodeURIComponent(button.dataset.document)}`, {headers:{Authorization:`Bearer ${currentToken}`}});
        if (!response.ok) throw new Error('Could not open this source document.');
        const url = URL.createObjectURL(await response.blob());
        if (viewer) viewer.location = `${url}#page=${Number(button.dataset.page) || 1}`;
        else {URL.revokeObjectURL(url);throw new Error('Allow popups to open source PDFs.');}
        setTimeout(()=>URL.revokeObjectURL(url),60000);
    } catch(error) {viewer?.close();workflowError(error);}
});

function canDeleteTicket(ticket) {
    return ['resolved', 'escalated'].includes(ticket.status) && (currentRole === 'admin' || ticket.created_by === currentUser);
}

async function deleteTicket(id, button) {
    if (!window.confirm(`Permanently delete ticket #${id} and its replies? This cannot be undone.`)) return;
    button.disabled = true;
    try {
        await workflowRequest(`/tickets/${id}`, {method:'DELETE'});
        if (activeTicketId === id) {
            document.getElementById('ticketDialog').close();
            activeTicketId = null;
        }
        await loadTickets();
        await loadNotifications();
        showToast('Ticket deleted', 'success');
    } catch(error) {workflowError(error);button.disabled=false;}
}
