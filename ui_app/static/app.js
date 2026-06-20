// TAIA Chat Application
const API = 'http://localhost:8000';
let token = null;
let sessionId = null;
let currentRole = 'student';

// Configure Marked.js for safe markdown rendering
if (typeof marked !== 'undefined') {
    marked.setOptions({
        breaks: true,
        gfm: true
    });
}

const quickQ = {
    student: [
        "What is my attendance percentage?",
        "What assignments are pending?",
        "What is my GPA?",
        "Show my fee status",
        "Show my registered courses",
        "Show my timetable",
        "Generate a study plan",
        "What is the attendance policy?",
    ],
    faculty: [
        "Which students have low attendance?",
        "Which assignments are ungraded?",
        "Which students are at risk of failure?",
        "Show course performance statistics",
        "What are the examination rules?",
    ],
    admin: [
        "How many total students are enrolled?",
        "Show admission statistics",
        "What is the fee collection status?",
        "Show department performance",
    ],
    finance: [
        "What is the fee collection status?",
        "Show fee statistics",
    ],
    exam_officer: [
        "What are the examination rules?",
        "Show grading policy",
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
    // Auto resize textarea
    const textarea = document.getElementById('msgInput');
    textarea.addEventListener('input', function() {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value === '') {
            this.style.height = 'auto';
        }
    });
});

async function login() {
    const userId = document.getElementById('userId').value.trim();
    const role = document.getElementById('userRole').value;
    const loginBtn = document.querySelector('.btn-login');
    
    if (!userId) { alert('Enter a User ID'); return; }

    const originalBtnText = loginBtn.innerHTML;
    loginBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Waking up Servers (up to 50s)...';
    loginBtn.disabled = true;
    loginBtn.style.opacity = '0.7';

    const errDiv = document.getElementById('loginError');
    if (errDiv) errDiv.style.display = 'none';

    try {
        const r = await fetch(`http://localhost:8001/api/v1/auth/login`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({user_id: userId, role: role}),
        });
        
        const data = await r.json();
        
        if (!r.ok) {
            throw new Error(data.detail || "Login failed");
        }
        
        token = data.token;
        currentRole = role;
        sessionId = 'sess_' + Date.now();
        localStorage.setItem('taia_jwt', token);
        localStorage.setItem('taia_role', role);

        // Update UI
        document.getElementById('loginSection').style.display = 'none';
        document.getElementById('userInfo').style.display = 'block';
        document.getElementById('quickQuestions').style.display = 'block';
        document.getElementById('userName').textContent = data.name || userId;
        document.getElementById('userAvatar').textContent = (data.name || userId)[0].toUpperCase();
        document.getElementById('userRoleBadge').textContent = role;
        document.getElementById('msgInput').disabled = false;
        document.getElementById('sendBtn').disabled = false;

        // Load quick questions
        const list = document.getElementById('questionsList');
        list.innerHTML = '';
        (quickQ[role] || quickQ.student).forEach(q => {
            const btn = document.createElement('button');
            btn.className = 'qq-btn';
            btn.innerHTML = `<i class="far fa-comment"></i> ${q}`;
            btn.onclick = () => { document.getElementById('msgInput').value = q; sendMessage(); };
            list.appendChild(btn);
        });

        // Welcome message
        const msgs = document.getElementById('messages');
        msgs.innerHTML = '';
        addMsg('assistant', `Hello ${data.name || userId}! I'm TAIA, your Academic AI Assistant.\n\nYou can ask me about your ${role === 'student' ? 'attendance, results, GPA, fees, timetable, assignments, or study plans' : role === 'faculty' ? 'course attendance, ungraded assignments, or at-risk students' : 'student statistics, admissions, fee collection, or department performance'}.`);
    } catch (e) {
        if (e.message.includes('502') || e.message.includes('Failed to fetch') || e.message.includes('500') || e.message.includes('1 minute')) {
            let seconds = 30;
            errDiv.style.display = 'block';
            errDiv.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ERP Server is waking up from sleep. Please wait <strong id="retryCount">${seconds}</strong>s...`;
            
            const interval = setInterval(() => {
                seconds--;
                const countSpan = document.getElementById('retryCount');
                if (countSpan) countSpan.textContent = seconds;
                
                if (seconds <= 0) {
                    clearInterval(interval);
                    errDiv.style.display = 'none';
                    // The user can now click login again
                }
            }, 1000);
        } else {
            errDiv.style.display = 'block';
            errDiv.innerHTML = `<i class="fas fa-exclamation-circle"></i> Login failed: ${e.message}`;
        }
    } finally {
        loginBtn.innerHTML = originalBtnText;
        loginBtn.disabled = false;
        loginBtn.style.opacity = '1';
    }
}

function logout() {
    token = null; sessionId = null;
    localStorage.removeItem('taia_jwt');
    localStorage.removeItem('taia_role');
    document.getElementById('loginSection').style.display = 'block';
    document.getElementById('userInfo').style.display = 'none';
    document.getElementById('quickQuestions').style.display = 'none';
    document.getElementById('msgInput').disabled = true;
    document.getElementById('sendBtn').disabled = true;
    
    document.getElementById('messages').innerHTML = `
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
    document.getElementById('messages').innerHTML = '';
    addMsg('assistant', "I've started a new conversation. How can I help you?");
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
        const r = await fetch(`${API}/api/v1/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': 'Bearer ' + token,
            },
            body: JSON.stringify({message: msg, session_id: sessionId}),
        });
        typing.remove();
        if (r.ok) {
            const data = await r.json();
            addMsg('assistant', data.response, `${data.time || ''} | [${data.intent || 'Unknown'}]`);
        } else {
            const err = await r.json();
            addMsg('assistant', `**Error:** ${err.detail || 'Error processing request'}`);
        }
    } catch (e) {
        typing.remove();
        addMsg('assistant', '**Connection Error:** Make sure both servers are running.\n\nAI Service: `uvicorn app.main:app --reload`\nMock ERP: `uvicorn mock_erp.main:app --port 8001 --reload`');
    }
}

function addMsg(type, text, meta) {
    const msgs = document.getElementById('messages');
    
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
    
    // Scroll to bottom
    msgs.scrollTop = msgs.scrollHeight;
}

function showTyping() {
    const msgs = document.getElementById('messages');
    
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
    
    msgs.scrollTop = msgs.scrollHeight;
    return wrapper;
}

function toggleSidebar() {
    document.getElementById('sidebar').classList.toggle('open');
}
