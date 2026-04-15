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
        defaultFrequency: 3600,
        defaultHorizon: 259200
    }
};

// API暴露的方法（供PyWebView调用）
window.uapAPI = {
    // 获取项目列表
    getProjects: () => state.projects,
    
    // 创建项目回调
    onProjectCreated: (project) => {
        state.projects.push(project);
        renderProjectGrid();
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

document.addEventListener('DOMContentLoaded', () => {
    // 配置前端日志
    const originalConsoleLog = console.log;
    const originalConsoleError = console.error;
    
    // 添加时间戳前缀
    const formatTime = () => new Date().toISOString().split('T')[1].slice(0, 8);
    
    console.log = function(...args) {
        originalConsoleLog(`[${formatTime()}] [FRONTEND]`, ...args);
    };
    
    console.error = function(...args) {
        originalConsoleError(`[${formatTime()}] [FRONTEND-ERROR]`, ...args);
    };
    
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
    bindModalEvents();
    
    // 加载初始数据
    await loadProjects();
    await loadSettings();
    
    console.log('UAP initialized');
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
    if (viewName === 'modeling' || viewName === 'prediction') {
        updateProjectSelects();
    }
}

// ==================== 项目管理 ====================

async function loadProjects() {
    console.log('[API] Loading projects...');
    try {
        if (window.pywebview) {
            const projects = await window.pywebview.api.get_projects();
            console.log('[API] get_projects returned:', projects);
            state.projects = projects || [];
            renderProjectGrid();
        }
    } catch (e) {
        console.error('[API] Failed to load projects:', e);
        // 演示数据
        state.projects = [];
        renderProjectGrid();
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
                <span class="project-status ${project.model ? 'has-model' : 'no-model'}">
                    ${project.model ? '已建模' : '未建模'}
                </span>
            </div>
            <p class="project-description">${escapeHtml(project.description || '暂无描述')}</p>
            <div class="project-card-footer">
                <span class="project-date">${formatDate(project.created_at)}</span>
                <div class="project-actions">
                    <button class="btn-icon" onclick="openProjectFolder('${project.id}')" title="打开本地文件夹">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path>
                        </svg>
                    </button>
                    <button class="btn-icon" onclick="openProject('${project.id}')" title="打开">
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"></path>
                            <polyline points="15 3 21 3 21 9"></polyline>
                            <line x1="10" y1="14" x2="21" y2="3"></line>
                        </svg>
                    </button>
                    <button class="btn-icon danger" onclick="deleteProject('${project.id}', '${escapeHtml(project.name)}')" title="删除">
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
    try {
        if (window.pywebview) {
            const project = await window.pywebview.api.get_project(projectId);
            window.uapAPI.onProjectLoaded(project);
            switchView('modeling');
        }
    } catch (e) {
        console.error('Failed to open project:', e);
        showToast('打开项目失败', 'error');
    }
}

async function openProjectFolder(projectId) {
    try {
        if (window.pywebview) {
            const result = await window.pywebview.api.get_project_folder(projectId);
            if (result && result.folder_path) {
                window.pywebview.api.open_folder(result.folder_path);
                showToast('正在打开项目文件夹', 'info');
            } else {
                showToast('无法获取项目路径', 'error');
            }
        } else {
            showToast('演示模式：项目文件夹路径已获取', 'info');
        }
    } catch (e) {
        console.error('Failed to open project folder:', e);
        showToast('打开项目文件夹失败', 'error');
    }
}

async function deleteProject(projectId, projectName) {
    // 创建确认模态框
    const modal = document.getElementById('deleteConfirmModal') || createDeleteConfirmModal();
    
    document.getElementById('deleteProjectName').textContent = projectName;
    document.getElementById('deleteConfirmInput').value = '';
    document.getElementById('deleteConfirmBtn').disabled = true;
    
    // 监听输入变化
    const input = document.getElementById('deleteConfirmInput');
    const confirmBtn = document.getElementById('deleteConfirmBtn');
    
    const checkInput = () => {
        confirmBtn.disabled = input.value.trim() !== projectName;
    };
    input.oninput = checkInput;
    
    // 设置确认回调
    confirmBtn.onclick = async () => {
        if (input.value.trim() === projectName) {
            modal.classList.remove('active');
            await performDelete(projectId);
        }
    };
    
    modal.classList.add('active');
}

async function performDelete(projectId) {
    try {
        if (window.pywebview) {
            await window.pywebview.api.delete_project(projectId);
            window.uapAPI.onProjectDeleted(projectId);
        }
    } catch (e) {
        console.error('Failed to delete project:', e);
        showToast('删除项目失败', 'error');
    }
}

function createDeleteConfirmModal() {
    const modal = document.createElement('div');
    modal.className = 'modal';
    modal.id = 'deleteConfirmModal';
    modal.innerHTML = `
        <div class="modal-content modal-small">
            <div class="modal-header">
                <h3>确认删除项目</h3>
                <button class="modal-close" onclick="this.closest('.modal').classList.remove('active')">&times;</button>
            </div>
            <div class="modal-body">
                <p>确定要删除项目 <strong id="deleteProjectName"></strong> 吗？</p>
                <p class="hint">此操作不可恢复，项目文件夹将永久删除。</p>
                <div class="form-group">
                    <label>请输入项目名称进行确认：</label>
                    <input type="text" id="deleteConfirmInput" placeholder="输入项目名称">
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" onclick="this.closest('.modal').classList.remove('active')">取消</button>
                <button class="btn btn-danger" id="deleteConfirmBtn" disabled>确认删除</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    
    modal.addEventListener('click', (e) => {
        if (e.target === modal) modal.classList.remove('active');
    });
    
    return modal;
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
    
    // 点击背景关闭
    const modal = document.getElementById('createProjectModal');
    if (modal) {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) {
                closeModal('createProjectModal');
            }
        });
    }
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
        if (window.pywebview) {
            const project = await window.pywebview.api.create_project(name, description);
            window.uapAPI.onProjectCreated(project);
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
        showToast('创建项目失败', 'error');
    }
}

// ==================== 建模功能 ====================

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
}

function updateProjectSelects() {
    ['modelingProjectSelect', 'predictionProjectSelect'].forEach(selectId => {
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

async function sendModelingMessage() {
    const input = document.getElementById('chatInput');
    const message = input?.value.trim();
    
    if (!message) return;
    if (!state.currentProject) {
        showToast('请先选择一个项目', 'warning');
        return;
    }
    
    console.log('[Modeling] Sending message:', message.substring(0, 50) + '...');
    
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
        console.log('[Modeling] Calling modeling_chat API for project:', state.currentProject.id);
        if (window.pywebview) {
            const response = await window.pywebview.api.modeling_chat(
                state.currentProject.id,
                message
            );
            console.log('[Modeling] API response:', response);
            removeLoadingMessage(loadingId);
            if (response) {
                appendChatMessage({
                    type: 'assistant',
                    content: response.message || response,
                    timestamp: new Date().toISOString()
                });
                if (response.model) {
                    window.uapAPI.onModelExtracted(response.model);
                }
            }
        } else {
            // 演示模式
            setTimeout(() => {
                removeLoadingMessage(loadingId);
                appendChatMessage({
                    type: 'assistant',
                    content: `已收到您的描述：「${message}」。正在提取系统模型...\n\n检测到可能的系统类型：动态系统\n建议变量：x(t), y(t)\n状态方程：dx/dt = f(x, y)`,
                    timestamp: new Date().toISOString()
                });
            }, 1000);
        }
    } catch (e) {
        console.error('[Modeling] Modeling failed:', e);
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
        if (window.pywebview) {
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
        showToast('该项目尚未建模，请先进行系统建模', 'warning');
        return;
    }
    
    try {
        if (window.pywebview) {
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
        if (window.pywebview) {
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

function bindSettingsEvents() {
    const saveBtn = document.getElementById('saveSettingsBtn');
    if (saveBtn) {
        saveBtn.addEventListener('click', saveSettings);
    }
}

async function loadSettings() {
    try {
        if (window.pywebview) {
            const settings = await window.pywebview.api.get_settings();
            window.uapAPI.onSettingsLoaded(settings);
        }
    } catch (e) {
        console.error('加载设置失败:', e);
    }
}

function renderSettings() {
    const fields = [
        ['llmProvider', state.settings.llmProvider],
        ['llmModel', state.settings.llmModel],
        ['llmBaseUrl', state.settings.llmBaseUrl],
        ['defaultFrequency', state.settings.defaultFrequency],
        ['defaultHorizon', state.settings.defaultHorizon]
    ];
    
    fields.forEach(([id, value]) => {
        const el = document.getElementById(id);
        if (el) el.value = value;
    });
}

async function saveSettings() {
    const settings = {
        llm: {
            provider: document.getElementById('llmProvider')?.value || 'ollama',
            model: document.getElementById('llmModel')?.value || 'llama3.2',
            base_url: document.getElementById('llmBaseUrl')?.value || 'http://127.0.0.1:11434'
        },
        prediction_defaults: {
            default_frequency_sec: parseInt(document.getElementById('defaultFrequency')?.value || 3600),
            default_horizon_sec: parseInt(document.getElementById('defaultHorizon')?.value || 259200)
        }
    };
    
    console.log('[Settings] Saving:', settings);
    
    try {
        if (window.pywebview) {
            const result = await window.pywebview.api.update_config(settings);
            console.log('[Settings] Save result:', result);
            if (result.success) {
                state.settings = {
                    llmProvider: settings.llm.provider,
                    llmModel: settings.llm.model,
                    llmBaseUrl: settings.llm.base_url,
                    defaultFrequency: settings.prediction_defaults.default_frequency_sec,
                    defaultHorizon: settings.prediction_defaults.default_horizon_sec
                };
                showToast('设置已保存到本地', 'success');
            } else {
                showToast('保存失败: ' + (result.error || '未知错误'), 'error');
            }
        } else {
            state.settings = {
                llmProvider: settings.llm.provider,
                llmModel: settings.llm.model,
                llmBaseUrl: settings.llm.base_url,
                defaultFrequency: settings.prediction_defaults.default_frequency_sec,
                defaultHorizon: settings.prediction_defaults.default_horizon_sec
            };
            showToast('演示模式: 设置已保存', 'info');
        }
    } catch (e) {
        console.error('[Settings] Save failed:', e);
        showToast('保存设置失败: ' + e.message, 'error');
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
window.openProjectFolder = openProjectFolder;
window.deleteProject = deleteProject;
window.sendModelingMessage = sendModelingMessage;
window.startPrediction = startPrediction;
window.stopPrediction = stopPrediction;
