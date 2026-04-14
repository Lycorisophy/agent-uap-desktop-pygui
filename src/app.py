"""
UAP - 复杂系统未来势态量化预测统一智能体
主入口文件
"""

import os
import sys
import webview
import threading
import argparse
from pathlib import Path

# 添加src目录到路径
src_dir = Path(__file__).parent / "src"
sys.path.insert(0, str(src_dir))

from uap.config import load_config
from uap.api import UAPApi


class UAPApplication:
    """UAP 桌面应用主类"""

    def __init__(self, debug: bool = False):
        self.debug = debug
        self.config = load_config()
        self.api: UAPApi = None
        self.window: webview.Window = None

    def start(self):
        """启动应用"""
        # 初始化API
        self.api = UAPApi(self.config)

        # 启动调度器
        self.api.scheduler.start()

        # 创建窗口
        self._create_window()

        # 启动PyWebView
        webview.start(self._on_start, debug=self.debug)

    def _create_window(self):
        """创建主窗口"""
        # 确定前端文件路径
        frontend_dir = Path(__file__).parent / "web"

        # 使用本地HTML作为前端
        index_path = frontend_dir / "index.html"

        # 如果前端文件不存在，创建默认页面
        if not index_path.exists():
            self._create_default_frontend(frontend_dir)

        # 创建窗口
        self.window = webview.create_window(
            title="UAP - 复杂系统预测智能体",
            url=str(index_path.absolute()),
            width=1280,
            height=800,
            min_size=(800, 600),
            resizable=True,
            js_api=self.api
        )

    def _create_default_frontend(self, frontend_dir: Path):
        """创建默认前端页面"""
        frontend_dir.mkdir(parents=True, exist_ok=True)

        # 创建 index.html
        html_content = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UAP - 复杂系统预测智能体</title>
    <link rel="stylesheet" href="style.css">
