/**
 * UAP 卡片确认系统前端模块
 * 
 * 管理卡片的显示、交互和响应提交流程
 */

class CardManagerUI {
    constructor(api) {
        this.api = api;
        this.currentCard = null;
        this.selectedOption = null;
        this.onCardResponse = null;  // 回调函数
        this.init();
    }

    init() {
        // 创建卡片容器
        this.createCardContainer();
        
        // 定期检查待处理卡片
        this.startPolling();
    }

    createCardContainer() {
        // 卡片模态框
        this.cardOverlay = document.createElement('div');
        this.cardOverlay.className = 'card-overlay';
        this.cardOverlay.id = 'cardOverlay';
        this.cardOverlay.innerHTML = `
            <div class="confirmation-card" id="confirmationCard">
                <div class="card-header">
                    <h3><span class="card-icon" id="cardIcon">📋</span> <span id="cardTitle">确认</span></h3>
                    <button class="card-close" id="cardClose">&times;</button>
                </div>
                <div class="card-body">
                    <div class="card-content" id="cardContent"></div>
                    <div class="card-options" id="cardOptions"></div>
                </div>
                <div class="card-footer">
                    <button class="btn btn-secondary" id="cardCancel">取消</button>
                    <button class="btn btn-primary" id="cardConfirm" disabled>确认</button>
                </div>
            </div>
        `;
        document.body.appendChild(this.cardOverlay);

        // 绑定事件
        document.getElementById('cardClose').addEventListener('click', () => this.hideCard());
        document.getElementById('cardCancel').addEventListener('click', () => this.hideCard());
        document.getElementById('cardConfirm').addEventListener('click', () => this.submitResponse());

        // 点击遮罩关闭
        this.cardOverlay.addEventListener('click', (e) => {
            if (e.target === this.cardOverlay) {
                this.hideCard();
            }
        });
    }

    startPolling() {
        // 每2秒检查待处理卡片
        this.pollInterval = setInterval(() => {
            this.checkPendingCards();
        }, 2000);
    }

    async checkPendingCards() {
        if (!window.uapApp || !window.uapApp.currentProject) return;
        
        try {
            const card = await pywebview.api.get_pending_card(window.uapApp.currentProject);
            if (card && !this.currentCard) {
                this.showCard(card);
            }
        } catch (e) {
            console.error('Failed to check pending cards:', e);
        }
    }

    showCard(cardData) {
        this.currentCard = cardData;
        this.selectedOption = null;

        // 设置内容
        document.getElementById('cardIcon').textContent = cardData.icon || '📋';
        document.getElementById('cardTitle').textContent = cardData.title;
        
        // 渲染内容（Markdown + 代码高亮 / Mermaid，见 uap_markdown.js）
        const contentEl = document.getElementById('cardContent');
        contentEl.className = 'card-content md-body';
        if (typeof window.UAPMarkdown !== 'undefined' && window.UAPMarkdown.renderMarkdownToSafeHtml) {
            contentEl.innerHTML = window.UAPMarkdown.renderMarkdownToSafeHtml(cardData.content || '');
            window.UAPMarkdown.finalizeRichContent(contentEl).catch(() => {});
        } else {
            contentEl.innerHTML = this.renderMarkdown(cardData.content);
        }

        // 渲染选项
        const optionsEl = document.getElementById('cardOptions');
        optionsEl.innerHTML = '';
        
        cardData.options.forEach(option => {
            const optionEl = document.createElement('div');
            optionEl.className = 'card-option';
            optionEl.dataset.optionId = option.id;
            
            const isRadio = cardData.options.length > 2;
            const inputType = isRadio ? 'radio' : 'radio';
            
            optionEl.innerHTML = `
                <input type="${inputType}" name="cardOption" value="${option.id}" id="opt_${option.id}">
                <label for="opt_${option.id}" class="card-option-content">
                    <div class="card-option-label">${option.label}</div>
                    ${option.description ? `<div class="card-option-desc">${option.description}</div>` : ''}
                </label>
            `;
            
            optionEl.addEventListener('click', () => this.selectOption(option.id));
            optionsEl.appendChild(optionEl);
        });

        // 设置优先级样式
        const card = document.getElementById('confirmationCard');
        card.className = 'confirmation-card';
        if (cardData.priority === 'high') {
            card.classList.add('card-priority-high');
        } else if (cardData.priority === 'critical') {
            card.classList.add('card-priority-critical');
        }

        // 设置默认选项
        if (cardData.default_option_id) {
            this.selectOption(cardData.default_option_id);
            const radio = document.getElementById(`opt_${cardData.default_option_id}`);
            if (radio) radio.checked = true;
        }

        // 显示
        this.cardOverlay.classList.add('active');
    }

