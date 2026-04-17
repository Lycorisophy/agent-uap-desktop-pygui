/**
 * UAP 前端应用 - 主交互逻辑
 * 处理UI交互、API调用、视图切换
 */

// 全局状态
const state = {
    currentView: 'projects',
    projects: [],
    currentProject: null,
    settings: {
        llmProvider: 'ollama',
        llmModel: 'llama3.2',
        llmBaseUrl: 'http://localhost:11434',
        llmApiKeySet: false,
        llmPresets: {},
        defaultFrequency: 3600,
        defaultHorizon: 259200,
        embedModel: 'qwen3-embedding:8b',
        embedBaseUrl: '',
        embedDimension: 4096,
        milvusLitePath: '',
        modelingIntentContextRounds: 2,
        reactMaxStepsDefault: 8,
        classifyUseSeparate: false,
        classifyProvider: 'ollama',
        classifyModel: '',
        classifyBaseUrl: '',
        classifyApiKeySet: false
    }
};

// API暴露的方法（供PyWebView调用）
window.uapAPI = {
    // 获取项目列表
    getProjects: () => state.projects,
    
    // 创建项目回调
    onProjectCreated: (result) => {
        // 处理不同的返回格式
        let project;
        if (result && result.project) {
            // 格式: {ok: true, project: {...}, project_id: '...'}
            project = result.project;
        } else if (result && result.id) {
            // 格式: 直接是项目对象
            project = result;
        }
        
        if (project && project.id) {
            // 检查是否已存在
            const exists = state.projects.find(p => p.id === project.id);
            if (!exists) {
                state.projects.push(project);
            }
        }
        renderProjectGrid();
        updateProjectSelects();
        closeModal('createProjectModal');
        showToast('项目创建成功', 'success');
    },
    
    // 删除项目回调
    onProjectDeleted: (projectId) => {
        state.projects = state.projects.filter(p => p.id !== projectId);
        renderProjectGrid();
        showToast('项目已删除', 'info');
    },
    
    // 项目加载回调
    onProjectLoaded: (project) => {
        state.currentProject = project;
        updateProjectSelects();
        if (state.currentView === 'modeling') {
            renderModelPreview(project.model);
        }
        showToast('项目已加载', 'success');
    },
    
    // 建模消息回调
    onModelingMessage: (message) => {
        appendChatMessage(message);
    },
    
    // 模型提取完成
    onModelExtracted: (model) => {
        if (state.currentProject) {
            state.currentProject.model = model;
        }
        renderModelPreview(model);
    },
    
    // 预测结果回调
    onPredictionResult: (result) => {
        renderPredictionResults(result);
    },
    
    // 预测任务状态
    onPredictionTaskStatus: (status) => {
        updateTaskStatus(status);
    },
    
    // 设置加载
    onSettingsLoaded: (settings) => {
        state.settings = { ...state.settings, ...settings };
        renderSettings();
    },
    
    // 错误处理
    onError: (error) => {
        showToast(error, 'error');
    }
};

// ==================== 初始化 ====================

/**
 * pywebview 会先挂上 `window.pywebview.api = {}`，再在子线程里执行 `_createApi` 绑定方法（见 pywebview util.inject_pywebview）。
 * 仅判断 `if (api)` 会在空对象阶段为真，此时调用 `list_projects` 会得到 “is not a function”。
 */
function isPywebviewApiCallable() {
    const api = window.pywebview?.api;
    return !!(
        api &&
        typeof api.list_projects === 'function' &&
        typeof api.get_config === 'function'
    );
}

/** 建模 LLM 流式轮询（后台线程 + hub）；旧版 exe 无此方法时回退 ``modeling_chat``。 */
function isModelingStreamApiAvailable() {
    const api = window.pywebview?.api;
    return !!(
        api &&
        typeof api.start_modeling_chat_stream === 'function' &&
        typeof api.poll_modeling_chat_stream === 'function'
    );
}

function removeModelingStreamLiveBubbles() {
    document.querySelectorAll('.message.assistant.modeling-stream-live').forEach((el) => {
        el.remove();
    });
}

