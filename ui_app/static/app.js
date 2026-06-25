// TAIA Chat Application
const CFG = window.TAIA_CONFIG || {};
const API = CFG.AI_API_URL || 'http://127.0.0.1:8000';
const ERP_AUTH_URL = '/api/v1/auth/login';
let token = null;
let sessionId = null;
let currentRole = 'student';
let currentUserId = null;

// Configure Marked.js for safe markdown rendering
if (typeof marked !== 'undefined') {
    marked.setOptions({
        breaks: true,
        gfm: true
    });
}

const quickQ = {
    student: [
        "What is my attendance?",
        "What assignments are pending?",
        "What is my GPA?",
        "Show my fee status",
        "Show my registered courses",
        "Show my timetable",
        "Generate a study plan",
    ],
    faculty: [
        "Which students have low attendance?",
        "Which assignments are ungraded?",
        "Which students are at risk of failing?",
        "Show course performance statistics",
        "What are the examination rules?",
    ],
    admin: [
        "Show overall university statistics",
        "Show department-wise student count",
        "Show admission statistics",
        "Which students are at risk?",
        "Show fee collection status",
    ],
    finance: [
        "Show fee collection summary",
        "Which students have pending fees?",
        "Show department-wise fee stats",
        "Show scholarship statistics",
        "Show financial summary",
    ],
    exam_officer: [
        "Show upcoming exam schedule",
        "Which students are at risk of failing?",
        "Show course performance statistics",
        "Show ungraded assignments",
        "What are the examination rules?",
    ],
};

function updateDefaultId() {
    const role = document.getElementById('userRole').value;
    const input = document.getElementById('userId');
    const rolePrefixes = {
        'student': 'STU-0001',
        'faculty': 'FAC-0001',
        'admin': 'ADM-0001',
        'finance': 'FIN-0001',
        'exam_officer': 'EXM-0001'
    };
    
    if (rolePrefixes[role]) {
        input.value = rolePrefixes[role];
        input.placeholder = `e.g. ${rolePrefixes[role]}`;
    }
}
// Theme Management
function initTheme() {
    const savedTheme = localStorage.getItem('theme') || 'light';
    document.documentElement.setAttribute('data-theme', savedTheme);
    updateThemeIcon(savedTheme);
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const target = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', target);
    localStorage.setItem('theme', target);
    updateThemeIcon(target);
}

function updateThemeIcon(theme) {
    const btn = document.getElementById('themeToggleBtn');
    if (theme === 'dark') {
        btn.innerHTML = '<i class="fas fa-sun"></i> Light Mode';
    } else {
        btn.innerHTML = '<i class="fas fa-moon"></i> Dark Mode';
    }
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    initTheme();
    const textarea = document.getElementById('msgInput');
    textarea.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value === '') {
            this.style.height = 'auto';
        }
    });
    restoreSessionIfLoggedIn();
});

function authHeaders() {
    return {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + token,
    };
}

function formatHistoryTime(ts) {
    if (!ts) return '';
    const d = new Date(ts * 1000);
    const now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    if (sameDay) {
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    }
    return d.toLocaleDateString([], { month: 'short', day: 'numeric' });
}

function getChatMessagesEl() {
    return document.getElementById('chat-messages');
}

function getHistoryListEl() {
    return document.getElementById('chat-history-list');
}

async function loadChatHistory() {
    const listEl = getHistoryListEl();
    const historySection = document.getElementById('chatHistory');
    if (!token || !currentUserId || !listEl) return;

    if (historySection) historySection.style.display = 'block';
    listEl.innerHTML = '<li class="history-empty">Loading history...</li>';

    try {
        const r = await fetch(`${API}/api/v1/chat/history/list/${encodeURIComponent(currentUserId)}`, {
            headers: authHeaders(),
        });
        if (!r.ok) {
            const err = await r.json().catch(() => ({}));
            console.error('Chat history list failed:', r.status, err.detail || err);
            renderHistoryList([]);
            return;
        }
        const data = await r.json();
        renderHistoryList(data.sessions || []);
    } catch (err) {
        console.error('Chat history fetch error:', err);
        renderHistoryList([]);
    }
}