    hideCard() {
        this.cardOverlay.classList.remove('active');
        this.currentCard = null;
        this.selectedOption = null;
    }

    selectOption(optionId) {
        this.selectedOption = optionId;
        
        // 更新UI
        document.querySelectorAll('.card-option').forEach(el => {
            el.classList.toggle('selected', el.dataset.optionId === optionId);
            const radio = el.querySelector('input[type="radio"]');
            if (radio) radio.checked = el.dataset.optionId === optionId;
        });

        // 启用确认按钮
        document.getElementById('cardConfirm').disabled = false;
    }

    async submitResponse() {
        if (!this.currentCard || !this.selectedOption) return;

        try {
            const result = await pywebview.api.submit_card_response(
                this.currentCard.card_id,
                this.selectedOption
            );

            if (result.success) {
                // 触发回调
                if (this.onCardResponse) {
                    this.onCardResponse({
                        card_id: this.currentCard.card_id,
                        selected_option_id: this.selectedOption,
                        card_type: this.currentCard.card_type
                    });
                }
            }

            this.hideCard();
        } catch (e) {
            console.error('Failed to submit card response:', e);
            alert('提交失败，请重试');
        }
    }

    renderMarkdown(text) {
        // 简单的Markdown渲染
        if (!text) return '';
        
        return text
            .replace(/^### (.*$)/gim, '<h4>$1</h4>')
            .replace(/^## (.*$)/gim, '<h3>$1</h3>')
            .replace(/^# (.*$)/gim, '<h2>$1</h2>')
            .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
            .replace(/\*(.*?)\*/g, '<em>$1</em>')
            .replace(/`([^`]+)`/g, '<code>$1</code>')
            .replace(/^- (.*$)/gim, '<li>$1</li>')
            .replace(/(<li>.*<\/li>)/s, '<ul>$1</ul>')
            .replace(/\n/g, '<br>');
    }

    // 显示预测方法选择卡片
    async showMethodSelectionCard(projectId) {
        try {
            const result = await pywebview.api.create_prediction_method_card(projectId);
            if (result.success && result.card) {
                this.showCard(result.card);
            }
        } catch (e) {
            console.error('Failed to show method selection card:', e);
        }
    }

    // 显示预测执行确认卡片
    async showPredictionConfirmCard(projectId, methodName, horizon, frequency) {
        try {
            const result = await pywebview.api.create_prediction_execution_card(
                projectId, methodName, horizon, frequency
            );
if (result.success && result.card) {
                this.showCard(result.card);
            }
        } catch (e) {
            console.error('Failed to show prediction confirm card:', e);
        }
    }

    // 显示模型确认卡片
    async showModelConfirmCard(projectId, variables, relations, constraints) {
        try {
            const result = await pywebview.api.create_model_confirm_card(
                projectId, variables, relations, constraints
            );
            if (result.success && result.card) {
                this.showCard(result.card);
            }
        } catch (e) {
            console.error('Failed to show model confirm card:', e);
        }
    }

    // 显示toast提示
    showToast(icon, title, content) {
        const toast = document.createElement('div');
        toast.className = 'card-toast';
        toast.innerHTML = `
            <div class="toast-header">
                <span class="toast-icon">${icon}</span>
                <span class="toast-title">${title}</span>
            </div>
            <div class="toast-content">${content}</div>
        `;
        document.body.appendChild(toast);

        // 3秒后自动消失
        setTimeout(() => {
            toast.style.opacity = '0';
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }

    destroy() {
        if (this.pollInterval) {
            clearInterval(this.pollInterval);
        }
        if (this.cardOverlay) {
            this.cardOverlay.remove();
        }
    }
}

// 导出
window.CardManagerUI = CardManagerUI;