function appendModelingStreamLiveBubble(streamId) {
    const container = document.getElementById('chatMessages');
    if (!container) return null;
    const wrap = document.createElement('div');
    wrap.className = 'message assistant modeling-stream-live';
    wrap.dataset.uapStreamId = String(streamId || '');
    const timeStr = formatTime(new Date().toISOString());
    wrap.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-content">
            <div class="message-text modeling-stream-text" style="white-space: pre-wrap;"></div>
            <div class="modeling-stream-hint">正在生成回复…</div>
            <div class="message-time">${escapeHtml(timeStr)}</div>
        </div>
    `;
    container.appendChild(wrap);
    container.scrollTop = container.scrollHeight;
    return wrap.querySelector('.modeling-stream-text');
}

async function uapSleepMs(ms) {
    await new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * PyWebView 在 DOMContentLoaded 时可能尚未注入 window.pywebview。
 * 原先在 maxMs 时用 finish() 直接清掉轮询，若 api 在超时后才就绪会永久错过，表现为重启后列表/设置为空。
 */
async function waitForPywebviewApi(maxMs = 60000) {
    if (isPywebviewApiCallable()) return true;
    const deadline = Date.now() + maxMs;
    const ready = await new Promise((resolve) => {
        let done = false;
        const finish = (ok) => {
            if (done) return;
            done = true;
            clearInterval(iv);
            clearTimeout(to);
            window.removeEventListener('pywebviewready', onReady);
            resolve(ok);
        };
        const onReady = () => {
            if (isPywebviewApiCallable()) finish(true);
        };
        window.addEventListener('pywebviewready', onReady);
        const iv = setInterval(() => {
            if (isPywebviewApiCallable()) finish(true);
            else if (Date.now() >= deadline) finish(false);
        }, 50);
        const to = setTimeout(() => finish(false), maxMs);
    });
    if (!ready) {
        console.warn(
            `[UAP] waitForPywebviewApi: ${maxMs}ms 内未完成 _createApi（list_projects 仍不可用），项目与设置将无法从后端加载`
        );
    }
    return ready;
}

/**
 * 若 DOMContentLoaded 时 pywebview.api 尚未注入（调试器/冷启动常见），首轮 load 会空跑。
 * 在 pywebviewready 与短时轮询上补跑一次，直到成功或超时。
 */
function scheduleDeferredProjectAndSettingsLoad() {
    if (window.__uapDeferredBootstrapScheduled) return;
    window.__uapDeferredBootstrapScheduled = true;

    let deferredRunning = false;
    const tryOnce = async () => {
        if (deferredRunning || window.__uapDataBootstrapDone || !isPywebviewApiCallable()) return;
        deferredRunning = true;
        try {
            console.log('[UAP] deferred: _createApi 已完成，补载项目与设置');
            await loadProjects();
            await loadSettings();
            window.__uapDataBootstrapDone = true;
            clearInterval(iv);
            window.removeEventListener('pywebviewready', onPvReady);
        } catch (e) {
            console.error('[UAP] deferred loadProjects/loadSettings 失败', e);
        } finally {
            deferredRunning = false;
        }
    };

    const onPvReady = () => {
        tryOnce();
    };
    window.addEventListener('pywebviewready', onPvReady);
    const iv = setInterval(() => {
        tryOnce();
    }, 400);
    setTimeout(() => {
        clearInterval(iv);
        window.removeEventListener('pywebviewready', onPvReady);
        if (!window.__uapDataBootstrapDone && isPywebviewApiCallable()) {
            tryOnce();
        } else if (!window.__uapDataBootstrapDone) {
            console.warn('[UAP] deferred: 120s 内 _createApi 仍未完成（list_projects 不可用），请检查 pywebview 与调试启动方式');
        }
    }, 120000);
}

document.addEventListener('DOMContentLoaded', () => {
    initializeApp();
});

async function initializeApp() {
    console.log('UAP initializing...');
    
    // 绑定全局事件
    bindNavigationEvents();
    bindProjectEvents();
    bindModelingEvents();
    bindPredictionEvents();
    bindSettingsEvents();
    bindKnowledgeEvents();
    bindModalEvents();
    
    const apiReady = await waitForPywebviewApi();
    await loadProjects();
    await loadSettings();
    if (apiReady && isPywebviewApiCallable()) {
        window.__uapDataBootstrapDone = true;
        console.log('[UAP] initialized, projects=', state.projects.length);
    } else {
        console.warn('[UAP] initialized before _createApi 完成; projects=', state.projects.length);
        scheduleDeferredProjectAndSettingsLoad();
    }
}

// ==================== 导航切换 ====================

function bindNavigationEvents() {
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            switchView(view);
        });
    });
}

function switchView(viewName) {
    // 更新导航状态
    document.querySelectorAll('.nav-item').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.view === viewName);
    });
    
    // 更新视图显示
    document.querySelectorAll('.view').forEach(view => {
        view.classList.toggle('active', view.id === `${viewName}View`);
    });
    
    state.currentView = viewName;
    
    // 视图特定初始化
    if (viewName === 'modeling' || viewName === 'prediction' || viewName === 'knowledge') {
        updateProjectSelects();
    }
    if (viewName === 'knowledge') {
        refreshKbStatus();
    }
}

// ==================== 项目管理 ====================

async function loadProjects() {
    if (!isPywebviewApiCallable()) {
        console.warn('[UAP] loadProjects: _createApi 尚未完成（api 无 list_projects），跳过加载');
        showToast('无法加载项目列表：桌面 API 尚未就绪，请稍候或重启应用', 'warning');
        return;
    }
    console.log('[UAP] loadProjects: 请求 list_projects …');
    try {
        const result = await window.pywebview.api.list_projects();
        const items = Array.isArray(result)
            ? result
            : (result && Array.isArray(result.items) ? result.items : []);
        const total =
            result && !Array.isArray(result) && result.total != null
                ? result.total
                : items.length;
        state.projects = items;
        console.log('[UAP] loadProjects: list_projects 成功', { count: items.length, total });
        renderProjectGrid();
        updateProjectSelects();
    } catch (e) {
        const msg = e?.message || String(e);
        console.error('[UAP] loadProjects: list_projects 失败', e);
        showToast('加载项目列表失败：' + msg, 'error');
        renderProjectGrid();
        updateProjectSelects();
    }
}

function renderProjectGrid() {
    const grid = document.getElementById('projectGrid');
    if (!grid) return;
    
    if (state.projects.length === 0) {
        grid.innerHTML = `
            <div class="empty-state">
                <p>暂无项目</p>
                <p class="hint">点击右上角按钮创建第一个项目</p>
            </div>
        `;
        return;
    }
    
    grid.innerHTML = state.projects.map(project => `
        <div class="project-card" data-id="${project.id}">
            <div class="project-card-header">
                <h3>${escapeHtml(project.name)}</h3>
                <span class="project-status ${project.model || project.has_model ? 'has-model' : 'no-model'}">
                    ${project.model || project.has_model ? '已建模' : '未建模'}
                </span>
            </div>
            <p class="project-description">${escapeHtml(project.description || '暂无描述')}</p>
            <div class="project-card-footer">
                <span class="project-date">${formatDate(project.created_at)}</span>
                <div class="project-actions">
                    <button class="btn-icon" onclick="openProject('${project.id}')" title="打开">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
                        </svg>
                    </button>
                    <button class="btn-icon danger" onclick="deleteProject('${project.id}')" title="删除">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <polyline points="3 6 5 6 21 6"></polyline>
                            <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path>
                        </svg>
                    </button>
                </div>
            </div>
        </div>
    `).join('');
}

function bindProjectEvents() {
    const createBtn = document.getElementById('createProjectBtn');
    if (createBtn) {
        createBtn.addEventListener('click', () => openModal('createProjectModal'));
    }
}

async function openProject(projectId) {
    if (!projectId || projectId === 'undefined') {
        showToast('项目ID无效', 'error');
        return;
    }
    try {
        if (isPywebviewApiCallable()) {
            const project = await window.pywebview.api.get_project(projectId);
            if (project) {
                state.currentProject = project;
                switchView('modeling');
                window.uapAPI.onProjectLoaded(project);
                await loadModelingChatForCurrentProject();
            } else {
                showToast('项目不存在', 'error');
            }
        }
    } catch (e) {
        console.error('Failed to open project:', e);
        showToast('打开项目失败: ' + (e.message || e), 'error');
    }
}

async function deleteProject(projectId) {
    if (!projectId || projectId === 'undefined') {
        showToast('项目ID无效', 'error');
        return;
    }
    if (!confirm('确定要删除这个项目吗？')) return;
    
    try {
        if (isPywebviewApiCallable()) {
            const result = await window.pywebview.api.delete_project(projectId);
            if (result && result.success) {
                window.uapAPI.onProjectDeleted(projectId);
            } else {
                showToast(result?.error || '删除项目失败', 'error');
            }
        }
    } catch (e) {
        console.error('Failed to delete project:', e);
        showToast('删除项目失败', 'error');
    }
}

// ==================== 模态框 ====================

function bindModalEvents() {
    // 关闭按钮
    const closeBtn = document.getElementById('closeProjectModal');
    if (closeBtn) {
        closeBtn.addEventListener('click', () => closeModal('createProjectModal'));
    }
    
    // 取消按钮
    const cancelBtn = document.getElementById('cancelProjectBtn');
    if (cancelBtn) {
        cancelBtn.addEventListener('click', () => closeModal('createProjectModal'));
    }
    
    // 创建确认
    const confirmBtn = document.getElementById('confirmCreateBtn');
    if (confirmBtn) {
        confirmBtn.addEventListener('click', createProject);
    }
    
    // 不再点击背景关闭弹框，只允许按钮关闭
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.add('active');
    }
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.classList.remove('active');
        // 清空表单
        const nameInput = document.getElementById('projectName');
        const descInput = document.getElementById('projectDescription');
        if (nameInput) nameInput.value = '';
        if (descInput) descInput.value = '';
    }
}

async function createProject() {
    const nameInput = document.getElementById('projectName');
    const descInput = document.getElementById('projectDescription');
    
    const name = nameInput?.value.trim();
    if (!name) {
        showToast('请输入项目名称', 'warning');
        return;
    }
    
    const description = descInput?.value.trim() || '';
    
    try {
        if (isPywebviewApiCallable()) {
            const result = await window.pywebview.api.create_project(name, description);
            if (result && result.ok) {
                window.uapAPI.onProjectCreated(result);
            } else {
                showToast(result?.error || '创建项目失败', 'error');
            }
        } else {
            // 演示模式
            const demoProject = {
                id: 'demo-' + Date.now(),
                name: name,
                description: description,
                created_at: new Date().toISOString(),
                model: null
            };
            window.uapAPI.onProjectCreated(demoProject);
        }
    } catch (e) {
        console.error('Failed to create project:', e);
        showToast('创建项目失败: ' + (e.message || e), 'error');
    }
}

// ==================== 建模功能 ====================

const UAP_MODELING_WELCOME_INNER_HTML =
    '欢迎使用智能对话模式。<br>• 智能思考与工具调用<br>• 对话状态追踪<br>• 人在环确认<br><br>用<strong>一句话</strong>说出想预测什么即可（天气、营收、股价等）；我会主动追问细节并协助建模。建模完成并配置数据后，可使用定时预测。如需帮助，随时问我。';

function resetModelingChatToWelcome() {
    const c = document.getElementById('chatMessages');
    if (!c) return;
    c.innerHTML = `<div class="message system"><div class="message-content">${UAP_MODELING_WELCOME_INNER_HTML}</div></div>`;
    c.scrollTop = c.scrollHeight;
}

function resetModelingSessionSidebars() {
    const badge = document.getElementById('processStatus');
    const box = document.getElementById('processSteps');
    if (badge) {
        badge.className = 'status-badge idle';
        badge.textContent = '空闲';
    }
    if (box) {
        box.innerHTML = '<div class="empty-state">暂无运行中的任务</div>';
    }
    updateDSTStatus('INITIAL', 0, {});
    const dstDetails = document.getElementById('dstDetails');
    if (dstDetails) {
        dstDetails.innerHTML = '<p class="placeholder">DST详情将在这里显示</p>';
    }
}

function renderModelingChatFromApiMessages(messages) {
    resetModelingChatToWelcome();
    const arr = Array.isArray(messages) ? messages : [];
    arr.forEach((m) => {
        const role = (m.role || '').toLowerCase();
        if (role !== 'user' && role !== 'assistant') return;
        appendChatMessage({
            type: role,
            content: String(m.content != null ? m.content : ''),
            timestamp: m.created_at || new Date().toISOString(),
        });
    });
}

async function loadModelingChatForCurrentProject() {
    if (!state.currentProject || !isPywebviewApiCallable()) return;
    try {
        const res = await window.pywebview.api.get_modeling_messages(state.currentProject.id);
        if (res && res.ok) {
            renderModelingChatFromApiMessages(res.messages);
        }
    } catch (e) {
        console.error('加载建模会话失败:', e);
    }
}

function formatHistorySessionTime(iso) {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        if (Number.isNaN(d.getTime())) return String(iso).slice(0, 19);
        return d.toLocaleString('zh-CN');
    } catch (_) {
        return String(iso);
    }
}

async function loadModelingConversationHistory() {
    const list = document.getElementById('modelingHistoryList');
    if (!list) return;
    if (!state.currentProject) {
        list.innerHTML = '<div class="empty-state">请先选择项目</div>';
        return;
    }
    if (!isPywebviewApiCallable()) {
        list.innerHTML = '<div class="empty-state">演示模式无历史</div>';
        return;
    }
    list.innerHTML = '<div class="empty-state">加载中…</div>';
    try {
        const res = await window.pywebview.api.list_modeling_conversation_history(
            state.currentProject.id
        );
        if (!res || !res.ok) {
            list.innerHTML = `<div class="empty-state">${escapeHtml(res?.error || '加载失败')}</div>`;
            return;
        }
        const items = res.items || [];
        if (!items.length) {
            list.innerHTML = '<div class="empty-state">暂无归档会话</div>';
            return;
        }
        list.innerHTML = items
            .map((it) => {
                const id = escapeHtml(String(it.id || ''));
                const pv = escapeHtml(String(it.preview || ''));
                const fa = escapeHtml(formatHistorySessionTime(it.first_at));
                const la = escapeHtml(formatHistorySessionTime(it.last_at));
                return `<div class="modeling-history-row">
        <div class="modeling-history-row-meta">
          <div class="modeling-history-preview">${pv}</div>
          <div class="modeling-history-times">最早：${fa}<br>最新：${la}</div>
        </div>
        <button type="button" class="btn btn-primary btn-sm modeling-restore-btn" data-session-id="${id}">恢复</button>
      </div>`;
            })
            .join('');
        list.querySelectorAll('.modeling-restore-btn').forEach((btn) => {
            btn.addEventListener('click', () => {
                const sid = btn.getAttribute('data-session-id');
                if (sid) restoreModelingConversationSession(sid);
            });
        });
    } catch (e) {
        console.error(e);
        list.innerHTML = '<div class="empty-state">加载失败</div>';
    }
}

async function restoreModelingConversationSession(sessionId) {
    if (!state.currentProject || !sessionId) return;
    if (!isPywebviewApiCallable()) return;
    try {
        const res = await window.pywebview.api.restore_modeling_conversation(
            state.currentProject.id,
            sessionId
        );
        if (!res || !res.ok) {
            showToast(res?.error || '恢复失败', 'error');
            return;
        }
        renderModelingChatFromApiMessages(res.messages);
        resetModelingSessionSidebars();
        showToast('已恢复该会话到当前建模', 'success');
    } catch (e) {
        showToast('恢复失败: ' + (e.message || e), 'error');
    }
}

async function onNewModelingConversationClick() {
    if (!state.currentProject) {
        showToast('请先选择一个项目', 'warning');
        return;
    }
    if (!isPywebviewApiCallable()) {
        resetModelingChatToWelcome();
        resetModelingSessionSidebars();
        showToast('演示模式：已清空本地显示', 'info');
        return;
    }
    if (!confirm('确定开始新对话？当前会话将归档到「历史」，聊天与后端上下文将清空。')) {
        return;
    }
    try {
        const res = await window.pywebview.api.start_new_modeling_conversation(
            state.currentProject.id
        );
        if (!res || !res.ok) {
            showToast(res?.error || '操作失败', 'error');
            return;
        }
        resetModelingChatToWelcome();
        resetModelingSessionSidebars();
        if (res.archived_session_id) {
            showToast('已归档并开始新对话', 'success');
        } else {
            showToast('已开始新对话', 'success');
        }
        await loadModelingConversationHistory();
    } catch (e) {
        showToast('新对话失败: ' + (e.message || e), 'error');
    }
}

window.loadModelingConversationHistory = loadModelingConversationHistory;

function bindModelingEvents() {
    const sendBtn = document.getElementById('sendMessageBtn');
    if (sendBtn) {
        sendBtn.addEventListener('click', sendModelingMessage);
    }
    
    const chatInput = document.getElementById('chatInput');
    if (chatInput) {
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendModelingMessage();
            }
        });
    }
    
    const projectSelect = document.getElementById('modelingProjectSelect');
    if (projectSelect) {
        projectSelect.addEventListener('change', async (e) => {
            if (e.target.value) {
                await openProject(e.target.value);
            }
        });
    }

    document
        .getElementById('newModelingChatBtn')
        ?.addEventListener('click', () => onNewModelingConversationClick());
    
    // 智能体侧边栏标签切换
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const tab = btn.dataset.tab;
            switchAgentTab(tab);
        });
    });
}

// ==================== 智能体侧边栏 ====================

function switchAgentTab(tabName) {
    // 更新标签按钮状态
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.tab === tabName);
    });
    
    // 更新面板显示
    document.querySelectorAll('.tab-panel').forEach(panel => {
        panel.classList.toggle('active', panel.id === `${tabName}Panel`);
    });
    
    // 加载对应面板数据
    switch (tabName) {
        case 'skills':
            loadSkillsList();
            break;
        case 'history':
            loadModelingConversationHistory();
            break;
        case 'files':
            loadProjectFiles();
            break;
        case 'models':
            refreshModelPreview();
            break;
    }
}

// 刷新技能列表
async function loadSkillsList() {
    const container = document.getElementById('skillsList');
    if (!container) return;
    
    try {
        if (isPywebviewApiCallable()) {
            const skills = await window.pywebview.api.get_atomic_skills();
            if (skills && skills.length > 0) {
                container.innerHTML = skills.map(skill => `
                    <div class="skill-item" data-id="${skill.id || skill.name}">
                        <div class="skill-name">${escapeHtml(skill.name || '未知技能')}</div>
                        <div class="skill-desc">${escapeHtml(skill.description || skill.desc || '')}</div>
                        ${skill.category ? `<span class="skill-category">${escapeHtml(skill.category)}</span>` : ''}
                    </div>
                `).join('');
            } else {
                container.innerHTML = '<div class="empty-state">暂无可用技能</div>';
            }
        } else {
            // 演示数据
            container.innerHTML = `
                <div class="skill-item" data-id="web_search">
                    <div class="skill-name">网络搜索</div>
                    <div class="skill-desc">搜索互联网获取相关信息</div>
                    <span class="skill-category">情报</span>
                </div>
                <div class="skill-item" data-id="file_reader">
                    <div class="skill-name">文件读取</div>
                    <div class="skill-desc">读取项目文件夹中的文件</div>
                    <span class="skill-category">工具</span>
                </div>
                <div class="skill-item" data-id="variable_extractor">
                    <div class="skill-name">变量提取</div>
                    <div class="skill-desc">从对话中提取系统变量</div>
                    <span class="skill-category">建模</span>
                </div>
            `;
        }
    } catch (e) {
        console.error('加载技能列表失败:', e);
        container.innerHTML = '<div class="empty-state">加载失败</div>';
    }
}

// 刷新技能列表（供外部调用）
window.refreshSkillsList = loadSkillsList;

// 加载项目文件
async function loadProjectFiles() {
    const container = document.getElementById('fileBrowser');
    if (!container) return;
    
    if (!state.currentProject) {
        container.innerHTML = '<div class="empty-state">请先选择项目</div>';
        return;
    }
    
    try {
        if (isPywebviewApiCallable()) {
            const result = await window.pywebview.api.get_project_folder(state.currentProject.id);
            if (result && result.success && result.folder_path) {
                // 获取文件夹内容
                const files = await listDirectory(result.folder_path);
                container.innerHTML = renderFileTree(files, result.folder_path);
            } else {
                container.innerHTML = '<div class="empty-state">无法获取项目文件夹</div>';
            }
        } else {
            // 演示数据
            container.innerHTML = `
                <div class="file-item folder-item" data-path="intro">
                    <span class="folder-arrow">▶</span>
                    <span class="file-icon">📁</span>
                    <span class="file-name">intro</span>
                </div>
                <div class="file-item folder-item" data-path="skills">
                    <span class="folder-arrow">▶</span>
                    <span class="file-icon">📁</span>
                    <span class="file-name">skills</span>
                </div>
                <div class="file-item folder-item" data-path="logs">
                    <span class="folder-arrow">▶</span>
                    <span class="file-icon">📁</span>
                    <span class="file-name">logs</span>
                </div>
                <div class="file-item folder-item" data-path="models">
                    <span class="folder-arrow">▶</span>
                    <span class="file-icon">📁</span>
                    <span class="file-name">models</span>
                </div>
                <div class="file-item folder-item" data-path="tasks">
                    <span class="folder-arrow">▶</span>
                    <span class="file-icon">📁</span>
                    <span class="file-name">tasks</span>
                </div>
                <div class="file-item folder-item" data-path="data">
                    <span class="folder-arrow">▶</span>
                    <span class="file-icon">📁</span>
                    <span class="file-name">data</span>
                </div>
            `;
        }
    } catch (e) {
        console.error('加载项目文件失败:', e);
        container.innerHTML = '<div class="empty-state">加载失败</div>';
    }
}

// 列出目录内容
async function listDirectory(folderPath) {
    try {
        if (isPywebviewApiCallable()) {
            const result = await window.pywebview.api.list_directory(folderPath);
            return result.files || [];
        }
    } catch (e) {
        console.error('列出目录失败:', e);
    }
    return [];
}

// 渲染文件树
function renderFileTree(files, basePath) {
    if (!files || files.length === 0) {
        return '<div class="empty-state">文件夹为空</div>';
    }
    
    return files.map(file => `
        <div class="file-item ${file.is_directory ? 'folder-item' : ''}" data-path="${file.path}">
            ${file.is_directory ? '<span class="folder-arrow">▶</span>' : ''}
            <span class="file-icon">${file.is_directory ? '📁' : getFileIcon(file.name)}</span>
            <span class="file-name">${escapeHtml(file.name)}</span>
            ${file.size ? `<span class="file-size">${formatFileSize(file.size)}</span>` : ''}
        </div>
    `).join('');
}

// 获取文件图标
function getFileIcon(filename) {
    const ext = filename.split('.').pop().toLowerCase();
    const icons = {
        'md': '📝', 'txt': '📄', 'json': '📋', 'yaml': '📋', 'yml': '📋',
        'py': '🐍', 'js': '📜', 'ts': '📜', 'csv': '📊', 'xlsx': '📊',
        'png': '🖼️', 'jpg': '🖼️', 'jpeg': '🖼️', 'gif': '🖼️',
        'pdf': '📕'
    };
    return icons[ext] || '📄';
}

// 格式化文件大小
function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

// 在文件管理器中打开项目文件夹
async function openProjectInExplorer() {
    if (!state.currentProject) {
        showToast('请先选择项目', 'warning');
        return;
    }
    
    try {
        if (isPywebviewApiCallable()) {
            const result = await window.pywebview.api.get_project_folder(state.currentProject.id);
            if (result && result.success) {
                await window.pywebview.api.open_folder(result.folder_path);
            }
        }
    } catch (e) {
        console.error('打开文件夹失败:', e);
        showToast('打开文件夹失败', 'error');
    }
}

window.openProjectInExplorer = openProjectInExplorer;

// 更新进程状态
function updateProcessStatus(status, steps = []) {
    const statusBadge = document.getElementById('processStatus');
    const stepsContainer = document.getElementById('processSteps');
    
    if (statusBadge) {
        statusBadge.className = `status-badge ${status}`;
        statusBadge.textContent = {
            'idle': '空闲',
            'running': '运行中',
            'completed': '完成',
            'error': '错误'
        }[status] || status;
    }
    
    if (stepsContainer) {
        if (steps.length === 0) {
            stepsContainer.innerHTML = '<div class="empty-state">暂无运行中的任务</div>';
        } else {
            stepsContainer.innerHTML = steps.map(step => `
                <div class="process-step ${step.status || ''}">
                    <div class="step-header">
                        <span class="step-name">${escapeHtml(step.name || step.action || '步骤')}</span>
                        <span class="step-status">${step.status === 'completed' ? '✓' : step.status === 'running' ? '●' : '○'}</span>
                    </div>
                    ${step.detail ? `<div class="step-detail">${escapeHtml(step.detail)}</div>` : ''}
                </div>
            `).join('');
        }
    }
}

window.updateProcessStatus = updateProcessStatus;

// 更新DST状态
function updateDSTStatus(stage, progress, details = {}) {
    const progressIndicator = document.getElementById('dstProgress');
    const stagesContainer = document.getElementById('dstStages');
    const detailsContainer = document.getElementById('dstDetails');
    
    // 更新进度
    if (progressIndicator) {
        progressIndicator.textContent = `${Math.round(progress * 100)}%`;
    }
    
    // 更新阶段
    const stageOrder = ['INITIAL', 'INTENT', 'VARIABLES', 'RELATIONS', 'CONSTRAINTS', 'VALIDATION', 'COMPLETED'];
    const rawIdx = stageOrder.indexOf(stage);
    const currentIndex = rawIdx < 0 ? 0 : rawIdx;
    
    if (stagesContainer) {
        document.querySelectorAll('.dst-stage').forEach(el => {
            const elStage = el.dataset.stage;
            const elIndex = stageOrder.indexOf(elStage);
            
            el.classList.remove('active', 'completed');
            if (elIndex < currentIndex) {
                el.classList.add('completed');
            } else if (elStage === stage) {
                el.classList.add('active');
            }
        });
    }
    
    // 更新详情
    if (detailsContainer && Object.keys(details).length > 0) {
        detailsContainer.innerHTML = Object.entries(details).map(([key, value]) => `
            <div class="detail-row">
                <span class="detail-label">${escapeHtml(key)}</span>
                <span class="detail-value">${escapeHtml(String(value))}</span>
            </div>
        `).join('');
    }
}

window.updateDSTStatus = updateDSTStatus;

// 刷新模型预览
async function refreshModelPreview() {
    if (!state.currentProject || !state.currentProject.model) {
        // 尝试从API获取模型
        if (state.currentProject && isPywebviewApiCallable()) {
            try {
                const project = await window.pywebview.api.get_project(state.currentProject.id);
                if (project && project.model) {
                    state.currentProject.model = project.model;
                }
            } catch (e) {
                console.error('获取模型失败:', e);
            }
        }
    }
    
    renderModelPreviewToPanels(state.currentProject?.model);
}

window.refreshModelPreview = refreshModelPreview;

// 渲染模型到面板
function renderModelPreviewToPanels(model) {
    const variablesContainer = document.getElementById('modelVariables');
    const relationsContainer = document.getElementById('modelRelations');
    const constraintsContainer = document.getElementById('modelConstraints');
    
    if (variablesContainer) {
        if (model && model.variables && model.variables.length > 0) {
            variablesContainer.innerHTML = '<h5>变量定义</h5>' + model.variables.map(v => `
                <div class="model-var-item">
                    <span class="var-name">${escapeHtml(v.name)}</span>
                    <span class="var-type">${escapeHtml(v.type || v.data_type || '未知')}</span>
                    ${v.description ? `<div class="var-desc">${escapeHtml(v.description)}</div>` : ''}
                </div>
            `).join('');
        } else {
            variablesContainer.innerHTML = '<h5>变量定义</h5><div class="empty-state">尚未提取变量</div>';
        }
    }
    
    if (relationsContainer) {
        if (model && model.relations && model.relations.length > 0) {
            relationsContainer.innerHTML = '<h5>关系定义</h5>' + model.relations.map(r => `
                <div class="model-rel-item">
                    <div class="rel-name">${escapeHtml(r.name || r.source + ' → ' + r.target)}</div>
                    <div class="rel-desc">${escapeHtml(r.description || r.type || '')}</div>
                </div>
            `).join('');
        } else {
            relationsContainer.innerHTML = '<h5>关系定义</h5><div class="empty-state">尚未提取关系</div>';
        }
    }
    
    if (constraintsContainer) {
        if (model && model.constraints && model.constraints.length > 0) {
            constraintsContainer.innerHTML = '<h5>约束条件</h5>' + model.constraints.map(c => `
                <div class="model-constraint-item">
                    <div class="constraint-name">${escapeHtml(c.name || c.expression)}</div>
                    ${c.description ? `<div class="constraint-desc">${escapeHtml(c.description)}</div>` : ''}
                </div>
            `).join('');
        } else {
            constraintsContainer.innerHTML = '<h5>约束条件</h5><div class="empty-state">尚未定义约束</div>';
        }
    }
}

function updateProjectSelects() {
    ['modelingProjectSelect', 'predictionProjectSelect', 'kbProjectSelect'].forEach(selectId => {
        const select = document.getElementById(selectId);
        if (!select) return;
        
        const currentValue = select.value;
        select.innerHTML = '<option value="">选择项目...</option>' + 
            state.projects.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join('');
        
        if (currentValue && state.projects.find(p => p.id === currentValue)) {
            select.value = currentValue;
        } else if (state.currentProject) {
            select.value = state.currentProject.id;
        }
    });
}

function getKbProjectId() {
    const sel = document.getElementById('kbProjectSelect');
    return sel?.value?.trim() || '';
}

async function refreshKbStatus() {
    const pid = getKbProjectId();
    const el = document.getElementById('kbStatus');
    if (!el) return;
    if (!pid) {
        el.innerHTML = '<p class="placeholder">请先选择项目</p>';
        return;
    }
    if (!isPywebviewApiCallable()) return;
    try {
        const r = await window.pywebview.api.knowledge_base_status(pid);
        if (!r.ok) {
            el.innerHTML = `<p class="error-text">${escapeHtml(r.error || '状态获取失败')}</p>`;
            return;
        }
        const rows = r.row_count != null ? r.row_count : '—';
        const ex = r.exists ? '已创建' : '未创建';
        el.innerHTML = `
            <p><strong>集合</strong>：<code>${escapeHtml(r.collection || '')}</code></p>
            <p><strong>状态</strong>：${ex}</p>
            <p><strong>条目数</strong>：${rows}</p>
        `;
    } catch (e) {
        el.innerHTML = `<p class="error-text">${escapeHtml(String(e))}</p>`;
    }
}

async function kbPickAndImport() {
    const pid = getKbProjectId();
    if (!pid) {
        showToast('请先选择项目', 'warning');
        return;
    }
    if (!isPywebviewApiCallable()) return;
    try {
        const pick = await window.pywebview.api.knowledge_base_pick_file();
        if (pick.cancelled) return;
        if (!pick.success) {
            showToast(pick.error || '未选择文件', 'error');
            return;
        }
        const path = pick.path;
        showToast('正在导入…', 'info');
        const r = await window.pywebview.api.knowledge_base_import(pid, path);
        if (r.ok) {
            showToast(`已导入 ${r.chunks || 0} 个分块`, 'success');
            await refreshKbStatus();
        } else {
            showToast(r.error || '导入失败', 'error');
        }
    } catch (e) {
        showToast(String(e), 'error');
    }
}

async function kbRunSearch() {
    const pid = getKbProjectId();
    const q = document.getElementById('kbSearchInput')?.value?.trim() || '';
    const out = document.getElementById('kbSearchResults');
    if (!out) return;
    if (!pid) {
        showToast('请先选择项目', 'warning');
        return;
    }
    if (!q) {
        showToast('请输入查询', 'warning');
        return;
    }
    if (!isPywebviewApiCallable()) return;
    try {
        const r = await window.pywebview.api.knowledge_base_search(pid, q, 5);
        if (!r.ok) {
            out.innerHTML = `<p class="error-text">${escapeHtml(r.error || '')}</p>`;
            return;
        }
        const hits = r.hits || [];
        if (hits.length === 0) {
            out.innerHTML = '<p class="placeholder">无结果</p>';
            return;
        }
        out.innerHTML = hits.map((h, i) => `
            <div class="kb-hit">
                <div class="kb-hit-meta">#${i + 1} · ${escapeHtml(h.source_name || '')} · chunk ${h.chunk_index} · dist ${h.distance != null ? h.distance.toFixed(4) : '—'}</div>
                <div class="kb-hit-text">${escapeHtml((h.text || '').slice(0, 1200))}</div>
            </div>
        `).join('');
    } catch (e) {
        out.innerHTML = `<p class="error-text">${escapeHtml(String(e))}</p>`;
    }
}

function bindKnowledgeEvents() {
    document.getElementById('kbRefreshBtn')?.addEventListener('click', () => refreshKbStatus());
    document.getElementById('kbImportBtn')?.addEventListener('click', () => kbPickAndImport());
    document.getElementById('kbSearchBtn')?.addEventListener('click', () => kbRunSearch());
    document.getElementById('kbProjectSelect')?.addEventListener('change', () => refreshKbStatus());
}

const UAP_TYPEWRITER_BASE_MS = 18;
const UAP_TYPEWRITER_CHARS = 1;

function uapPrefersReducedMotion() {
    try {
        return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    } catch (e) {
        return false;
    }
}

function _typewriterTiming(len) {
    const l = len || 0;
    if (l > 3500) return { ms: 6, chars: 2 };
    if (l > 1200) return { ms: 10, chars: 1 };
    return { ms: UAP_TYPEWRITER_BASE_MS, chars: UAP_TYPEWRITER_CHARS };
}

/**
 * 在已有 text 节点上跑打字机（textContent，无 HTML）。
 */
function runTypewriterEffect(textDiv, fullText, scrollParent) {
    if (!textDiv) {
        return Promise.resolve();
    }
    const full = fullText == null ? '' : String(fullText);
    const scrollEl =
        scrollParent ||
        (textDiv.closest && textDiv.closest('.chat-messages')) ||
        textDiv.parentElement;

    if (uapPrefersReducedMotion() || !full.length) {
        textDiv.textContent = full;
        if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
        return Promise.resolve();
    }

    const { ms, chars } = _typewriterTiming(full.length);
    return new Promise((resolve) => {
        let i = 0;
        const step = () => {
            if (i >= full.length) {
                if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
                resolve();
                return;
            }
            const n = Math.min(full.length, i + chars);
            textDiv.textContent += full.slice(i, n);
            i = n;
            if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
            setTimeout(step, ms);
        };
        textDiv.textContent = '';
        step();
    });
}

/**
 * 建模助手纯文本气泡 + 打字机（兼容旧调用）。
 */
function appendAssistantTypewriter(content, timestamp) {
    const container = document.getElementById('chatMessages');
    if (!container) return Promise.resolve();

    const messageEl = document.createElement('div');
    messageEl.className = 'message assistant';
    const timeStr = formatTime(timestamp);
    messageEl.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-content">
            <div class="message-text" style="white-space: pre-wrap;"></div>
            <div class="message-time">${escapeHtml(timeStr)}</div>
        </div>
    `;
    const textDiv = messageEl.querySelector('.message-text');
    container.appendChild(messageEl);
    return runTypewriterEffect(textDiv, content, container);
}