function renderHistoryList(sessions) {
    const listEl = getHistoryListEl();
    if (!listEl) return;

    listEl.innerHTML = '';
    if (!sessions.length) {
        listEl.innerHTML = '<li class="history-empty">No history available</li>';
        return;
    }

    sessions.forEach((s) => {
        const li = document.createElement('li');
        li.className = 'history-item' + (s.session_id === sessionId ? ' active' : '');
        li.dataset.sessionId = s.session_id;
        li.innerHTML = `
            <div class="history-item-title">${escapeHtml(s.title || 'New chat')}</div>
            <div class="history-item-time">${formatHistoryTime(s.timestamp)}</div>
        `;
        li.onclick = () => loadChatSession(s.session_id);
        listEl.appendChild(li);
    });
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function loadChatSession(targetSessionId) {
    if (!token || !currentUserId || !targetSessionId) return;

    sessionId = targetSessionId;
    localStorage.setItem('taia_session_id', sessionId);

    const msgs = getChatMessagesEl();
    msgs.innerHTML = '<div class="welcome-msg"><p class="subtitle">Loading conversation...</p></div>';

    try {
        const r = await fetch(
            `${API}/api/v1/chat/history/${currentUserId}?session_id=${encodeURIComponent(targetSessionId)}`,
            { headers: authHeaders() }
        );
        if (!r.ok) throw new Error('Failed to load session');
        const data = await r.json();
        renderLoadedMessages(data.messages || []);
        highlightActiveHistoryItem(targetSessionId);
    } catch (_) {
        msgs.innerHTML = '';
        addMsg('assistant', 'Could not load this conversation. Please try again.');
    }
}

function renderLoadedMessages(messages) {
    const msgs = getChatMessagesEl();
    msgs.innerHTML = '';
    if (!messages.length) {
        addMsg('assistant', 'This conversation is empty. Send a message to continue.');
        return;
    }
    messages.forEach((m) => {
        addMsg(m.role === 'user' ? 'user' : 'assistant', m.content, null, false);
    });
    scrollToBottom();
}

function highlightActiveHistoryItem(activeId) {
    document.querySelectorAll('.history-item').forEach((el) => {
        el.classList.toggle('active', el.dataset.sessionId === activeId);
    });
}

function afterLoginUI(data, userId, role, skipWelcome = false) {
    token = data.token || token;
    currentRole = role;
    currentUserId = userId;
    sessionId = localStorage.getItem('taia_session_id') || ('sess_' + Date.now());
    localStorage.setItem('taia_jwt', token);
    localStorage.setItem('taia_role', role);
    localStorage.setItem('taia_user_id', userId);
    localStorage.setItem('taia_session_id', sessionId);

    document.getElementById('loginSection').style.display = 'none';
    document.getElementById('userInfo').style.display = 'block';
    document.getElementById('quickQuestions').style.display = 'block';
    document.getElementById('chatHistory').style.display = 'block';
    document.getElementById('userName').textContent = data.name || userId;
    document.getElementById('userAvatar').textContent = (data.name || userId)[0].toUpperCase();
    document.getElementById('userRoleBadge').textContent = role;
    document.getElementById('msgInput').disabled = false;
    document.getElementById('sendBtn').disabled = false;

    const list = document.getElementById('questionsList');
    list.innerHTML = '';
    (quickQ[role] || quickQ.student).forEach(q => {
        const btn = document.createElement('button');
        btn.className = 'qq-btn';
        btn.innerHTML = `<i class="far fa-comment"></i> ${q}`;
        btn.onclick = () => { document.getElementById('msgInput').value = q; sendMessage(); };
        list.appendChild(btn);
    });

    const msgs = getChatMessagesEl();
    msgs.innerHTML = '';
    if (!skipWelcome) {
        const roleHints = {
            student: 'attendance, results, GPA, fees, timetable, assignments, or study plans',
            faculty: 'course attendance, ungraded assignments, at-risk students, or course performance',
            admin: 'university statistics, admissions, fee collection, or department performance',
            finance: 'fee collection, pending fees, scholarships, or financial summaries',
            exam_officer: 'exam schedules, course performance, at-risk students, or examination rules',
        };
        const hint = roleHints[role] || roleHints.student;
        addMsg('assistant', `Hello ${data.name || userId}! I'm TAIA, your Academic AI Assistant.\n\nYou can ask me about ${hint}.`);
    }

    loadChatHistory();
}

async function restoreSessionIfLoggedIn() {
    const savedToken = localStorage.getItem('taia_jwt');
    const savedUserId = localStorage.getItem('taia_user_id');
    const savedRole = localStorage.getItem('taia_role');
    if (!savedToken || !savedUserId) return;

    token = savedToken;
    currentUserId = savedUserId;
    currentRole = savedRole || 'student';
    sessionId = localStorage.getItem('taia_session_id') || ('sess_' + Date.now());

    afterLoginUI({ token: savedToken, name: savedUserId }, savedUserId, currentRole, true);

    const savedSession = localStorage.getItem('taia_session_id');
    if (savedSession) {
        await loadChatSession(savedSession);
    } else {
        const roleHints = {
            student: 'attendance, results, GPA, fees, timetable, assignments, or study plans',
            faculty: 'course attendance, ungraded assignments, at-risk students, or course performance',
            admin: 'university statistics, admissions, fee collection, or department performance',
            finance: 'fee collection, pending fees, scholarships, or financial summaries',
            exam_officer: 'exam schedules, course performance, at-risk students, or examination rules',
        };
        const hint = roleHints[currentRole] || roleHints.student;
        addMsg('assistant', `Welcome back! Ask me about ${hint}.`);
    }
}

async function login() {
    const userId = document.getElementById('userId').value.trim();
    const role = document.getElementById('userRole').value;
    const loginBtn = document.querySelector('.btn-login');
    
    if (!userId) { alert('Enter a User ID'); return; }

    const originalBtnText = loginBtn.innerHTML;
    loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Logging in...';
    loginBtn.disabled = true;
    loginBtn.style.opacity = '0.7';

    const errDiv = document.getElementById('loginError');
    if (errDiv) errDiv.style.display = 'none';

    const loginPayload = { user_id: userId, role: role };

    try {
        const r = await fetch(ERP_AUTH_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(loginPayload),
        });

        let data;
        try {
            data = await r.json();
        } catch (parseErr) {
            console.error('Invalid JSON response:', parseErr);
            throw new Error('Invalid response from ERP server');
        }

        if (!r.ok) {
            throw new Error(data.detail || data.message || 'Login failed');
        }

        token = data.token;
        sessionId = 'sess_' + Date.now();
        localStorage.setItem('taia_session_id', sessionId);
        afterLoginUI(data, userId, role);
    } catch (error) {
        console.error('Network error: ', error);
        errDiv.style.display = 'block';
        const isNetworkError =
            error instanceof TypeError ||
            (error.message && error.message.toLowerCase().includes('failed to fetch'));
        errDiv.innerHTML = isNetworkError
            ? '<i class="fas fa-exclamation-circle"></i> Cannot connect to the ERP server. Please make sure it is running (<code>docker compose up -d erp</code>).'
            : `<i class="fas fa-exclamation-circle"></i> Login failed: ${error.message}`;
    } finally {
        loginBtn.innerHTML = originalBtnText;
        loginBtn.disabled = false;
        loginBtn.style.opacity = '1';
    }
}