</head>
<body>
    <div class="app-container">
        <!-- 侧边栏 -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <h1>UAP</h1>
                <p class="subtitle">复杂系统预测</p>
            </div>
            <nav class="sidebar-nav">
                <button class="nav-item active" data-view="projects">
                    <span class="icon">📁</span>
                    <span>项目列表</span>
                </button>
                <button class="nav-item" data-view="modeling">
                    <span class="icon">🔧</span>
                    <span>系统建模</span>
                </button>
                <button class="nav-item" data-view="prediction">
                    <span class="icon">📊</span>
                    <span>预测分析</span>
                </button>
                <button class="nav-item" data-view="settings">
                    <span class="icon">⚙️</span>
                    <span>设置</span>
                </button>
            </nav>
            <div class="sidebar-footer">
                <div class="scheduler-status" id="schedulerStatus">
                    <span class="status-indicator"></span>
                    <span>调度器运行中</span>
                </div>
            </div>
        </aside>

        <!-- 主内容区 -->
        <main class="main-content">
            <!-- 项目列表视图 -->
            <section id="projectsView" class="view active">
                <div class="view-header">
                    <h2>项目列表</h2>
                    <button class="btn btn-primary" id="createProjectBtn">+ 新建项目</button>
                </div>
                <div class="project-grid" id="projectGrid">
                    <!-- 项目卡片将通过JS动态加载 -->
                </div>
            </section>

            <!-- 系统建模视图 -->
            <section id="modelingView" class="view">
                <div class="view-header">
                    <h2>系统建模</h2>
                    <div class="project-selector">
                        <select id="modelingProjectSelect">
                            <option value="">选择项目...</option>
                        </select>
                    </div>
                </div>
                <div class="modeling-container">
                    <div class="modeling-chat">
                        <div class="chat-messages" id="chatMessages">
                            <div class="message system">
                                <div class="message-content">
                                    欢迎使用系统建模工具。您可以通过对话方式描述您的复杂系统，我会帮您提取系统模型。
                                </div>
                            </div>
                        </div>
                        <div class="chat-input">
                            <textarea id="chatInput" placeholder="描述您的系统..." rows="3"></textarea>
                            <button class="btn btn-primary" id="sendMessageBtn">发送</button>
                        </div>
                    </div>
                    <div class="model-preview">
                        <h3>系统模型预览</h3>
                        <div class="model-content" id="modelPreview">
                            <p class="placeholder">尚未提取模型</p>
                        </div>
                    </div>
                </div>
            </section>

            <!-- 预测分析视图 -->
            <section id="predictionView" class="view">
                <div class="view-header">
                    <h2>预测分析</h2>
                    <div class="project-selector">
                        <select id="predictionProjectSelect">
                            <option value="">选择项目...</option>
                        </select>
                    </div>
                </div>
                <div class="prediction-container">
                    <div class="prediction-config">
                        <h3>预测配置</h3>
                        <div class="config-form">
                            <div class="form-group">
                                <label>预测频率</label>
                                <select id="predictionFrequency">
                                    <option value="3600">每小时</option>
                                    <option value="7200">每2小时</option>
                                    <option value="21600">每6小时</option>
                                    <option value="43200">每12小时</option>
                                    <option value="86400">每天</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>预测时长</label>
                                <select id="predictionHorizon">
                                    <option value="86400">1天</option>
                                    <option value="259200">3天</option>
                                    <option value="604800">7天</option>
                                    <option value="2592000">30天</option>
                                </select>
                            </div>
                            <div class="form-actions">
                                <button class="btn btn-primary" id="runNowBtn">立即预测</button>
                                <button class="btn btn-success" id="startSchedulerBtn">启动定时</button>
                                <button class="btn btn-secondary" id="stopSchedulerBtn">停止定时</button>
                            </div>
                        </div>
                        <div class="task-status" id="taskStatus">
                            <p>任务状态: 未启动</p>
                        </div>
                    </div>
                    <div class="prediction-results">
                        <h3>预测结果</h3>
                        <div class="results-chart" id="resultsChart">
                            <div class="chart-placeholder">
                                <p>暂无预测数据</p>
                            </div>
                        </div>
                        <div class="results-list" id="resultsList">
                            <!-- 预测结果列表 -->
                        </div>
                    </div>
                </div>
            </section>

            <!-- 设置视图 -->
            <section id="settingsView" class="view">
                <div class="view-header">
                    <h2>设置</h2>
                </div>
                <div class="settings-container">
                    <div class="settings-section">
                        <h3>LLM 配置</h3>
                        <div class="settings-form">
                            <div class="form-group">
                                <label>提供商</label>
                                <select id="llmProvider">
                                    <option value="ollama">Ollama</option>
                                    <option value="openai">OpenAI</option>
                                    <option value="deepseek">DeepSeek</option>
                                </select>
                            </div>
                            <div class="form-group">
                                <label>模型名称</label>
                                <input type="text" id="llmModel" placeholder="e.g., llama3.2">
                            </div>
                            <div class="form-group">
                                <label>API Base URL</label>
                                <input type="text" id="llmBaseUrl" placeholder="http://localhost:11434">
                            </div>
                        </div>
                    </div>
                    <div class="settings-section">
                        <h3>预测参数</h3>
                        <div class="settings-form">
                            <div class="form-group">
                                <label>默认预测频率（秒）</label>
                                <input type="number" id="defaultFrequency" value="3600">
                            </div>
                            <div class="form-group">
                                <label>默认预测时长（秒）</label>
                                <input type="number" id="defaultHorizon" value="259200">
                            </div>
                        </div>
                    </div>
                    <div class="settings-actions">
                        <button class="btn btn-primary" id="saveSettingsBtn">保存设置</button>
                    </div>
                </div>
            </section>
        </main>
    </div>

    <!-- 创建项目模态框 -->
    <div class="modal" id="createProjectModal">
        <div class="modal-content">
            <div class="modal-header">
                <h3>新建项目</h3>
                <button class="modal-close" id="closeProjectModal">&times;</button>
            </div>
            <div class="modal-body">
                <div class="form-group">
                    <label>项目名称</label>
                    <input type="text" id="projectName" placeholder="输入项目名称">
                </div>
                <div class="form-group">
                    <label>项目描述</label>
                    <textarea id="projectDescription" placeholder="输入项目描述（可选）" rows="3"></textarea>
                </div>
            </div>
            <div class="modal-footer">
                <button class="btn btn-secondary" id="cancelProjectBtn">取消</button>
                <button class="btn btn-primary" id="confirmCreateBtn">创建</button>