function extractModelingSummaryText(fullMessage) {
    const s = fullMessage == null ? '' : String(fullMessage);
    const idx = s.indexOf('\n\n[');
    return (idx >= 0 ? s.slice(0, idx) : s).trim();
}

function safeJsonForPre(obj, maxLen = 12000) {
    try {
        let s = JSON.stringify(obj, null, 2);
        if (s.length > maxLen) {
            s = s.slice(0, maxLen - 1) + '…';
        }
        return s;
    } catch (e) {
        return String(obj);
    }
}

/** 避免单步内容过大导致 innerHTML 长时间阻塞主线程（界面像卡在「正在分析」） */
function truncateModelingUiText(s, maxLen) {
    const t = String(s || '');
    if (t.length <= maxLen) return t;
    return `${t.slice(0, maxLen - 1)}…\n\n（已截断显示）`;
}

function formatModelingStepBodyHtml(step) {
    const parts = [];
    const th = truncateModelingUiText((step.thought || '').trim(), 6000);
    if (th) {
        parts.push(
            `<div class="mt-block"><span class="mt-label">思考</span><pre class="mt-pre">${escapeHtml(th)}</pre></div>`
        );
    }
    const act = (step.action || '').trim();
    const desc = truncateModelingUiText((step.description || '').trim(), 8000);
    if (desc && act === 'plan_step') {
        parts.push(
            `<div class="mt-block"><span class="mt-label">步骤说明</span><pre class="mt-pre">${escapeHtml(desc)}</pre></div>`
        );
    }
    if (act && act !== 'FINAL_ANSWER') {
        const inp = step.action_input;
        let extra = '';
        if (inp && typeof inp === 'object' && Object.keys(inp).length) {
            extra = `<pre class="mt-pre">${escapeHtml(safeJsonForPre(inp))}</pre>`;
        }
        parts.push(
            `<div class="mt-block"><span class="mt-label">工具调用</span><div class="mt-pre" style="white-space:pre-wrap;font-weight:600;margin-bottom:4px">${escapeHtml(act)}</div>${extra}</div>`
        );
    }
    const obs = truncateModelingUiText((step.observation || '').trim(), 12000);
    if (obs) {
        const lab = act === 'FINAL_ANSWER' ? '最终回复' : '观察 / 回复';
        parts.push(
            `<div class="mt-block"><span class="mt-label">${lab}</span><pre class="mt-pre">${escapeHtml(obs)}</pre></div>`
        );
    }
    if (step.is_error || step.error_message) {
        const err = truncateModelingUiText((step.error_message || '').trim() || '错误', 4000);
        parts.push(
            `<div class="mt-block"><span class="mt-label">错误</span><pre class="mt-pre">${escapeHtml(err)}</pre></div>`
        );
    }
    if (step.tool_name && act !== step.tool_name) {
        parts.push(
            `<div class="mt-block"><span class="mt-label">工具名</span><pre class="mt-pre">${escapeHtml(String(step.tool_name))}</pre></div>`
        );
    }
    return parts.join('') || '<div class="mt-block hint">（无详情）</div>';
}

