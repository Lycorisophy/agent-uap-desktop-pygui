/**
 * UAP 可视化展示模块
 * 预测结果可视化、场景模板选择、历史回放
 */

// ==================== 可视化管理器 ====================
class VisualizationManager {
    constructor() {
        this.currentChart = null;
        this.chartContainer = document.getElementById('resultsChart');
    }

    // 渲染轨迹图
    renderTrajectory(svgData) {
        if (!this.chartContainer) return;
        this.chartContainer.innerHTML = svgData;
    }

    // 渲染空图表
    renderEmpty(message = '暂无数据') {
        if (!this.chartContainer) return;
        this.chartContainer.innerHTML = `
            <div class="chart-placeholder">
                <svg width="100" height="100" viewBox="0 0 100 100">
                    <rect width="100" height="100" fill="#f3f4f6"/>
                    <text x="50" y="55" text-anchor="middle" fill="#9ca3af" font-size="12">${escapeHtml(message)}</text>
                </svg>
            </div>
        `;
    }

    // 渲染分析结果
    renderAnalysisResults(results) {
        const container = document.getElementById('resultsList');
        if (!container) return;

        let html = '';

        // 熵值分析
        if (results.entropy) {
            html += this._renderEntropyCard(results.entropy);
        }

        // 湍流度
        if (results.turbulence) {
            html += this._renderTurbulenceCard(results.turbulence);
        }

        // 异常摘要
        if (results.anomalies) {
            html += this._renderAnomalySummary(results.anomalies);
        }

        container.innerHTML = html || '<p class="placeholder">暂无分析结果</p>';
    }

    _renderEntropyCard(entropy) {
        const level = entropy.predictability > 0.7 ? 'low' : entropy.predictability > 0.4 ? 'medium' : 'high';
        const color = level === 'low' ? '#10b981' : level === 'medium' ? '#f59e0b' : '#ef4444';
        const label = level === 'low' ? '可预测' : level === 'medium' ? '中等可预测' : '高不确定性';

        return `
            <div class="analysis-card entropy-card">
                <div class="card-header">
                    <span class="card-icon">📊</span>
                    <h4>熵值分析</h4>
                </div>
                <div class="card-body">
                    <div class="metric-row">
                        <span>可预测性:</span>
                        <span class="metric-value" style="color: ${color}">${label}</span>
                    </div>
                    <div class="metric-row">
                        <span>排列熵:</span>
                        <span class="metric-value">${entropy.permutation?.toFixed(3) || 'N/A'}</span>
                    </div>
                    <div class="metric-row">
                        <span>样本熵:</span>
                        <span class="metric-value">${entropy.sample?.toFixed(3) || 'N/A'}</span>
                    </div>
                </div>
                ${entropy.recommendations?.length ? `
                    <div class="card-footer">
                        <p class="hint">${escapeHtml(entropy.recommendations[0])}</p>
                    </div>
                ` : ''}
            </div>
        `;
    }

    _renderTurbulenceCard(turbulence) {
        const levelColors = {
            'calm': '#10b981',
            'moderate': '#f59e0b',
            'turbulent': '#ef4444',
            'chaotic': '#dc2626'
        };
        const color = levelColors[turbulence.level] || '#6b7280';

        return `
            <div class="analysis-card turbulence-card">
                <div class="card-header">
                    <span class="card-icon">🌀</span>
                    <h4>湍流度评估</h4>
                </div>
                <div class="card-body">
                    <div class="turbulence-meter">
                        <div class="meter-bar">
                            <div class="meter-fill" style="width: ${turbulence.score}%; background: ${color}"></div>
                        </div>
                        <span class="meter-label">${turbulence.score.toFixed(1)}</span>
                    </div>
                    <div class="level-badge" style="background: ${color}20; color: ${color}">
                        ${turbulence.level.toUpperCase()}
                    </div>
                </div>
                <div class="card-footer">
                    <p>${escapeHtml(turbulence.interpretation)}</p>
                </div>
            </div>
        `;
    }