function logout() {
    token = null;
    sessionId = null;
    currentUserId = null;
    localStorage.removeItem('taia_jwt');
    localStorage.removeItem('taia_role');
    localStorage.removeItem('taia_user_id');
    localStorage.removeItem('taia_session_id');
    document.getElementById('loginSection').style.display = 'block';
    document.getElementById('userInfo').style.display = 'none';
    document.getElementById('quickQuestions').style.display = 'none';
    document.getElementById('chatHistory').style.display = 'none';
    const historyList = getHistoryListEl();
    if (historyList) historyList.innerHTML = '<li class="history-empty">No history available</li>';
    document.getElementById('msgInput').disabled = true;
    document.getElementById('sendBtn').disabled = true;
    
    getChatMessagesEl().innerHTML = `
        <div class="welcome-msg">
            <div class="logo-large"><i class="fas fa-graduation-cap"></i></div>
            <h2>How can I help you today?</h2>
            <p class="subtitle">Login from the sidebar to access your personalized academic dashboard.</p>
        </div>
    `;
}

function startNewChat() {
    if (!token) {
        alert("Please login first.");
        return;
    }
    sessionId = 'sess_' + Date.now();
    localStorage.setItem('taia_session_id', sessionId);
    getChatMessagesEl().innerHTML = '';
    addMsg('assistant', "I've started a new conversation. How can I help you?");
    highlightActiveHistoryItem(null);
}