function modelingStepSummaryLine(step, index1) {
    const act = (step.action || '').trim();
    if (act === 'FINAL_ANSWER') return `第${index1}步 · 最终回复`;
    if (act === 'ask_user') return `第${index1}步 · 追问用户`;
    if (act === 'plan_step') return `第${index1}步 · 计划步骤`;
    return `第${index1}步 · ${act || '执行'}`;
}

/** 摘要行：标题 + 思考预览 + 复制（折叠时也可一键复制正文） */
function modelingStepSummaryHtml(step, index1) {
    const sum = modelingStepSummaryLine(step, index1);
    const sumEsc = escapeHtml(sum);
    const th = (step.thought || '').trim();
    let preview = '';
    let showEllipsis = false;
    if (th) {
        const oneLine = th.replace(/\s+/g, ' ');
        preview = truncateModelingUiText(oneLine, 96);
        showEllipsis = oneLine.length > 96;
    }
    const prevEsc = preview ? escapeHtml(preview) : '';
    return (
        '<span class="mt-sum-text">' +
        `<span class="mt-sum-title">${sumEsc}</span>` +
        (preview
            ? `<span class="mt-sum-preview"> · ${prevEsc}${showEllipsis ? '…' : ''}</span>`
            : '') +
        '</span>' +
        '<button type="button" class="mt-copy-btn" aria-label="复制本步内容" title="复制本步（思考、工具与观察）">复制</button>'
    );
}

