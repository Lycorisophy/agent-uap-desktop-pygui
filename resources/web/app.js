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
        defaultHorizon: 259200
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
    try {
        if (window.pywebview) {
            const result = await window.pywebview.api.list_projects();
            state.projects = result.items || [];
            renderProjectGrid();
            // 同时更新项目选择器
            updateProjectSelects();
        }
    } catch (e) {
        console.error('Failed to load projects:', e);
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
        if (window.pywebview) {
            const project = await window.pywebview.api.get_project(projectId);
            if (project) {
                state.currentProject = project;
                window.uapAPI.onProjectLoaded(project);
                switchView('modeling');
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
        if (window.pywebview) {
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
        if (window.pywebview) {
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
        if (window.pywebview) {
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
        if (window.pywebview) {
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
        if (window.pywebview) {
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
        if (window.pywebview) {
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
    const currentIndex = stageOrder.indexOf(stage);
    
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
        if (state.currentProject && window.pywebview) {
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
        if (window.pywebview) {
            const response = await window.pywebview.api.modeling_chat(
                state.currentProject.id,
                message
            );
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
                    content: `已收到：「${message}」（演示模式）\n\n我会像真实环境一样先澄清目标与时间范围，再逐步建模。请连接后端以使用完整智能体。`,
                    timestamp: new Date().toISOString()
                });
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
        showToast('该项目尚未完成建模或数据配置。请先在对话里用一句话开始目标，完成建模后再开定时预测。', 'warning');
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
    const prov = document.getElementById('llmProvider');
    if (prov) {
        prov.addEventListener('change', () => {
            applyLlmProviderPreset();
            updateLlmPresetHint();
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
    try {
        if (window.pywebview) {
            const config = await window.pywebview.api.get_config();
            if (config) {
                // 提取LLM配置
                const llm = config.llm || {};
                const predDefaults = config.prediction_defaults || {};
                state.settings = {
                    llmProvider: llm.provider || 'ollama',
                    llmModel: llm.model || 'llama3.2',
                    llmBaseUrl: llm.base_url || 'http://localhost:11434',
                    llmApiKeySet: !!llm.api_key_set,
                    llmPresets: config.llm_presets || {},
                    defaultFrequency: predDefaults.frequency_sec || 3600,
                    defaultHorizon: predDefaults.horizon_sec || 259200
                };
            }
            renderSettings();
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
    const settings = {
        llm,
        prediction_defaults: {
            frequency_sec: parseInt(document.getElementById('defaultFrequency')?.value || 3600),
            horizon_sec: parseInt(document.getElementById('defaultHorizon')?.value || 259200)
        }
    };

    try {
        if (window.pywebview) {
            await window.pywebview.api.update_config(settings);
        }
        state.settings = {
            llmProvider: settings.llm.provider,
            llmModel: settings.llm.model,
            llmBaseUrl: settings.llm.base_url,
            llmApiKeySet: state.settings.llmApiKeySet || !!apiKey,
            llmPresets: state.settings.llmPresets,
            defaultFrequency: settings.prediction_defaults.frequency_sec,
            defaultHorizon: settings.prediction_defaults.horizon_sec
        };
        showToast('设置已保存', 'success');
        await loadSettings();
    } catch (e) {
        console.error('保存设置失败:', e);
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