function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
}

async function sendMessage() {
    const input = document.getElementById('msgInput');
    const msg = input.value.trim();
    if (!msg || !token) return;
    
    input.value = '';
    input.style.height = 'auto'; // reset height
    
    addMsg('user', msg);
    const typing = showTyping();

    try {
        await streamResponse(msg, typing);
    } catch (e) {
        typing.remove();
        let success = false;
        for (let attempt = 1; attempt <= 4; attempt++) {
            await new Promise(res => setTimeout(res, 1500 * attempt));
            const retryTyping = showTyping();
            try {
                await streamResponse(msg, retryTyping);
                success = true;
                break;
            } catch (_) {
                retryTyping.remove();
                try {
                    await normalResponse(msg);
                    success = true;
                    break;
                } catch (__) {
                    // next attempt
                }
            }
        }
        if (!success) {
            addMsg('assistant', `**Connection Error:** Make sure all three services are running.\n\nUI: \`python ui_app/app.py\` (port 5000)\nAI Service: \`uvicorn app.main:app --reload --host 127.0.0.1 --port 8000\`\nMock ERP: \`uvicorn mock_erp.main:app --reload --host 127.0.0.1 --port 8801\`\n\nOr run \`npm run dev\` from the project root.`);
        }
    }
    loadChatHistory();
    highlightActiveHistoryItem(sessionId);
}

async function streamResponse(msg, typing) {
    const response = await fetch(`${API}/api/v1/chat/stream`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token,
            'x-session-id': sessionId || '',
        },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
    });

    if (!response.ok) {
        const err = await response.json().catch(() => ({}));
        throw new Error(err.detail || 'Stream request failed');
    }
    if (!response.body) {
        throw new Error('No response body');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let msgDiv = null;
    let contentEl = null;
    let fullText = '';
    let meta = null;
    let streamStarted = false;

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payload = line.slice(6).trim();
            if (payload === '[DONE]') continue;

            let data;
            try {
                data = JSON.parse(payload);
            } catch (_) {
                continue;
            }

            if (data.meta) {
                meta = data.meta;
                continue;
            }

            if (data.text) {
                if (!streamStarted) {
                    typing.remove();
                    const bubble = createAssistantBubble();
                    msgDiv = bubble.wrapper;
                    contentEl = bubble.content;
                    streamStarted = true;
                }
                fullText += data.text;
                contentEl.textContent = fullText;
                scrollToBottom();
            }
        }
    }

    if (!streamStarted) {
        typing.remove();
        throw new Error('Empty stream');
    }

    if (typeof marked !== 'undefined') {
        contentEl.innerHTML = marked.parse(fullText);
    }

    if (meta) {
        const metaDiv = document.createElement('div');
        metaDiv.className = 'msg-meta';
        metaDiv.innerHTML = `<i class="fas fa-info-circle"></i> ${meta.time || ''} | [${meta.intent || 'Unknown'}]`;
        contentEl.appendChild(metaDiv);
    }

    scrollToBottom();
}