function bindModelingTraceCopyButtons(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('details.mt-step .mt-copy-btn').forEach((btn) => {
        if (btn.dataset.uapCopyBound) return;
        btn.dataset.uapCopyBound = '1';
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            const det = btn.closest('details.mt-step');
            const body = det && det.querySelector('.mt-body');
            const text = body ? body.innerText : '';
            if (!text) return;
            const done = () => {
                if (typeof showToast === 'function') showToast('已复制本步内容', 'success');
            };
            const fail = () => {
                try {
                    window.prompt('请手动复制：', text);
                } catch (err) {
                    console.error(err);
                }
            };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(done).catch(fail);
            } else {
                fail();
            }
        });
    });
}

const UAP_MODELING_TRACE_MAX_STEPS = 60;

function buildModelingTraceHtml(steps) {
    if (!steps || !steps.length) {
        return '<div class="hint" style="padding:8px">本回合无分步轨迹（例如规划 JSON 解析失败或未进入 ReAct/Plan 循环）。</div>';
    }
    const total = steps.length;
    const slice =
        total > UAP_MODELING_TRACE_MAX_STEPS
            ? steps.slice(total - UAP_MODELING_TRACE_MAX_STEPS)
            : steps;
    const offset = total - slice.length;
    const headNote =
        offset > 0
            ? `<div class="hint" style="padding:8px">步数较多，仅展示最近 ${slice.length} 步（共 ${total} 步）。</div>`
            : '';
    return (
        headNote +
        slice
            .map((step, i) => {
                const index1 = offset + i + 1;
                const sumHtml = modelingStepSummaryHtml(step, index1);
                const body = formatModelingStepBodyHtml(step);
                const isLast = i === slice.length - 1;
                const openAttr = isLast ? ' open' : '';
                return `<details class="mt-step"${openAttr}><summary class="mt-summary-row">${sumHtml}</summary><div class="mt-body">${body}</div></details>`;
            })
            .join('')
    );
}

function normalizeDstStageForUi(raw) {
    const s = String(raw || '')
        .toLowerCase()
        .replace(/^modelingstage\./, '');
    const m = {
        initial: 'INITIAL',
        intent: 'INTENT',
        variables: 'VARIABLES',
        relations: 'RELATIONS',
        constraints: 'CONSTRAINTS',
        validation: 'VALIDATION',
        prediction: 'VALIDATION',
        completed: 'COMPLETED',
    };
    return m[s] || 'INITIAL';
}

function syncModelingDstPanel(dst) {
    if (!dst || typeof dst !== 'object' || Object.keys(dst).length === 0) return;
    const uiStage = normalizeDstStageForUi(dst.current_stage);
    const prog = typeof dst.progress === 'number' ? dst.progress : 0;
    const details = {};
    if (dst.intent) details['意图'] = dst.intent;
    if (dst.scene) details['场景'] = dst.scene;
    if (Array.isArray(dst.variables)) details['变量数'] = String(dst.variables.length);
    if (Array.isArray(dst.relations)) details['关系数'] = String(dst.relations.length);
    if (dst.constraints_count != null) details['约束条数'] = String(dst.constraints_count);
    updateDSTStatus(uiStage, prog, details);
}

function renderModelingProcessPanel(response) {
    const badge = document.getElementById('processStatus');
    const box = document.getElementById('processSteps');
    if (!box) return;

    const ok = response && response.ok !== false;
    const success = !!(response && response.success);
    const pendingIn = !!(response && response.pending_user_input);
    const m = response && response.model;
    const substantiveFromModel =
        m &&
        typeof m === 'object' &&
        ((Array.isArray(m.variables) && m.variables.length > 0) ||
            (Array.isArray(m.relations) && m.relations.length > 0) ||
            (Array.isArray(m.constraints) && m.constraints.length > 0));
    const substantive =
        !!(response && response.modeling_substantive) || substantiveFromModel;

    let st = 'idle';
    let badgeText = '空闲';
    if (!ok) {
        st = 'error';
        badgeText = '错误';
    } else if (pendingIn) {
        st = 'running';
        badgeText = '待您回复';
    } else if (success && substantive) {
        st = 'completed';
        badgeText = '已完成';
    } else if (success) {
        st = 'partial';
        badgeText = '已结束';
    } else {
        st = 'partial';
        badgeText = '已结束';
    }

    if (badge) {
        badge.className = `status-badge ${st}`;
        badge.textContent = badgeText;
    }

    const mu = ((response && response.mode_used) || '').toString().trim().toLowerCase();
    const mr = ((response && response.mode_requested) || '').toString().trim().toLowerCase();
    let modeLabel = mu === 'plan' ? 'Plan' : 'ReAct';
    if (mr === 'auto' && mu) modeLabel = `Auto→${mu}`;

    const steps = (response && response.steps) || [];
    const header = `<div class="process-step completed" style="border-left-color:#6366f1"><div class="step-header"><span class="step-name">模式 · ${escapeHtml(modeLabel)}</span><span class="step-status">${steps.length} 步</span></div></div>`;

    if (!steps.length) {
        box.innerHTML =
            header +
            '<div class="empty-state">无结构化步骤数据（可查看左侧聊天中的汇总说明）</div>';
        return;
    }
    box.innerHTML = header + buildModelingTraceHtml(steps);
    bindModelingTraceCopyButtons(box);
}

/**
 * 建模成功：轨迹（可折叠）+ 汇总打字机；并刷新进程 / DST 侧栏。
 */
const UAP_MODELING_SUMMARY_TYPEWRITER_MAX = 8000;

async function appendModelingAssistantWithTrace(response) {
    const container = document.getElementById('chatMessages');
    if (!container) return;

    const fullMsg = response.message != null ? String(response.message) : '';
    let summary = extractModelingSummaryText(fullMsg);
    if (summary.length > UAP_MODELING_SUMMARY_TYPEWRITER_MAX) {
        summary =
            summary.slice(0, UAP_MODELING_SUMMARY_TYPEWRITER_MAX - 40) +
            '\n\n…（汇总过长，已截断显示）';
    }
    const traceHtml = buildModelingTraceHtml(response.steps || []);
    const timeStr = formatTime(new Date().toISOString());

    const wrap = document.createElement('div');
    wrap.className = 'message assistant modeling-response';
    wrap.innerHTML = `
        <div class="message-avatar">🤖</div>
        <div class="message-content modeling-response-inner">
            <div class="modeling-trace">${traceHtml}</div>
            <div class="modeling-summary">
                <div class="modeling-summary-label">助手汇总</div>
                <div class="message-text modeling-typewriter-target" style="white-space: pre-wrap;"></div>
                <div class="message-time">${escapeHtml(timeStr)}</div>
            </div>
        </div>
    `;
    container.appendChild(wrap);
    bindModelingTraceCopyButtons(wrap);
    const target = wrap.querySelector('.modeling-typewriter-target');
    try {
        renderModelingProcessPanel(response);
        if (response.dst_state) syncModelingDstPanel(response.dst_state);
        switchAgentTab('process');
    } catch (e) {
        console.error('[modeling] 侧栏刷新失败:', e);
    }

    await runTypewriterEffect(target, summary, container);
    const inner = wrap.querySelector('.modeling-response-inner');
    if (
        inner &&
        response.pending_ask_user_card &&
        state.currentProject &&
        isPywebviewApiCallable()
    ) {
        try {
            mountInlineAskUserCard(inner, response.pending_ask_user_card, state.currentProject.id);
        } catch (e) {
            console.error('[modeling] 追问卡片挂载失败:', e);
        }
    }
}

