/* ==========================================
   工作台 Workbench — 前端逻辑
   ========================================== */

// ---- 全局状态 ----
let projects = [];
let currentProjectName = '';
let activeCategory = '全部';
let pendingSwitch = null;
let statusPollTimer = null;

// ---- DOM 元素 ----
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const projectsGrid = $('#projects-grid');
const searchInput = $('#search-input');
const searchClear = $('#search-clear');
const categoryTabs = $('#category-tabs');
const statusBar = $('#status-bar');
const statusDot = $('#status-dot');
const statusText = $('#status-text');
const emptyState = $('#empty-state');
const toastContainer = $('#toast-container');
const confirmModal = $('#confirm-modal');
const confirmMessage = $('#confirm-message');
const confirmTitle = $('#confirm-title');
const historyOverlay = $('#history-overlay');
const historyDrawer = $('#history-drawer');
const historyList = $('#history-list');
const processPanel = $('#process-panel');
const processList = $('#process-list');
const processCount = $('#process-count');

// ---- 初始化 ----
document.addEventListener('DOMContentLoaded', () => {
    loadProjects();
    checkStatus();
    initEvents();
    loadTheme();
});

// ---- 事件绑定 ----
function initEvents() {
    // 搜索
    searchInput.addEventListener('input', () => {
        const val = searchInput.value.trim();
        searchClear.style.display = val ? 'block' : 'none';
        renderProjects();
    });
    searchClear.addEventListener('click', () => {
        searchInput.value = '';
        searchClear.style.display = 'none';
        renderProjects();
        searchInput.focus();
    });

    // 确认对话框
    $('#confirm-cancel').addEventListener('click', hideConfirm);
    $('#confirm-ok').addEventListener('click', () => {
        const target = pendingSwitch;
        hideConfirm();
        if (target) {
            doSwitch(target);
        }
    });

    // 点击遮罩关闭对话框（不确认）
    confirmModal.addEventListener('click', (e) => {
        if (e.target === confirmModal) hideConfirm();
    });

    // 关闭当前环境
    $('#btn-close-current').addEventListener('click', closeCurrent);

    // 历史抽屉
    $('#btn-history').addEventListener('click', openHistory);
    $('#btn-history-close').addEventListener('click', closeHistory);
    historyOverlay.addEventListener('click', closeHistory);
    $('#btn-clear-history').addEventListener('click', clearHistory);

    // 重新加载配置
    $('#btn-reload').addEventListener('click', reloadConfig);

    // 主题切换
    $('#btn-theme').addEventListener('click', toggleTheme);

    // 键盘快捷键
    document.addEventListener('keydown', (e) => {
        // Escape 关闭弹窗/抽屉
        if (e.key === 'Escape') {
            if (confirmModal.style.display !== 'none') hideConfirm();
            else if (historyDrawer.style.display !== 'none' &&
                     historyDrawer.style.display !== '') closeHistory();
            else searchInput.blur();
        }
        // Ctrl+F / / 聚焦搜索
        if ((e.ctrlKey && e.key === 'f') || (e.key === '/' && !e.ctrlKey && !e.metaKey)) {
            if (document.activeElement !== searchInput) {
                e.preventDefault();
                searchInput.focus();
            }
        }
    });
}

// ---- 数据加载 ----
async function loadProjects() {
    try {
        const res = await fetch('/api/projects');
        const data = await res.json();
        projects = data.projects || [];
        applySettings(data.settings);
        renderCategoryTabs();
        renderProjects();
    } catch (err) {
        console.error('加载项目失败:', err);
        showToast('无法连接到工作台服务', 'error');
        emptyState.style.display = 'block';
    }
}

function applySettings(settings) {
    if (settings && settings.columns) {
        projectsGrid.style.gridTemplateColumns =
            `repeat(auto-fill, minmax(${Math.max(160, 900 / settings.columns - 32)}px, 1fr))`;
    }
}

// ---- 分类标签 ----
function renderCategoryTabs() {
    const cats = new Set();
    projects.forEach(p => cats.add(p.category || '其他'));
    const categories = ['全部', ...cats];

    categoryTabs.innerHTML = categories.map(c =>
        `<span class="category-pill${c === activeCategory ? ' active' : ''}"
              data-category="${c}">${c}</span>`
    ).join('');

    categoryTabs.querySelectorAll('.category-pill').forEach(pill => {
        pill.addEventListener('click', () => {
            activeCategory = pill.dataset.category;
            renderCategoryTabs();
            renderProjects();
        });
    });
}

