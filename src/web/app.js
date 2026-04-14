// UAP 前端应用

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

// 初始化卡片管理器
window.cardManager = new CardManagerUI();
window.cardManager.onCardResponse = (response) => {
    console.log('Card response:', response);
    if (response.card_type === 'model_confirm') {
        if (response.selected_option_id === 'confirm') {
            window.uapApp.showToast('success', '模型已确认', '系统模型已保存');
        }
    } else if (response.card_type === 'prediction_execution') {
        if (response.selected_option_id === 'execute') {
            window.uapApp.runPredictionNow();
        }
    }
};



    // 卡片相关方法
    showMethodSelectionCard() {
        if (!this.currentProject) {
            alert('请先选择一个项目');
            return;
        }
        window.cardManager.showMethodSelectionCard(this.currentProject);
    }
    
    showModelConfirmCard(variables, relations, constraints) {
        if (!this.currentProject) return;
        window.cardManager.showModelConfirmCard(
            this.currentProject, variables, relations, constraints
        );
    }
    
    showToast(type, title, content) {
        const icon = type === 'success' ? '✅' : type === 'error' ? '❌' : 'ℹ️';
        if (window.cardManager) {
            window.cardManager.showToast(icon, title, content);
        }
    }

// 启动应用
window.addEventListener('DOMContentLoaded', () => {
    window.uapApp = new UAPApp();
});