/**
 * 建模追问 IM 卡片：默认选项、手输、提交后 modeling_chat；拒绝/超时由后端处理。
 */
function mountInlineAskUserCard(containerEl, card, projectId) {
    if (!containerEl || !card || !card.card_id) return;
    if (containerEl.querySelector('.uap-ask-user-card')) return;

    const cardId = String(card.card_id);
    const title = escapeHtml(card.title || '需要你的确认');
    const content = escapeHtml(card.content || '').replace(/\n/g, '<br>');
    const opts = Array.isArray(card.options) ? card.options : [];
    const defaultId = card.default_option_id != null ? String(card.default_option_id) : '';

    const wrap = document.createElement('div');
    wrap.className = 'uap-ask-user-card';
    wrap.dataset.cardId = cardId;

    let optionsHtml = '';
    opts.forEach((o) => {
        const oid = escapeHtml(String(o.id != null ? o.id : ''));
        const lab = escapeHtml(String(o.label || o.id || ''));
        const sel =
            oid === defaultId ? ' is-default is-selected' : '';
        optionsHtml += `<button type="button" class="uap-ask-user-opt${sel}" data-opt-id="${oid}">${lab}</button>`;
    });

    wrap.innerHTML = `
        <div class="uap-ask-user-card-title">${title}</div>
        <div class="uap-ask-user-card-body">${content}</div>
        <div class="uap-ask-user-card-options">${optionsHtml}</div>
        <input type="text" class="uap-ask-user-custom" placeholder="或手动输入回答…" autocomplete="off" />
        <div class="uap-ask-user-card-actions">
            <button type="button" class="btn btn-primary uap-ask-user-submit">提交</button>
            <button type="button" class="btn btn-secondary uap-ask-user-reject">拒绝</button>
        </div>
        <div class="uap-ask-user-countdown hint"></div>
    `;
    containerEl.appendChild(wrap);

    const optButtons = wrap.querySelectorAll('.uap-ask-user-opt');
    const customInp = wrap.querySelector('.uap-ask-user-custom');
    const btnSub = wrap.querySelector('.uap-ask-user-submit');
    const btnRej = wrap.querySelector('.uap-ask-user-reject');
    const cdEl = wrap.querySelector('.uap-ask-user-countdown');

    function getMode() {
        const sel = document.getElementById('modelingModeSelect');
        return sel && sel.value ? sel.value : 'auto';
    }

    function labelForId(id) {
        const o = opts.find((x) => String(x.id) === String(id));
        return o ? String(o.label || o.id) : String(id);
    }

    optButtons.forEach((b) => {
        b.addEventListener('click', () => {
            optButtons.forEach((x) => x.classList.remove('is-selected'));
            b.classList.add('is-selected');
            if (customInp) customInp.value = '';
        });
    });

    let cdTimer = null;
    if (card.expires_at && cdEl) {
        const expMs = new Date(card.expires_at).getTime();
        const tick = () => {
            const left = Math.max(0, Math.floor((expMs - Date.now()) / 1000));
            cdEl.textContent = left > 0 ? `剩余 ${left} 秒后将视为超时拒绝（不调模型）` : '';
            if (left <= 0 && cdTimer) {
                clearInterval(cdTimer);
                cdTimer = null;
            }
        };
        tick();
        cdTimer = setInterval(tick, 1000);
    }

    function disableAll() {
        optButtons.forEach((b) => {
            b.disabled = true;
        });
        if (customInp) customInp.disabled = true;
        if (btnSub) btnSub.disabled = true;
        if (btnRej) btnRej.disabled = true;
        if (cdTimer) clearInterval(cdTimer);
    }

    if (btnRej) {
        btnRej.addEventListener('click', async () => {
            if (!window.pywebview?.api?.reject_pending_ask_user) {
                showToast('当前版本不支持拒绝追问 API', 'warning');
                return;
            }
            disableAll();
            try {
                const r = await window.pywebview.api.reject_pending_ask_user(projectId, 'user_rejected');
                if (r && r.ok) {
                    showToast('已拒绝追问', 'success');
                } else {
                    showToast((r && r.message) || '拒绝失败', 'warning');
                }
            } catch (e) {
                showToast('拒绝失败: ' + (e.message || e), 'error');
            }
        });
    }

    if (btnSub) {
        btnSub.addEventListener('click', async () => {
            const custom = (customInp && customInp.value.trim()) || '';
            const selectedBtn = wrap.querySelector('.uap-ask-user-opt.is-selected');
            const optId = selectedBtn ? selectedBtn.getAttribute('data-opt-id') : '';

            if (!custom && !optId) {
                showToast('请选择一项或输入回答', 'warning');
                return;
            }
            if (optId === '__reject__') {
                if (btnRej) btnRej.click();
                return;
            }

            disableAll();
            try {
                if (custom) {
                    const sr = await window.pywebview.api.submit_card_response(
                        cardId,
                        '__custom__'
                    );
                    if (!sr || !sr.success) {
                        showToast('关闭追问卡片失败', 'error');
                        return;
                    }
                    await sendModelingMessageRaw(projectId, custom, getMode());
                } else if (optId) {
                    const sr = await window.pywebview.api.submit_card_response(cardId, optId);
                    if (!sr || !sr.success) {
                        showToast('提交选项失败', 'error');
                        return;
                    }
                    const msg = `用户选择：${labelForId(optId)}`;
                    await sendModelingMessageRaw(projectId, msg, getMode());
                }
            } catch (e) {
                showToast('提交失败: ' + (e.message || e), 'error');
            }
        });
    }
}

/** 内部：展示用户气泡后发起 modeling_chat（与主发送按钮一致，由 API 持久化 user） */
async function sendModelingMessageRaw(projectId, message, mode) {
    if (!isPywebviewApiCallable()) return;
    appendChatMessage({
        type: 'user',
        content: message,
        timestamp: new Date().toISOString()
    });
    const loadingId = 'loading-' + Date.now();
    appendChatMessage({
        type: 'loading',
        id: loadingId,
        content: '正在分析...'
    });
    try {
        let response = null;
        if (isModelingStreamApiAvailable()) {
            const startResp = await window.pywebview.api.start_modeling_chat_stream(
                projectId,
                message,
                mode
            );
            if (!startResp || !startResp.ok || !startResp.stream_id) {
                removeLoadingMessage(loadingId);
                showToast((startResp && (startResp.error || startResp.message)) || '流式启动失败', 'error');
                return;
            }
            const sid = startResp.stream_id;
            let streamTextEl = null;
            let streamBuf = '';
            for (;;) {
                const pr = await window.pywebview.api.poll_modeling_chat_stream(sid);
                if (!pr) {
                    await uapSleepMs(100);
                    continue;
                }
                const batch = Array.isArray(pr.tokens) ? pr.tokens.join('') : '';
                if (batch) {
                    if (!streamTextEl) {
                        removeLoadingMessage(loadingId);
                        streamTextEl = appendModelingStreamLiveBubble(sid);
                    }
                    streamBuf += batch;
                    if (streamTextEl) streamTextEl.textContent = streamBuf;
                    const c = document.getElementById('chatMessages');
                    if (c) c.scrollTop = c.scrollHeight;
                }
                if (pr.done) {
                    if (!streamTextEl) removeLoadingMessage(loadingId);
                    removeModelingStreamLiveBubbles();
                    const res = pr.result;
                    if (!pr.ok) {
                        showToast(String(pr.error || '流异常'), 'error');
                        break;
                    }
                    if (res && res.ok) {
                        response = res;
                    } else {
                        const em =
                            pr.error ||
                            (res && res.message != null ? String(res.message) : '') ||
                            '建模失败';
                        showToast(em, 'error');
                    }
                    break;
                }
                await uapSleepMs(90);
            }
        } else {
            try {
                response = await window.pywebview.api.modeling_chat(projectId, message, mode);
            } finally {
                removeLoadingMessage(loadingId);
            }
        }
        await uapYieldToPaint();
        if (response && response.ok) {
            await appendModelingAssistantWithTrace(response);
            if (response.model) window.uapAPI.onModelExtracted(response.model);
        } else if (response) {
            await appendAssistantTypewriter(
                response.message != null ? String(response.message) : '建模失败',
                new Date().toISOString()
            );
        }
    } catch (e) {
        removeLoadingMessage(loadingId);
        showToast('建模失败: ' + (e.message || e), 'error');
    }
}

function uapYieldToPaint() {
    return new Promise((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(resolve));
    });
}