</div>
        </div>
    </div>

    <script src="app.js"></script>
</body>
</html>
'''

        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(html_content)

        # 创建 CSS
        css_content = '''/* UAP 样式表 */

:root {
    --primary-color: #4f46e5;
    --primary-hover: #4338ca;
    --secondary-color: #6b7280;
    --success-color: #10b981;
    --danger-color: #ef4444;
    --warning-color: #f59e0b;
    --bg-color: #f9fafb;
    --sidebar-bg: #1f2937;
    --sidebar-text: #f3f4f6;
    --text-color: #1f2937;
    --border-color: #e5e7eb;
    --card-bg: #ffffff;
}

* {
    margin: 0;
    padding: 0;
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    background: var(--bg-color);
    color: var(--text-color);
    line-height: 1.6;
}

.app-container {
    display: flex;
    height: 100vh;
}

/* 侧边栏 */
.sidebar {
    width: 240px;
    background: var(--sidebar-bg);
    color: var(--sidebar-text);
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}

.sidebar-header {
    padding: 24px 20px;
    border-bottom: 1px solid rgba(255,255,255,0.1);
}

.sidebar-header h1 {
    font-size: 24px;
    font-weight: 700;
    margin-bottom: 4px;
}

.sidebar-header .subtitle {
    font-size: 12px;
    opacity: 0.7;
}

.sidebar-nav {
    flex: 1;
    padding: 16px 12px;
}

.nav-item {
    display: flex;
    align-items: center;
    gap: 12px;
    width: 100%;
    padding: 12px 16px;
    margin-bottom: 4px;
    background: transparent;
    border: none;
    border-radius: 8px;
    color: var(--sidebar-text);
    font-size: 14px;
    cursor: pointer;
    transition: all 0.2s;
}

.nav-item:hover {
    background: rgba(255,255,255,0.1);
}

.nav-item.active {
    background: var(--primary-color);
}

.nav-item .icon {
    font-size: 18px;
}

.sidebar-footer {
    padding: 16px 20px;
    border-top: 1px solid rgba(255,255,255,0.1);
}

.scheduler-status {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 12px;
    opacity: 0.8;
}

.status-indicator {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--success-color);
}

.status-indicator.stopped {
    background: var(--danger-color);
}

/* 主内容区 */
.main-content {
    flex: 1;
    overflow: auto;
    padding: 24px 32px;
}

.view {
    display: none;
}

.view.active {
    display: block;
}

.view-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 24px;
}

.view-header h2 {
    font-size: 24px;
    font-weight: 600;
}

/* 项目网格 */
.project-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
    gap: 20px;
}

.project-card {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    transition: all 0.2s;
    cursor: pointer;
}

.project-card:hover {
    box-shadow: 0 4px 12px rgba(0,0,0,0.15);
    transform: translateY(-2px);
}

.project-card h3 {
    font-size: 18px;
    margin-bottom: 8px;
}

.project-card p {
    font-size: 14px;
    color: var(--secondary-color);
    margin-bottom: 16px;
}

.project-meta {
    display: flex;
    justify-content: space-between;
    font-size: 12px;
    color: var(--secondary-color);
}

.project-status {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 4px;
    font-size: 12px;
}