async function normalResponse(msg) {
    const r = await fetch(`${API}/api/v1/chat`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + token,
            'x-session-id': sessionId || '',
        },
        body: JSON.stringify({ message: msg, session_id: sessionId }),
    });
    if (r.ok) {
        const data = await r.json();
        addMsg('assistant', data.response, `${data.time || ''} | [${data.intent || 'Unknown'}]`);
    } else {
        const err = await r.json();
        addMsg('assistant', `**Error:** ${err.detail || 'Error processing request'}`);
    }
}

function createAssistantBubble() {
    const msgs = getChatMessagesEl();

    const wrapper = document.createElement('div');
    wrapper.className = 'msg-wrapper assistant';

    const container = document.createElement('div');
    container.className = 'msg-container';

    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar ai-av';
    avatar.innerHTML = '<i class="fas fa-robot"></i>';

    const content = document.createElement('div');
    content.className = 'msg-content';

    container.appendChild(avatar);
    container.appendChild(content);
    wrapper.appendChild(container);
    msgs.appendChild(wrapper);

    scrollToBottom();
    return { wrapper, content };
}

function scrollToBottom() {
    const msgs = getChatMessagesEl();
    if (msgs) msgs.scrollTop = msgs.scrollHeight;
}

function addMsg(type, text, meta, autoScroll = true) {
    const msgs = getChatMessagesEl();
    
    const wrapper = document.createElement('div');
    wrapper.className = `msg-wrapper ${type}`;
    
    const container = document.createElement('div');
    container.className = 'msg-container';
    
    // Avatar
    const avatar = document.createElement('div');
    avatar.className = `msg-avatar ${type === 'user' ? 'user-av' : 'ai-av'}`;
    if (type === 'user') {
        const initial = document.getElementById('userAvatar').textContent || 'U';
        avatar.textContent = initial;
    } else {
        avatar.innerHTML = '<i class="fas fa-robot"></i>';
    }
    
    // Content
    const content = document.createElement('div');
    content.className = 'msg-content';
    
    // Parse markdown for assistant messages, render plain text for user
    if (type === 'assistant' && typeof marked !== 'undefined') {
        content.innerHTML = marked.parse(text);
    } else {
        const p = document.createElement('p');
        p.textContent = text;
        content.appendChild(p);
    }
    
    // Meta info (time, intent)
    if (meta && type === 'assistant') {
        const metaDiv = document.createElement('div');
        metaDiv.className = 'msg-meta';
        metaDiv.innerHTML = `<i class="fas fa-info-circle"></i> ${meta}`;
        content.appendChild(metaDiv);
    }
    
    container.appendChild(avatar);
    container.appendChild(content);
    wrapper.appendChild(container);
    msgs.appendChild(wrapper);
    
    if (autoScroll) scrollToBottom();
}

function showTyping() {
    const msgs = getChatMessagesEl();
    
    const wrapper = document.createElement('div');
    wrapper.className = `msg-wrapper assistant`;
    
    const container = document.createElement('div');
    container.className = 'msg-container';
    
    const avatar = document.createElement('div');
    avatar.className = 'msg-avatar ai-av';
    avatar.innerHTML = '<i class="fas fa-robot"></i>';
    
    const content = document.createElement('div');
    content.className = 'msg-content';
    
    const typing = document.createElement('div');
    typing.className = 'typing';
    typing.innerHTML = '<span></span><span></span><span></span>';
    
    content.appendChild(typing);
    container.appendChild(avatar);
    container.appendChild(content);
    wrapper.appendChild(container);
    msgs.appendChild(wrapper);
    
    scrollToBottom();
    return wrapper;
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}