async function sendModelingMessage() {
    const input = document.getElementById('chatInput');
    const message = input?.value.trim();
    
    if (!message) return;
    if (!state.currentProject) {
        showToast('请先选择一个项目', 'warning');
        return;
    }
    
    // 添加用户消息
    appendChatMessage({
        type: 'user',
        content: message,
        timestamp: new Date().toISOString()
    });
    
    input.value = '';
    
    // 添加加载指示器
    const loadingId = 'loading-' + Date.now();
    appendChatMessage({
        type: 'loading',
        id: loadingId,
        content: '正在分析...'
    });
    
    try {
        if (isPywebviewApiCallable()) {
            const modeSelect = document.getElementById('modelingModeSelect');
            const mode = (modeSelect && modeSelect.value) ? modeSelect.value : 'auto';
            let response = null;
            if (isModelingStreamApiAvailable()) {
                let startResp;
                try {
                    startResp = await window.pywebview.api.start_modeling_chat_stream(
                        state.currentProject.id,
                        message,
                        mode
                    );
                } catch (e) {
                    removeLoadingMessage(loadingId);
                    throw e;
                }
                if (!startResp || !startResp.ok || !startResp.stream_id) {
                    removeLoadingMessage(loadingId);
                    const err =
                        (startResp && (startResp.error || startResp.message)) ||
                        '无法启动建模流';
                    showToast(String(err), 'error');
                    await appendAssistantTypewriter(String(err), new Date().toISOString());
                    return;
                }
                const sid = startResp.stream_id;
                let streamTextEl = null;
                let streamBuf = '';
                for (;;) {
                    const pr = await window.pywebview.api.poll_modeling_chat_stream(sid);
                    if (!pr) {
                        await uapSleepMs(100);
                        continue;
                    }
                    const batch = Array.isArray(pr.tokens) ? pr.tokens.join('') : '';
                    if (batch) {
                        if (!streamTextEl) {
                            removeLoadingMessage(loadingId);
                            streamTextEl = appendModelingStreamLiveBubble(sid);
                        }
                        streamBuf += batch;
                        if (streamTextEl) {
                            streamTextEl.textContent = streamBuf;
                        }
                        const c = document.getElementById('chatMessages');
                        if (c) c.scrollTop = c.scrollHeight;
                    }
                    if (pr.done) {
                        if (!streamTextEl) {
                            removeLoadingMessage(loadingId);
                        }
                        removeModelingStreamLiveBubbles();
                        const res = pr.result;
                        if (!pr.ok) {
                            const em = pr.error || '建模流异常';
                            showToast(String(em), 'error');
                            await appendAssistantTypewriter(
                                String(em),
                                new Date().toISOString()
                            );
                            renderModelingProcessPanel({ ok: false, steps: [], success: false });
                        } else if (res && res.ok) {
                            response = res;
                        } else {
                            const em =
                                pr.error ||
                                (res && res.message != null ? String(res.message) : '') ||
                                '建模失败';
                            await appendAssistantTypewriter(em, new Date().toISOString());
                            renderModelingProcessPanel({
                                ok: false,
                                steps: (res && res.steps) || [],
                                success: false
                            });
                            if (res && res.dst_state) {
                                syncModelingDstPanel(res.dst_state);
                            }
                            switchAgentTab('process');
                        }
                        break;
                    }
                    await uapSleepMs(90);
                }
            } else {
                try {
                    response = await window.pywebview.api.modeling_chat(
                        state.currentProject.id,
                        message,
                        mode
                    );
                } finally {
                    removeLoadingMessage(loadingId);
                }
            }
            await uapYieldToPaint();
            if (response && response.ok) {
                try {
                    await appendModelingAssistantWithTrace(response);
                } catch (renderErr) {
                    console.error('建模结果渲染失败:', renderErr);
                    showToast(
                        '建模结果渲染失败: ' + (renderErr.message || String(renderErr)),
                        'error'
                    );
                    await appendAssistantTypewriter(
                        response.message != null
                            ? String(response.message)
                            : '（渲染失败，请查看控制台）',
                        new Date().toISOString()
                    );
                }
                if (response.model) {
                    window.uapAPI.onModelExtracted(response.model);
                }
            } else if (response) {
                await appendAssistantTypewriter(
                    response.message != null ? response.message : '建模失败',
                    new Date().toISOString()
                );
                renderModelingProcessPanel({ ok: false, steps: [], success: false });
                if (response.dst_state) syncModelingDstPanel(response.dst_state);
                switchAgentTab('process');
            }
        } else {
            // 演示模式
            setTimeout(async () => {
                removeLoadingMessage(loadingId);
                await appendAssistantTypewriter(
                    `已收到：「${message}」（演示模式）\n\n我会像真实环境一样先澄清目标与时间范围，再逐步建模。请连接后端以使用完整智能体。`,
                    new Date().toISOString()
                );
            }, 1000);
        }
    } catch (e) {
        console.error('建模失败:', e);
        removeLoadingMessage(loadingId);
        showToast('建模失败: ' + e.message, 'error');
    }
}

function appendChatMessage(message) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    
    const messageEl = document.createElement('div');
    messageEl.className = `message ${message.type}`;
    
    if (message.type === 'loading') {
        messageEl.id = message.id;
        messageEl.innerHTML = `
            <div class="message-content">
                <div class="loading-dots">
                    <span></span><span></span><span></span>
                </div>
                <p>${escapeHtml(message.content)}</p>
            </div>
        `;
    } else {
        const roleIcon = message.type === 'user' ? '👤' : '🤖';
        messageEl.innerHTML = `
            <div class="message-avatar">${roleIcon}</div>
            <div class="message-content">
                <div class="message-text">${escapeHtml(message.content).replace(/\n/g, '<br>')}</div>
                <div class="message-time">${formatTime(message.timestamp)}</div>
            </div>
        `;
    }
    
    container.appendChild(messageEl);
    container.scrollTop = container.scrollHeight;
}

function removeLoadingMessage(id) {
    const el = document.getElementById(id);
    if (el) el.remove();
}

function renderModelPreview(model) {
    const preview = document.getElementById('modelPreview');
    if (!preview) return;
    
    if (!model) {
        preview.innerHTML = '<p class="placeholder">尚未提取模型</p>';
        return;
    }
    
    preview.innerHTML = `
        <div class="model-section">
            <h4>状态变量</h4>
            <div class="variable-list">
                ${(model.variables || []).map(v => `
                    <div class="variable-item">
                        <span class="var-name">${escapeHtml(v.name)}</span>
                        <span class="var-unit">${escapeHtml(v.unit || '')}</span>
                    </div>
                `).join('') || '<p class="hint">暂无变量</p>'}
            </div>
        </div>
        <div class="model-section">
            <h4>状态方程</h4>
            <div class="equation-list">
                ${(model.equations || []).map(eq => `
                    <div class="equation-item">${escapeHtml(eq)}</div>
                `).join('') || '<p class="hint">暂无方程</p>'}
            </div>
        </div>
    `;
}

// ==================== 预测功能 ====================

function bindPredictionEvents() {
    const projectSelect = document.getElementById('predictionProjectSelect');
    if (projectSelect) {
        projectSelect.addEventListener('change', async (e) => {
            if (e.target.value) {
                await openProject(e.target.value);
            }
        });
    }
    
    const frequencySelect = document.getElementById('predictionFrequency');
    if (frequencySelect) {
        frequencySelect.addEventListener('change', async (e) => {
            if (state.currentProject) {
                await updatePredictionConfig();
            }
        });
    }
    
    const horizonInput = document.getElementById('predictionHorizon');
    if (horizonInput) {
        horizonInput.addEventListener('change', async () => {
            if (state.currentProject) {
                await updatePredictionConfig();
            }
        });
    }
    
    const startBtn = document.getElementById('startPredictionBtn');
    if (startBtn) {
        startBtn.addEventListener('click', startPrediction);
    }
    
    const stopBtn = document.getElementById('stopPredictionBtn');
    if (stopBtn) {
        stopBtn.addEventListener('click', stopPrediction);
    }
}

async function updatePredictionConfig() {
    const frequency = document.getElementById('predictionFrequency')?.value;
    const horizon = document.getElementById('predictionHorizon')?.value;
    
    if (!state.currentProject || !frequency) return;
    
    try {
        if (isPywebviewApiCallable()) {
            await window.pywebview.api.update_prediction_config(
                state.currentProject.id,
                parseInt(frequency),
                parseInt(horizon || 259200)
            );
            showToast('预测配置已更新', 'success');
        }
    } catch (e) {
        console.error('更新配置失败:', e);
    }
}

async function startPrediction() {
    if (!state.currentProject) {
        showToast('请先选择一个项目', 'warning');
        return;
    }
    
    if (!state.currentProject.model) {
        showToast('该项目尚未完成建模或数据配置。请先在对话里用一句话开始目标，完成建模后再开定时预测。', 'warning');
        return;
    }
    
    try {
        if (isPywebviewApiCallable()) {
            await window.pywebview.api.start_prediction(state.currentProject.id);
            showToast('预测任务已启动', 'success');
            updateTaskStatus({ running: true, next_run: '即将开始' });
        } else {
            showToast('演示模式：预测任务已启动', 'info');
            updateTaskStatus({ running: true, next_run: '1分钟后' });
        }
    } catch (e) {
        console.error('启动预测失败:', e);
        showToast('启动预测失败', 'error');
    }
}

async function stopPrediction() {
    try {
        if (isPywebviewApiCallable()) {
            await window.pywebview.api.stop_prediction(state.currentProject?.id);
            showToast('预测任务已停止', 'info');
        }
        updateTaskStatus({ running: false });
    } catch (e) {
        console.error('停止预测失败:', e);
    }
}

function updateTaskStatus(status) {
    const statusEl = document.getElementById('taskStatus');
    if (!statusEl) return;
    
    if (status.running) {
        statusEl.innerHTML = `
            <p>任务状态: <span class="status-running">运行中</span></p>
            <p>下次预测: ${status.next_run || '计算中...'}</p>
        `;
        document.getElementById('startPredictionBtn')?.style.setProperty('display', 'none');
        document.getElementById('stopPredictionBtn')?.style.removeProperty('display');
    } else {
        statusEl.innerHTML = '<p>任务状态: 已停止</p>';
        document.getElementById('startPredictionBtn')?.style.removeProperty('display');
        document.getElementById('stopPredictionBtn')?.style.setProperty('display', 'none');
    }
}

function renderPredictionResults(result) {
    const resultsList = document.getElementById('resultsList');
    if (!resultsList) return;
    
    if (!result) {
        resultsList.innerHTML = '<p class="placeholder">暂无预测结果</p>';
        return;
    }
    
    resultsList.innerHTML = `
        <div class="prediction-result">
            <div class="result-header">
                <span class="result-time">${formatTime(result.timestamp)}</span>
                <span class="result-confidence">置信度: ${((result.confidence || 0.9) * 100).toFixed(0)}%</span>
            </div>
            <div class="result-summary">
                ${result.summary || '预测完成'}
            </div>
            ${result.anomalies?.length ? `
                <div class="result-anomalies">
                    <h4>检测到异常</h4>
                    ${result.anomalies.map(a => `<span class="anomaly-tag">${escapeHtml(a)}</span>`).join('')}
                </div>
            ` : ''}
        </div>
    ` + resultsList.innerHTML;
}

// ==================== 设置功能 ====================

function setClassifierFieldsDisabled(disabled) {
    ['classifyLlmProvider', 'classifyLlmApiKey', 'classifyLlmModel', 'classifyLlmBaseUrl'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.disabled = !!disabled;
    });
}

function bindSettingsEvents() {
    const saveBtn = document.getElementById('saveSettingsBtn');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveSettings);
    }
    const prov = document.getElementById('llmProvider');
    if (prov) {
        prov.addEventListener('change', () => {
            applyLlmProviderPreset();
            updateLlmPresetHint();
        });
    }
    const clsSep = document.getElementById('classifierUseSeparate');
    if (clsSep) {
        clsSep.addEventListener('change', () => {
            setClassifierFieldsDisabled(!clsSep.checked);
        });
    }
}