// ---- 渲染项目卡片 ----
function renderProjects() {
    const searchTerm = searchInput.value.trim().toLowerCase();
    let filtered = projects;

    // 分类筛选
    if (activeCategory !== '全部') {
        filtered = filtered.filter(p => (p.category || '其他') === activeCategory);
    }

    // 搜索筛选
    if (searchTerm) {
        filtered = filtered.filter(p =>
            p.name.toLowerCase().includes(searchTerm) ||
            (p.category || '').toLowerCase().includes(searchTerm) ||
            p.environment.some(e =>
                e.app.toLowerCase().includes(searchTerm) ||
                (e.target || '').toLowerCase().includes(searchTerm)
            )
        );
    }

    // 渲染
    if (filtered.length === 0) {
        projectsGrid.innerHTML = '';
        emptyState.style.display = 'block';
    } else {
        emptyState.style.display = 'none';
        projectsGrid.innerHTML = filtered.map(p => createCard(p)).join('');
    }

    // 绑定卡片点击事件
    projectsGrid.querySelectorAll('.project-card').forEach(card => {
        card.addEventListener('click', function(e) {
            const projectName = this.dataset.projectName;
            // 创建波纹效果
            createRipple(e, this);
            // 切换到该项目
            handleProjectClick(projectName);
        });
    });
}