.project-status.idle { background: #e5e7eb; }
.project-status.modeling { background: #dbeafe; color: #1d4ed8; }
.project-status.running { background: #d1fae5; color: #047857; }
.project-status.error { background: #fee2e2; color: #b91c1c; }

/* 按钮 */
.btn {
    padding: 8px 16px;
    border-radius: 6px;
    border: none;
    font-size: 14px;
    cursor: pointer;
    transition: all 0.2s;
}

.btn-primary {
    background: var(--primary-color);
    color: white;
}

.btn-primary:hover {
    background: var(--primary-hover);
}

.btn-secondary {
    background: var(--secondary-color);
    color: white;
}

.btn-success {
    background: var(--success-color);
    color: white;
}

.btn-danger {
    background: var(--danger-color);
    color: white;
}

/* 表单 */
.form-group {
    margin-bottom: 16px;
}

.form-group label {
    display: block;
    margin-bottom: 6px;
    font-size: 14px;
    font-weight: 500;
}

.form-group input,
.form-group select,
.form-group textarea {
    width: 100%;
    padding: 8px 12px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    font-size: 14px;
}

.form-group input:focus,
.form-group select:focus,
.form-group textarea:focus {
    outline: none;
    border-color: var(--primary-color);
}

/* 模态框 */
.modal {
    display: none;
    position: fixed;
    top: 0;
    left: 0;
    width: 100%;
    height: 100%;
    background: rgba(0,0,0,0.5);
    z-index: 1000;
    align-items: center;
    justify-content: center;
}

.modal.active {
    display: flex;
}

.modal-content {
    background: white;
    border-radius: 12px;
    width: 480px;
    max-width: 90%;
}

.modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 16px 20px;
    border-bottom: 1px solid var(--border-color);
}

.modal-close {
    background: none;
    border: none;
    font-size: 24px;
    cursor: pointer;
    color: var(--secondary-color);
}

.modal-body {
    padding: 20px;
}

.modal-footer {
    display: flex;
    justify-content: flex-end;
    gap: 12px;
    padding: 16px 20px;
    border-top: 1px solid var(--border-color);
}

/* 建模视图 */
.modeling-container {
    display: grid;
    grid-template-columns: 1fr 400px;
    gap: 24px;
    height: calc(100vh - 200px);
}

.modeling-chat {
    display: flex;
    flex-direction: column;
    background: var(--card-bg);
    border-radius: 12px;
    overflow: hidden;
}

.chat-messages {
    flex: 1;
    overflow-y: auto;
    padding: 16px;
}

.message {
    margin-bottom: 16px;
}

.message.user {
    text-align: right;
}

.message-content {
    display: inline-block;
    padding: 12px 16px;
    border-radius: 12px;
    max-width: 80%;
    background: #f3f4f6;
}

.message.user .message-content {
    background: var(--primary-color);
    color: white;
}

.chat-input {
    display: flex;
    gap: 12px;
    padding: 16px;
    border-top: 1px solid var(--border-color);
}

.chat-input textarea {
    flex: 1;
    resize: none;
}

.model-preview {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
    overflow: auto;
}

.model-preview h3 {
    margin-bottom: 16px;
}

.model-content {
    font-size: 14px;
}

.model-content .placeholder {
    color: var(--secondary-color);
    text-align: center;
    padding: 40px;
}

/* 预测视图 */
.prediction-container {
    display: grid;
    grid-template-columns: 320px 1fr;
    gap: 24px;
}

.prediction-config {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
}

.prediction-config h3 {
    margin-bottom: 16px;
}

.config-form .form-actions {
    display: flex;
    gap: 8px;
    flex-wrap: wrap;
    margin-top: 16px;
}

.task-status {
    margin-top: 20px;
    padding: 12px;
    background: #f3f4f6;
    border-radius: 8px;
    font-size: 14px;
}

.prediction-results {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
}

.prediction-results h3 {
    margin-bottom: 16px;
}

.results-chart {
    height: 300px;
    background: #f9fafb;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    margin-bottom: 16px;
}

.chart-placeholder {
    color: var(--secondary-color);
}

/* 设置视图 */
.settings-container {
    max-width: 600px;
}

.settings-section {
    background: var(--card-bg);
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 20px;
}

.settings-section h3 {
    margin-bottom: 16px;
    padding-bottom: 12px;
    border-bottom: 1px solid var(--border-color);
}

.settings-actions {
    display: flex;
    justify-content: flex-end;
}

/* 项目选择器 */
.project-selector select {
    padding: 8px 12px;
    border: 1px solid var(--border-color);
    border-radius: 6px;
    font-size: 14px;
    min-width: 200px;
}
'''

        with open(frontend_dir / "style.css", 'w', encoding='utf-8') as f:
            f.write(css_content)

        # 创建 JavaScript
        js_content = '''// UAP 前端应用

class UAPApp {
    constructor() {
        this.currentProject = null;
        this.projects = [];
        this.init();
    }

    async init() {
        this.bindEvents();
        await this.loadProjects();
        this.updateSchedulerStatus();
    }

    bindEvents() {
        // 导航切换
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', () => this.switchView(item.dataset.view));
        });

        // 创建项目
        document.getElementById('createProjectBtn').addEventListener('click', () => this.showCreateModal());
        document.getElementById('closeProjectModal').addEventListener('click', () => this.hideCreateModal());
        document.getElementById('cancelProjectBtn').addEventListener('click', () => this.hideCreateModal());
        document.getElementById('confirmCreateBtn').addEventListener('click', () => this.createProject());

        // 建模视图
        document.getElementById('sendMessageBtn').addEventListener('click', () => this.sendMessage());
        document.getElementById('chatInput').addEventListener('keypress', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                this.sendMessage();
            }
        });

        // 预测视图
        document.getElementById('runNowBtn').addEventListener('click', () => this.runPredictionNow());
        document.getElementById('startSchedulerBtn').addEventListener('click', () => this.startScheduler());
        document.getElementById('stopSchedulerBtn').addEventListener('click', () => this.stopScheduler());

        // 项目选择器变化
        document.getElementById('modelingProjectSelect').addEventListener('change', (e) => {
            this.currentProject = e.target.value;
            this.loadModelPreview();
        });
        document.getElementById('predictionProjectSelect').addEventListener('change', (e) => {
            this.currentProject = e.target.value;
            this.loadPredictionConfig();
        });

        // 设置保存
        document.getElementById('saveSettingsBtn').addEventListener('click', () => this.saveSettings());

        // 定时更新调度器状态
        setInterval(() => this.updateSchedulerStatus(), 5000);
    }

    switchView(viewName) {
        // 切换导航激活状态
        document.querySelectorAll('.nav-item').forEach(item => {
            item.classList.toggle('active', item.dataset.view === viewName);
        });

        // 切换视图显示
        document.querySelectorAll('.view').forEach(view => {
            view.classList.toggle('active', view.id === viewName + 'View');
        });

        // 视图特定初始化
        if (viewName === 'prediction') {
            this.loadPredictionConfig();
        }
    }

    // ==================== 项目管理 ====================

    async loadProjects() {
        try {
            const result = await pywebview.api.list_projects();
            this.projects = result.items || [];
            this.renderProjects();
            this.updateProjectSelectors();
        } catch (e) {
            console.error('Failed to load projects:', e);
        }
    }

    renderProjects() {
        const grid = document.getElementById('projectGrid');
        grid.innerHTML = '';

        if (this.projects.length === 0) {
            grid.innerHTML = '<p class="placeholder">暂无项目，点击"新建项目"创建</p>';
            return;
        }

        this.projects.forEach(project => {
            const card = document.createElement('div');
            card.className = 'project-card';
            card.innerHTML = `
                <h3>${this.escapeHtml(project.name)}</h3>
                <p>${this.escapeHtml(project.description || '无描述')}</p>
                <div class="project-meta">
                    <span class="project-status ${project.status}">${this.getStatusText(project.status)}</span>
                    <span>${this.formatDate(project.created_at)}</span>
                </div>
            `;
            card.addEventListener('click', () => this.openProject(project.id));
            grid.appendChild(card);
        });
    }

    updateProjectSelectors() {
        const selectors = [
            document.getElementById('modelingProjectSelect'),
            document.getElementById('predictionProjectSelect')
        ];

        selectors.forEach(select => {
            const currentValue = select.value;
            select.innerHTML = '<option value="">选择项目...</option>';
            this.projects.forEach(p => {
                const option = document.createElement('option');
                option.value = p.id;
                option.textContent = p.name;
                select.appendChild(option);
            });
            if (currentValue) select.value = currentValue;
        });
    }

    showCreateModal() {
        document.getElementById('createProjectModal').classList.add('active');
        document.getElementById('projectName').focus();
    }

    hideCreateModal() {
        document.getElementById('createProjectModal').classList.remove('active');
        document.getElementById('projectName').value = '';
        document.getElementById('projectDescription').value = '';
    }

    async createProject() {
        const name = document.getElementById('projectName').value.trim();
        const description = document.getElementById('projectDescription').value.trim();

        if (!name) {
            alert('请输入项目名称');
            return;
        }

        try {
            await pywebview.api.create_project(name, description);
            this.hideCreateModal();
            await this.loadProjects();
        } catch (e) {
            console.error('Failed to create project:', e);
            alert('创建项目失败');
        }
    }

    async openProject(projectId) {
        this.currentProject = projectId;
        this.switchView('modeling');
        document.getElementById('modelingProjectSelect').value = projectId;
        await this.loadModelPreview();
    }

    // ==================== 系统建模 ====================

    async sendMessage() {
        const input = document.getElementById('chatInput');
        const message = input.value.trim();

        if (!message || !this.currentProject) {
            if (!this.currentProject) {
                alert('请先选择一个项目');
            }
            return;
        }

        // 添加用户消息
        this.addMessage('user', message);
        input.value = '';

        // 调用API提取模型
        try {
            const result = await pywebview.api.extract_model_from_conversation(
                this.currentProject,
                [],
                message
            );

            if (result.success) {
                this.addMessage('system', '系统模型已更新');
                this.loadModelPreview();
            } else {
                this.addMessage('system', result.error || '模型提取失败');
            }
        } catch (e) {
            console.error('Failed to extract model:', e);
            this.addMessage('system', '模型提取失败');
        }
    }

    addMessage(type, content) {
        const container = document.getElementById('chatMessages');
        const message = document.createElement('div');
        message.className = `message ${type}`;
        message.innerHTML = `<div class="message-content">${this.escapeHtml(content)}</div>`;
        container.appendChild(message);
        container.scrollTop = container.scrollHeight;
    }

    async loadModelPreview() {
        const preview = document.getElementById('modelPreview');

        if (!this.currentProject) {
            preview.innerHTML = '<p class="placeholder">请选择一个项目</p>';
            return;
        }

        try {
            const model = await pywebview.api.get_model(this.currentProject);
            if (model) {
                preview.innerHTML = this.renderModelPreview(model);
            } else {
                preview.innerHTML = '<p class="placeholder">尚未提取模型，请通过对话描述您的系统</p>';
            }
        } catch (e) {
            console.error('Failed to load model:', e);
        }
    }

    renderModelPreview(model) {
        let html = '<div class="model-section">';
        html += '<h4>变量</h4><ul>';
        (model.variables || []).forEach(v => {
            html += `<li>${this.escapeHtml(v.name)}: ${this.escapeHtml(v.type)}</li>`;
        });
        html += '</ul></div>';

        html += '<div class="model-section"><h4>关系</h4><ul>';
        (model.relations || []).forEach(r => {
            html += `<li>${this.escapeHtml(r.from_var)} → ${this.escapeHtml(r.to_var)} (${this.escapeHtml(r.type)})</li>`;
        });
        html += '</ul></div>';

        html += '<div class="model-section"><h4>约束</h4><ul>';
        (model.constraints || []).forEach(c => {
            html += `<li>${this.escapeHtml(c.expression)}</li>`;
        });
        html += '</ul></div>';

        return html;
    }

    // ==================== 预测分析 ====================

    async loadPredictionConfig() {
        if (!this.currentProject) return;

        try {
            const config = await pywebview.api.get_prediction_config(this.currentProject);
            if (config) {
                document.getElementById('predictionFrequency').value = config.frequency_seconds || 3600;
                document.getElementById('predictionHorizon').value = config.horizon_seconds || 259200;
            }

            // 加载任务状态
            const tasks = await pywebview.api.get_project_tasks(this.currentProject);
            this.updateTaskStatus(tasks);

            // 加载预测结果
            await this.loadPredictionResults();
        } catch (e) {
            console.error('Failed to load prediction config:', e);
        }
    }

    updateTaskStatus(tasks) {
        const status = document.getElementById('taskStatus');
        const activeTask = tasks.find(t => t.status === 'pending' || t.status === 'running');

        if (activeTask) {
            status.innerHTML = `<p>任务状态: 运行中 (ID: ${activeTask.id.substring(0, 8)}...)</p>`;
        } else {
            status.innerHTML = '<p>任务状态: 未启动</p>';
        }
    }

    async loadPredictionResults() {
        if (!this.currentProject) return;

        try {
            const result = await pywebview.api.get_prediction_results(this.currentProject);
            const list = document.getElementById('resultsList');

            if (result.items && result.items.length > 0) {
                list.innerHTML = result.items.slice(0, 10).map(item => `
                    <div class="result-item">
                        <div class="result-header">
                            <span>${this.formatDate(item.predicted_at)}</span>
                            <span class="system-state ${item.system_state}">${item.system_state}</span>
                        </div>
                        <div class="result-details">
                            熵值: ${item.entropy_value?.toFixed(4) || 'N/A'}
                        </div>
                    </div>
                `).join('');
            } else {
                list.innerHTML = '<p>暂无预测结果</p>';
            }
        } catch (e) {
            console.error('Failed to load results:', e);
        }
    }

    async runPredictionNow() {
        if (!this.currentProject) {
            alert('请先选择一个项目');
            return;
        }

        try {
            const result = await pywebview.api.run_prediction_now(this.currentProject);
            if (result.success) {
                alert('预测完成');
                await this.loadPredictionResults();
            } else {
                alert('预测失败: ' + result.error);
            }
        } catch (e) {
            console.error('Failed to run prediction:', e);
            alert('预测执行失败');
        }
    }

    async startScheduler() {
        if (!this.currentProject) {
            alert('请先选择一个项目');
            return;
        }

        const frequency = parseInt(document.getElementById('predictionFrequency').value);

        try {
            const result = await pywebview.api.create_prediction_task(
                this.currentProject,
                'interval',
                frequency
            );

            if (result.success) {
                alert('定时预测已启动');
                await this.loadPredictionConfig();
            } else {
                alert('启动失败: ' + result.error);
            }
        } catch (e) {
            console.error('Failed to start scheduler:', e);
        }
    }

    async stopScheduler() {
        if (!this.currentProject) return;

        try {
            const tasks = await pywebview.api.get_project_tasks(this.currentProject);
            for (const task of tasks) {
                if (task.status === 'pending' || task.status === 'running') {
                    await pywebview.api.delete_prediction_task(task.id);
                }
            }
            alert('定时预测已停止');
            await this.loadPredictionConfig();
        } catch (e) {
            console.error('Failed to stop scheduler:', e);
        }
    }

    // ==================== 设置 ====================

    async saveSettings() {
        alert('设置已保存');
    }

    // ==================== 工具方法 ====================

    updateSchedulerStatus() {
        pywebview.api.get_scheduler_status().then(status => {
            const indicator = document.querySelector('.status-indicator');
            if (indicator) {
                indicator.classList.toggle('stopped', !status.running);
            }
        });
    }

    getStatusText(status) {
        const map = {
            idle: '空闲',
            modeling: '建模中',
            running: '运行中',
            error: '错误'
        };
        return map[status] || status;
    }

    formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.toLocaleString('zh-CN');
    }

    escapeHtml(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
}

// 启动应用
window.addEventListener('DOMContentLoaded', () => {
    window.uapApp = new UAPApp();
});
'''

        with open(frontend_dir / "app.js", 'w', encoding='utf-8') as f:
            f.write(js_content)

    def _on_start(self):
        """窗口启动后的回调"""
        print("UAP Application started")

    def stop(self):
        """停止应用"""
        if self.api:
            self.api.scheduler.stop()


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='UAP - 复杂系统预测智能体')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    args = parser.parse_args()

    app = UAPApplication(debug=args.debug)
    app.start()


if __name__ == '__main__':
    main()