function applyLlmProviderPreset() {
    const p = document.getElementById('llmProvider')?.value;
    const presets = state.settings.llmPresets || {};
    if (!p || !presets[p]) return;
    const pr = presets[p];
    const bu = document.getElementById('llmBaseUrl');
    const mo = document.getElementById('llmModel');
    if (bu && pr.base_url) bu.value = pr.base_url;
    if (mo && pr.model) mo.value = pr.model;
}

function updateLlmPresetHint() {
    const p = document.getElementById('llmProvider')?.value;
    const el = document.getElementById('llmPresetHint');
    const presets = state.settings.llmPresets || {};
    if (!el) return;
    const h = presets[p]?.hint;
    el.textContent = h ? `说明：${h}` : '';
}

async function loadSettings() {
    if (!isPywebviewApiCallable()) {
        console.warn('[UAP] loadSettings: _createApi 尚未完成，保留默认表单状态');
        showToast('无法读取系统设置：桌面 API 尚未就绪', 'warning');
        return;
    }
    console.log('[UAP] loadSettings: 请求 get_config …');
    try {
        const config = await window.pywebview.api.get_config();
        if (config) {
            const llm = config.llm || {};
            const predDefaults = config.prediction_defaults || {};
            const emb = config.embedding || {};
            const storage = config.storage || {};
            const ag = config.agent || {};
            const cl = ag.modeling_classifier_llm;
            const hasClassifier = cl != null && typeof cl === 'object';
            state.settings = {
                llmProvider: llm.provider || 'ollama',
                llmModel: llm.model || 'llama3.2',
                llmBaseUrl: llm.base_url || 'http://localhost:11434',
                llmApiKeySet: !!llm.api_key_set,
                llmPresets: config.llm_presets || {},
                defaultFrequency: predDefaults.frequency_sec || 3600,
                defaultHorizon: predDefaults.horizon_sec || 259200,
                embedModel: emb.model || 'qwen3-embedding:8b',
                embedBaseUrl: emb.base_url || '',
                embedDimension: emb.dimension != null ? emb.dimension : 4096,
                milvusLitePath: storage.milvus_lite_path || '',
                modelingIntentContextRounds:
                    ag.modeling_intent_context_rounds != null
                        ? ag.modeling_intent_context_rounds
                        : 2,
                reactMaxStepsDefault:
                    ag.react_max_steps_default != null ? ag.react_max_steps_default : 8,
                classifyUseSeparate: hasClassifier,
                classifyProvider: (hasClassifier && cl.provider) || llm.provider || 'ollama',
                classifyModel: (hasClassifier && cl.model) || llm.model || '',
                classifyBaseUrl: (hasClassifier && cl.base_url) || llm.base_url || '',
                classifyApiKeySet: !!(hasClassifier && cl.api_key_set)
            };
            console.log('[UAP] loadSettings: get_config 成功', {
                config_path: config.config_path,
                provider: state.settings.llmProvider,
                model: state.settings.llmModel
            });
        } else {
            console.warn('[UAP] loadSettings: get_config 返回空，未更新 state.settings');
        }
        renderSettings();
    } catch (e) {
        const msg = e?.message || String(e);
        console.error('[UAP] loadSettings: get_config 失败', e);
        showToast('读取系统设置失败：' + msg, 'error');
    }
}

function renderSettings() {
    const fields = [
        ['llmProvider', state.settings.llmProvider],
        ['llmModel', state.settings.llmModel],
        ['llmBaseUrl', state.settings.llmBaseUrl],
        ['defaultFrequency', state.settings.defaultFrequency],
        ['defaultHorizon', state.settings.defaultHorizon],
        ['embedModel', state.settings.embedModel],
        ['embedBaseUrl', state.settings.embedBaseUrl],
        ['embedDimension', state.settings.embedDimension],
        ['milvusLitePath', state.settings.milvusLitePath],
        ['modelingIntentContextRounds', state.settings.modelingIntentContextRounds],
        ['reactMaxStepsDefault', state.settings.reactMaxStepsDefault],
        ['classifyLlmProvider', state.settings.classifyProvider],
        ['classifyLlmModel', state.settings.classifyModel],
        ['classifyLlmBaseUrl', state.settings.classifyBaseUrl]
    ];

    fields.forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
    const clsChk = document.getElementById('classifierUseSeparate');
    if (clsChk) clsChk.checked = !!state.settings.classifyUseSeparate;
    setClassifierFieldsDisabled(!state.settings.classifyUseSeparate);
    const ckey = document.getElementById('classifyLlmApiKey');
    if (ckey) {
        ckey.value = '';
        ckey.placeholder = state.settings.classifyApiKeySet
            ? '已保存分类密钥（留空不修改）'
            : '留空则继承主 LLM 已保存密钥';
    }
    const keyEl = document.getElementById('llmApiKey');
    if (keyEl) {
        keyEl.value = '';
        keyEl.placeholder = state.settings.llmApiKeySet
            ? '已保存密钥（留空不修改；输入新值则覆盖）'
            : '远程厂商必填；本地 Ollama 可留空';
    }
    updateLlmPresetHint();
}

async function saveSettings() {
    const llm = {
        provider: document.getElementById('llmProvider')?.value || 'ollama',
        model: document.getElementById('llmModel')?.value || 'llama3.2',
        base_url: document.getElementById('llmBaseUrl')?.value || 'http://localhost:11434'
    };
    const apiKey = document.getElementById('llmApiKey')?.value?.trim();
    if (apiKey) {
        llm.api_key = apiKey;
    }
    const embedding = {
        model: document.getElementById('embedModel')?.value || 'qwen3-embedding:8b',
        base_url: document.getElementById('embedBaseUrl')?.value?.trim() || '',
        dimension: parseInt(document.getElementById('embedDimension')?.value || 4096, 10)
    };
    const milvusPath = document.getElementById('milvusLitePath')?.value?.trim() || '';

    const roundsRaw = parseInt(
        document.getElementById('modelingIntentContextRounds')?.value || '2',
        10
    );
    const modeling_intent_context_rounds = Math.max(0, Math.min(20, Number.isFinite(roundsRaw) ? roundsRaw : 2));
    const stepsRaw = parseInt(
        document.getElementById('reactMaxStepsDefault')?.value || '8',
        10
    );
    const react_max_steps_default = Math.max(
        1,
        Math.min(32, Number.isFinite(stepsRaw) ? stepsRaw : 8)
    );
    const useClsSep = document.getElementById('classifierUseSeparate')?.checked;
    const agent = { modeling_intent_context_rounds, react_max_steps_default };
    if (!useClsSep) {
        agent.modeling_classifier_llm = null;
    } else {
        const sub = {};
        const cp = document.getElementById('classifyLlmProvider')?.value?.trim();
        const cm = document.getElementById('classifyLlmModel')?.value?.trim();
        const cb = document.getElementById('classifyLlmBaseUrl')?.value?.trim();
        const ck = document.getElementById('classifyLlmApiKey')?.value?.trim();
        if (cp) sub.provider = cp;
        if (cm) sub.model = cm;
        if (cb) sub.base_url = cb;
        if (ck) sub.api_key = ck;
        agent.modeling_classifier_llm = Object.keys(sub).length ? sub : null;
    }

    const settings = {
        llm,
        embedding,
        storage: {
            milvus_lite_path: milvusPath
        },
        prediction_defaults: {
            frequency_sec: parseInt(document.getElementById('defaultFrequency')?.value || 3600),
            horizon_sec: parseInt(document.getElementById('defaultHorizon')?.value || 259200)
        },
        agent
    };

    try {
        if (!isPywebviewApiCallable()) {
            console.warn('[UAP] saveSettings: _createApi 尚未完成');
            showToast('无法保存设置：桌面 API 尚未就绪', 'warning');
            return;
        }
        const logPayload = {
            ...settings,
            llm: { ...settings.llm, api_key: apiKey ? '(已填写，已省略)' : undefined }
        };
        console.log('[UAP] saveSettings: 调用 update_config …', logPayload);
        await window.pywebview.api.update_config(settings);
        console.log('[UAP] saveSettings: update_config 成功');
        state.settings = {
            llmProvider: settings.llm.provider,
            llmModel: settings.llm.model,
            llmBaseUrl: settings.llm.base_url,
            llmApiKeySet: state.settings.llmApiKeySet || !!apiKey,
            llmPresets: state.settings.llmPresets,
            defaultFrequency: settings.prediction_defaults.frequency_sec,
            defaultHorizon: settings.prediction_defaults.horizon_sec,
            embedModel: embedding.model,
            embedBaseUrl: embedding.base_url,
            embedDimension: embedding.dimension,
            milvusLitePath: milvusPath,
            modelingIntentContextRounds: agent.modeling_intent_context_rounds,
            reactMaxStepsDefault: agent.react_max_steps_default,
            classifyUseSeparate: !!useClsSep && !!agent.modeling_classifier_llm,
            classifyProvider:
                agent.modeling_classifier_llm?.provider || settings.llm.provider,
            classifyModel: agent.modeling_classifier_llm?.model || settings.llm.model,
            classifyBaseUrl:
                agent.modeling_classifier_llm?.base_url || settings.llm.base_url,
            classifyApiKeySet:
                state.settings.classifyApiKeySet || !!agent.modeling_classifier_llm?.api_key
        };
        showToast('设置已保存', 'success');
        await loadSettings();
    } catch (e) {
        console.error('[UAP] saveSettings: update_config 失败', e);
        showToast('保存设置失败: ' + (e.message || e), 'error');
    }
}

// ==================== 工具函数 ====================

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatDate(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleDateString('zh-CN');
}

function formatTime(isoString) {
    if (!isoString) return '';
    const date = new Date(isoString);
    return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer') || createToastContainer();
    
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${type === 'success' ? '✓' : type === 'error' ? '✗' : type === 'warning' ? '⚠' : 'ℹ'}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
    `;
    
    container.appendChild(toast);
    
    setTimeout(() => toast.classList.add('show'), 10);
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 3000);
}

function createToastContainer() {
    const container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container';
    document.body.appendChild(container);
    return container;
}

// 暴露全局函数
window.openProject = openProject;
window.deleteProject = deleteProject;
window.sendModelingMessage = sendModelingMessage;
window.startPrediction = startPrediction;
window.stopPrediction = stopPrediction;