function createCard(project) {
    const isActive = project.name === currentProjectName;
    const envTags = project.environment.slice(0, 4).map(e => {
        const labels = {
            vscode: 'VS', obsidian: 'Ob', browser: '🌐',
            terminal: '>_', folder: '📂', app: '⬡'
        };
        return `<span class="card-env-tag">${labels[e.app] || e.app}</span>`;
    }).join('');

    const moreCount = project.environment.length > 4
        ? `<span class="card-env-tag">+${project.environment.length - 4}</span>` : '';

    return `
        <div class="project-card${isActive ? ' active' : ''}"
             data-project-name="${escapeHtml(project.name)}"
             style="--card-color: ${project.color || '#4A90D9'}">
            <div class="card-top">
                <span class="card-icon">${project.icon || '📁'}</span>
                <span class="card-badge">${escapeHtml(project.category || '其他')}</span>
            </div>
            <div class="card-name">${escapeHtml(project.name)}</div>
            <div class="card-env">${envTags}${moreCount}</div>
            ${isActive
                ? '<div class="card-status card-status-running">● 运行中</div>'
                : ''}
        </div>
    `;
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ---- 项目切换 ----
async function handleProjectClick(projectName) {
    console.log('[Frontend] handleProjectClick:', projectName, 'current:', currentProjectName);
    // 如果点击的是当前已激活的项目，不做切换
    if (projectName === currentProjectName) {
        showToast(`「${projectName}」已在运行中`, 'info');
        return;
    }

    // 如果有当前环境，显示确认对话框
    if (currentProjectName) {
        console.log('[Frontend] showing confirm dialog for switch to:', projectName);
        const project = projects.find(p => p.name === projectName);
        const newEnvCount = project ? project.environment.length : 0;
        confirmTitle.textContent = '切换项目环境';
        confirmMessage.innerHTML = `
            即将关闭当前环境 <strong>「${currentProjectName}」</strong>，<br>
            切换到 <strong>「${projectName}」</strong>（${newEnvCount} 个组件）。<br><br>
            <small style="color: var(--text-muted);">
            未保存的文件不会被强制关闭，应用会提示你保存。
            </small>
        `;
        pendingSwitch = projectName;
        showConfirm();
    } else {
        // 没有活跃环境，直接切换
        await doSwitch(projectName);
    }
}

async function doSwitch(projectName) {
    console.log('[Frontend] doSwitch called:', projectName);
    try {
        showToast(`正在切换到「${projectName}」...`, 'info');

        const res = await fetch(`/api/switch/${encodeURIComponent(projectName)}`, {
            method: 'POST',
        });
        console.log('[Frontend] API response:', res.status);
        const data = await res.json();

        if (data.success) {
            currentProjectName = projectName;
            updateStatusBar(data.new_session);
            renderProjects();
            showToast(data.message, 'success');
        } else {
            showToast('切换失败', 'error');
        }
    } catch (err) {
        console.error('切换失败:', err);
        showToast('切换失败，请检查服务是否运行', 'error');
    }
}

async function closeCurrent() {
    if (!currentProjectName) return;

    try {
        const res = await fetch('/api/close-current', { method: 'POST' });
        const data = await res.json();
        currentProjectName = '';
        updateStatusBar(null);
        renderProjects();
        showToast(data.message, 'success');
    } catch (err) {
        showToast('关闭失败', 'error');
    }
}

// ---- 状态条 ----
async function checkStatus() {
    try {
        const res = await fetch('/api/status');
        const data = await res.json();
        if (data.active) {
            currentProjectName = data.project_name;
        }
        updateStatusBar(data);
        renderProcessPanel(data);
        renderProjects();
    } catch (err) {
        // 服务器可能尚未就绪
    }
}

function updateStatusBar(session) {
    if (session && session.active) {
        statusBar.style.display = 'flex';
        statusDot.className = 'status-dot active';
        const pids = session.tracked_pids || [];
        statusText.textContent = `${session.project_name} · ${pids.length} 进程`;
    } else if (currentProjectName) {
        statusBar.style.display = 'flex';
        statusDot.className = 'status-dot active';
        statusText.textContent = currentProjectName;
    } else {
        statusBar.style.display = 'none';
        statusDot.className = 'status-dot';
    }
}

// ---- 进程面板 ----
function renderProcessPanel(session) {
    if (!session || !session.active || !session.processes || session.processes.length === 0) {
        processPanel.style.display = 'none';
        return;
    }

    processPanel.style.display = 'block';
    const processes = session.processes;
    processCount.textContent = `${processes.length} 个进程`;

    processList.innerHTML = processes.map(p => {
        const statusCls = p.is_alive ? 'alive' : 'dead';
        const windowsText = (p.windows && p.windows.length > 0)
            ? p.windows.map(w => `"${w}"`).join(', ')
            : '<span style="color:var(--text-muted)">无可见窗口</span>';
        return `
            <div class="process-row">
                <span class="process-pid">PID ${p.pid}</span>
                <span class="process-name">${esc(p.name)}</span>
                <span class="process-windows" title="${esc(windowsText)}">${windowsText}</span>
                <span class="process-status ${statusCls}" title="${p.is_alive ? '运行中' : '已退出'}"></span>
            </div>
        `;
    }).join('');
}

function esc(s) {
    const d = document.createElement('div');
    d.textContent = s || '';
    return d.innerHTML;
}

// Toggle process panel
$('#btn-toggle-process').addEventListener('click', () => {
    processList.classList.toggle('collapsed');
    const btn = $('#btn-toggle-process');
    btn.textContent = processList.classList.contains('collapsed') ? '▶' : '▼';
});

// ---- 历史记录 ----
async function openHistory() {
    historyOverlay.style.display = 'block';
    historyDrawer.style.display = 'flex';

    try {
        const res = await fetch('/api/history');
        const data = await res.json();
        renderHistory(data.history || []);
    } catch (err) {
        historyList.innerHTML = '<div class="drawer-empty"><p>加载失败</p></div>';
    }
}

function closeHistory() {
    historyOverlay.style.display = 'none';
    historyDrawer.style.display = 'none';
}

function renderHistory(entries) {
    if (entries.length === 0) {
        historyList.innerHTML = '<div class="drawer-empty"><p>暂无历史记录</p></div>';
        return;
    }

    historyList.innerHTML = entries.map(e => `
        <div class="history-item" data-id="${e.id}">
            <span class="hi-icon">${e.icon || '📁'}</span>
            <div class="hi-info">
                <div class="hi-name">${escapeHtml(e.project_name)}</div>
                <div class="hi-summary">${escapeHtml(e.summary || '')}</div>
            </div>
            <span class="hi-time">${escapeHtml(e.formatted_time || '')}</span>
            <span class="hi-restore">恢复</span>
        </div>
    `).join('');

    historyList.querySelectorAll('.history-item').forEach(item => {
        item.addEventListener('click', () => restoreHistory(item.dataset.id));
    });
}

async function restoreHistory(entryId) {
    try {
        showToast('正在恢复...', 'info');
        closeHistory();

        const res = await fetch(`/api/history/${entryId}/restore`, { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            currentProjectName = data.new_session?.project_name || '';
            updateStatusBar(data.new_session);
            renderProjects();
            showToast(data.message, 'success');
        } else {
            showToast('恢复失败', 'error');
        }
    } catch (err) {
        showToast('恢复失败', 'error');
    }
}

async function clearHistory() {
    try {
        await fetch('/api/history', { method: 'DELETE' });
        historyList.innerHTML = '<div class="drawer-empty"><p>历史已清空</p></div>';
    } catch (err) {
        showToast('清空失败', 'error');
    }
}

// ---- 配置重载 ----
async function reloadConfig() {
    try {
        const res = await fetch('/api/reload', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            await loadProjects();
            showToast('配置已重新加载 ✓', 'success');
        } else {
            showToast('重载失败', 'error');
        }
    } catch (err) {
        showToast('重载失败', 'error');
    }
}

// ---- 主题 ----
function loadTheme() {
    const saved = localStorage.getItem('workbench-theme');
    if (saved) {
        document.documentElement.setAttribute('data-theme', saved);
        updateThemeIcon(saved);
    }
}

function toggleTheme() {
    const current = document.documentElement.getAttribute('data-theme');
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('workbench-theme', next);
    updateThemeIcon(next);
}

function updateThemeIcon(theme) {
    $('#btn-theme').textContent = theme === 'dark' ? '☀️' : '🌙';
}

// ---- Toast 通知 ----
function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    toastContainer.appendChild(toast);

    // 自动消失
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease-out';
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

// ---- 确认对话框 ----
function showConfirm() {
    confirmModal.style.display = 'flex';
}

function hideConfirm() {
    confirmModal.style.display = 'none';
    pendingSwitch = null;
}

// ---- 波纹效果 ----
function createRipple(event, element) {
    const ripple = document.createElement('span');
    ripple.className = 'ripple';

    const rect = element.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    ripple.style.width = ripple.style.height = `${size}px`;
    ripple.style.left = `${event.clientX - rect.left - size / 2}px`;
    ripple.style.top = `${event.clientY - rect.top - size / 2}px`;

    element.appendChild(ripple);
    ripple.addEventListener('animationend', () => ripple.remove());
}

// ---- 定期刷新状态 ----
setInterval(checkStatus, 10000); // 每 10 秒检查一次