    _renderAnomalySummary(anomalies) {
        const bySeverity = { critical: 0, high: 0, medium: 0, low: 0 };
        anomalies.forEach(a => {
            if (bySeverity[a.severity] !== undefined) bySeverity[a.severity]++;
        });

        return `
            <div class="analysis-card anomaly-card">
                <div class="card-header">
                    <span class="card-icon">⚠️</span>
                    <h4>异常检测</h4>
                </div>
                <div class="card-body">
                    <div class="severity-grid">
                        ${Object.entries(bySeverity).map(([sev, count]) => `
                            <div class="severity-item ${sev}">
                                <span class="count">${count}</span>
                                <span class="label">${sev}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            </div>
        `;
    }

    /**
     * 根据 PredictionResult（model_dump）构建轨迹与置信带 SVG。
     * @param {object} result
     * @returns {string|null} SVG 字符串，无数据时返回 null
     */
    buildPredictionTrajectorySvg(result) {
        const traj = result && Array.isArray(result.trajectory) ? result.trajectory : [];
        if (!traj.length) return null;

        const firstVals = traj[0].values;
        if (!firstVals || typeof firstVals !== 'object') return null;
        const varNames = Object.keys(firstVals);
        if (!varNames.length) return null;

        const W = 800;
        const H = 300;
        const padL = 56;
        const padR = 20;
        const padT = 28;
        const padB = 40;
        const innerW = W - padL - padR;
        const innerH = H - padT - padB;

        const xs = traj.map((p, i) => {
            const raw = p.timestamp;
            const t = raw ? Date.parse(raw) : NaN;
            return Number.isFinite(t) ? t : i;
        });
        const xMin = Math.min(...xs);
        const xMax = Math.max(...xs);
        const xSpan = xMax - xMin || 1;
        const xScale = (x) => padL + ((x - xMin) / xSpan) * innerW;

        const lowerList = result.confidence_lower || [];
        const upperList = result.confidence_upper || [];

        const palette = ['#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#9333ea', '#0891b2', '#ea580c'];

        const parts = [];
        const legend = varNames.map((name, idx) => {
            const c = palette[idx % palette.length];
            return `<span class="traj-legend-item"><span class="traj-swatch" style="background:${c}"></span>${escapeHtml(name)}</span>`;
        }).join('');

        varNames.forEach((name, vidx) => {
            const color = palette[vidx % palette.length];
            let vmin = Infinity;
            let vmax = -Infinity;
            traj.forEach((p, i) => {
                const v = p.values && p.values[name];
                if (typeof v === 'number' && Number.isFinite(v)) {
                    vmin = Math.min(vmin, v);
                    vmax = Math.max(vmax, v);
                }
                let lo = p.confidence_lower && typeof p.confidence_lower === 'object'
                    ? p.confidence_lower[name]
                    : (lowerList[i] && typeof lowerList[i] === 'object' ? lowerList[i][name] : undefined);
                let hi = p.confidence_upper && typeof p.confidence_upper === 'object'
                    ? p.confidence_upper[name]
                    : (upperList[i] && typeof upperList[i] === 'object' ? upperList[i][name] : undefined);
                if (typeof lo === 'number' && Number.isFinite(lo)) vmin = Math.min(vmin, lo);
                if (typeof hi === 'number' && Number.isFinite(hi)) vmax = Math.max(vmax, hi);
            });
            if (!Number.isFinite(vmin) || !Number.isFinite(vmax)) return;
            if (vmin === vmax) {
                vmin -= 1;
                vmax += 1;
            }
            const yScale = (val) => padT + innerH * (1 - (val - vmin) / (vmax - vmin));

            const upperPts = [];
            const lowerPts = [];
            traj.forEach((p, i) => {
                const x = xScale(xs[i]);
                let lo = p.confidence_lower && typeof p.confidence_lower === 'object'
                    ? p.confidence_lower[name]
                    : (lowerList[i] && typeof lowerList[i] === 'object' ? lowerList[i][name] : undefined);
                let hi = p.confidence_upper && typeof p.confidence_upper === 'object'
                    ? p.confidence_upper[name]
                    : (upperList[i] && typeof upperList[i] === 'object' ? upperList[i][name] : undefined);
                if (typeof lo !== 'number' || !Number.isFinite(lo)) lo = p.values[name];
                if (typeof hi !== 'number' || !Number.isFinite(hi)) hi = p.values[name];
                upperPts.push(`${x},${yScale(hi)}`);
                lowerPts.unshift(`${x},${yScale(lo)}`);
            });
            if (upperPts.length > 1) {
                const dBand = `M ${upperPts.join(' L ')} L ${lowerPts.join(' L ')} Z`;
                parts.push(`<path class="traj-band" d="${dBand}" fill="${color}" fill-opacity="0.12" stroke="none"/>`);
            }

            const linePts = traj.map((p, i) => {
                const x = xScale(xs[i]);
                const v = p.values[name];
                const y = yScale(typeof v === 'number' ? v : vmin);
                return `${x},${y}`;
            }).join(' ');
            parts.push(`<polyline class="traj-line" fill="none" stroke="${color}" stroke-width="2" points="${linePts}"/>`);
        });

        const anomalies = Array.isArray(result.anomalies) ? result.anomalies : [];
        anomalies.forEach((a) => {
            const ts = a.timestamp ? Date.parse(a.timestamp) : NaN;
            if (!Number.isFinite(ts)) return;
            let nearest = 0;
            let best = Infinity;
            xs.forEach((xv, i) => {
                const d = Math.abs(xv - ts);
                if (d < best) {
                    best = d;
                    nearest = i;
                }
            });
            const x = xScale(xs[nearest]);
            parts.push(
                `<line class="traj-anomaly-line" x1="${x}" y1="${padT}" x2="${x}" y2="${H - padB}" stroke="#f97316" stroke-width="1.5" stroke-dasharray="4 3"/>`,
            );
            parts.push(
                `<circle class="traj-anomaly-dot" cx="${x}" cy="${padT + 8}" r="4" fill="#f97316"/>`,
            );
        });

        const svg = `<svg class="prediction-traj-svg" viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">
            <rect class="traj-bg" x="0" y="0" width="${W}" height="${H}" fill="#f8fafc"/>
            <text class="traj-title" x="${padL}" y="18" font-size="12" fill="#475569">预测轨迹（各变量按自身取值范围映射到同一图区）</text>
            <foreignObject x="${padL}" y="4" width="${innerW}" height="22"><div xmlns="http://www.w3.org/1999/xhtml" class="traj-legend">${legend}</div></foreignObject>
            ${parts.join('\n')}
        </svg>`;
        return svg;
    }
}

// ==================== 场景模板选择器 ====================
class TemplateSelector {
    constructor(onSelect) {
        this.onSelect = onSelect;
        this.templates = [];
        this.container = null;
    }

    async load() {
        try {
            if (window.pywebview) {
                this.templates = await window.pywebview.api.get_templates();
            } else {
                // 演示数据
                this.templates = [
                    { id: 'power_grid_frequency', name: '电网频率', icon: '⚡', description: '电网频率稳定性监控' },
                    { id: 'supply_chain', name: '供应链', icon: '📦', description: '供应链风险管理' },
                    { id: 'financial_market', name: '金融市场', icon: '📈', description: '金融市场分析' },
                    { id: 'ecological_system', name: '生态系统', icon: '🌿', description: '生态系统建模' },
                    { id: 'climate_system', name: '气候系统', icon: '🌡️', description: '气候预测' },
                    { id: 'custom', name: '自定义', icon: '🔧', description: '从零开始定义' }
                ];
            }
            return this.templates;
        } catch (e) {
            console.error('Failed to load templates:', e);
            return [];
        }
    }

    render(containerId) {
        this.container = document.getElementById(containerId);
        if (!this.container) return;

        this.container.innerHTML = `
            <div class="template-grid">
                ${this.templates.map(t => `
                    <div class="template-card" data-id="${t.id}">
                        <span class="template-icon">${t.icon}</span>
                        <h4>${escapeHtml(t.name)}</h4>
                        <p>${escapeHtml(t.description || '')}</p>
                    </div>
                `).join('')}
            </div>
        `;

        // 绑定点击事件
        this.container.querySelectorAll('.template-card').forEach(card => {
            card.addEventListener('click', () => {
                const id = card.dataset.id;
                const template = this.templates.find(t => t.id === id);
                this.select(id);
                if (this.onSelect) this.onSelect(template);
            });
        });
    }

    select(templateId) {
        this.container?.querySelectorAll('.template-card').forEach(card => {
            card.classList.toggle('selected', card.dataset.id === templateId);
        });
    }
}

// ==================== 历史回放播放器 ====================
class HistoryPlayer {
    constructor() {
        this.isPlaying = false;
        this.currentIndex = 0;
        this.events = [];
    }

    async loadProject(projectId) {
        try {
            if (window.pywebview) {
                this.events = await window.pywebview.api.get_history_events(projectId);
            } else {
                this.events = [];
            }
            return this.events.length;
        } catch (e) {
            console.error('Failed to load history:', e);
            return 0;
        }
    }

    play() {
        this.isPlaying = true;
        this._tick();
    }

    pause() {
        this.isPlaying = false;
    }

    stop() {
        this.isPlaying = false;
        this.currentIndex = 0;
    }

    next() {
        if (this.currentIndex < this.events.length) {
            this.currentIndex++;
            return this.events[this.currentIndex - 1];
        }
        return null;
    }

    previous() {
        if (this.currentIndex > 0) {
            this.currentIndex--;
            return this.events[this.currentIndex];
        }
        return null;
    }

    _tick() {
        if (!this.isPlaying || this.currentIndex >= this.events.length) {
            this.isPlaying = false;
            return;
        }

        const event = this.events[this.currentIndex];
        this.currentIndex++;

        // 触发回调
        if (this.onEvent) this.onEvent(event);

        // 继续播放
        setTimeout(() => this._tick(), 2000);
    }

    renderTimeline(containerId) {
        const container = document.getElementById(containerId);
        if (!container) return;

        container.innerHTML = `
            <div class="timeline-container">
                <div class="timeline-track">
                    ${this.events.map((e, i) => `
                        <div class="timeline-marker ${e.type} ${i < this.currentIndex ? 'past' : ''} ${i === this.currentIndex ? 'current' : ''}"
                             data-index="${i}">
                        </div>
                    `).join('')}
                </div>
                <div class="timeline-controls">
                    <button class="btn-icon" onclick="historyPlayer.previous()" title="上一条">◀</button>
                    <button class="btn-icon" onclick="historyPlayer.play()" title="播放">▶</button>
                    <button class="btn-icon" onclick="historyPlayer.pause()" title="暂停">⏸</button>
                    <button class="btn-icon" onclick="historyPlayer.stop()" title="停止">⏹</button>
                    <button class="btn-icon" onclick="historyPlayer.next()" title="下一条">▶</button>
                </div>
            </div>
        `;
    }
}

// ==================== 异常告警卡片 ====================
class AnomalyAlertManager {
    constructor() {
        this.pendingAlerts = [];
        this.onAcknowledge = null;
    }

    addAlert(alert) {
        this.pendingAlerts.push(alert);
        this.showNextAlert();
    }

    showNextAlert() {
        if (this.pendingAlerts.length === 0) return;

        const alert = this.pendingAlerts[0];
        const modal = document.getElementById('anomalyAlertModal') || this.createModal();

        const severityColors = {
            low: '#3b82f6',
            medium: '#f59e0b',
            high: '#ef4444',
            critical: '#dc2626'
        };
        const color = severityColors[alert.severity] || '#6b7280';

        modal.innerHTML = `
            <div class="alert-card" style="border-left: 4px solid ${color}">
                <div class="alert-header">
                    <span class="alert-icon">${alert.severity_emoji || '⚠️'}</span>
                    <h3>${escapeHtml(alert.title)}</h3>
                </div>
                <div class="alert-body">
                    <p class="alert-description">${escapeHtml(alert.description)}</p>
                    <div class="alert-details">
                        ${Object.entries(alert.details || {}).map(([k, v]) => `
                            <div class="detail-row">
                                <span class="detail-key">${escapeHtml(k)}:</span>
                                <span class="detail-value">${escapeHtml(String(v))}</span>
                            </div>
                        `).join('')}
                    </div>
                    ${alert.suggestions?.length ? `
                        <div class="alert-suggestions">
                            <h4>建议操作:</h4>
                            <ul>
                                ${alert.suggestions.map(s => `<li>${escapeHtml(s)}</li>`).join('')}
                            </ul>
                        </div>
                    ` : ''}
                </div>
                <div class="alert-actions">
                    ${(alert.actions || []).map(a => `
                        <button class="btn btn-${a.style}" data-action="${a.id}">${escapeHtml(a.label)}</button>
                    `).join('')}
                </div>
            </div>
        `;

        modal.classList.add('active');

        // 绑定按钮事件
        modal.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', () => {
                this.handleAction(btn.dataset.action);
            });
        });
    }

    handleAction(action) {
        const alert = this.pendingAlerts.shift();
        this.closeModal();

        if (action === 'acknowledge' && this.onAcknowledge) {
            this.onAcknowledge(alert);
        }

        this.showNextAlert();
    }

    closeModal() {
        const modal = document.getElementById('anomalyAlertModal');
        if (modal) modal.classList.remove('active');
    }

    createModal() {
        const modal = document.createElement('div');
        modal.id = 'anomalyAlertModal';
        modal.className = 'modal alert-modal';
        modal.innerHTML = '<div class="modal-content alert-content"></div>';
        document.body.appendChild(modal);
        return modal;
    }
}

// ==================== 全局实例 ====================
const visManager = new VisualizationManager();
const templateSelector = new TemplateSelector();
const historyPlayer = new HistoryPlayer();
const anomalyAlertManager = new AnomalyAlertManager();

// 辅助函数
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 导出到全局
window.visManager = visManager;
window.templateSelector = templateSelector;
window.historyPlayer = historyPlayer;
window.anomalyAlertManager = anomalyAlertManager;
