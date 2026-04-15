"""
异常标注模块
检测和标注预测结果中的异常状态
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
import json
from datetime import datetime


class AnomalyType(Enum):
    """异常类型"""
    VALUE_SPIKE = "value_spike"           # 值突变
    THRESHOLD_BREACH = "threshold_breach"  # 阈值突破
    PATTERN_BREAK = "pattern_break"       # 模式破坏
    HIGH_VARIANCE = "high_variance"       # 高方差
    TREND_REVERSAL = "trend_reversal"     # 趋势反转
    OSCILLATION = "oscillation"            # 异常振荡
    FLATLINE = "flatline"                 # 长期平坦


class Severity(Enum):
    """严重程度"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class Anomaly:
    """异常记录"""
    anomaly_type: AnomalyType
    severity: Severity
    timestamp: float
    variable_name: str
    description: str
    details: Dict = field(default_factory=dict)
    
    # 上下文信息
    value: Optional[float] = None
    threshold: Optional[float] = None
    deviation: Optional[float] = None  # 偏离程度百分比
    
    # 元数据
    detected_at: Optional[str] = None
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    
    def to_dict(self) -> dict:
        return {
            'type': self.anomaly_type.value,
            'severity': self.severity.value,
            'timestamp': self.timestamp,
            'variable': self.variable_name,
            'description': self.description,
            'value': self.value,
            'threshold': self.threshold,
            'deviation': self.deviation,
            'acknowledged': self.acknowledged
        }


class AnomalyMarker:
    """
    异常标注器
    
    功能：
    1. 多维度异常检测
    2. 严重程度评估
    3. 异常上下文提取
    4. 生成标注卡片
    """
    
    def __init__(
        self,
        spike_threshold: float = 3.0,
        variance_threshold: float = 2.5,
        oscillation_threshold: float = 0.8
    ):
        """
        初始化异常标注器
        
        Args:
            spike_threshold: 突变阈值（标准差倍数）
            variance_threshold: 方差阈值
            oscillation_threshold: 振荡阈值
        """
        self.spike_threshold = spike_threshold
        self.variance_threshold = variance_threshold
        self.oscillation_threshold = oscillation_threshold
        
        # 阈值配置（可自定义）
        self.thresholds: Dict[str, Dict] = {}
    
    def set_threshold(self, variable: str, min_val: float, max_val: float) -> None:
        """设置变量的安全阈值"""
        self.thresholds[variable] = {
            'min': min_val,
            'max': max_val,
            'critical_min': min_val * 0.95,
            'critical_max': max_val * 1.05
        }
    
    def detect(
        self,
        timestamps: List[float],
        values: List[float],
        variable_name: str,
        unit: str = ""
    ) -> List[Anomaly]:
        """
        检测异常
        
        Args:
            timestamps: 时间戳列表
            values: 值列表
            variable_name: 变量名
            unit: 单位
            
        Returns:
            检测到的异常列表
        """
        anomalies = []
        n = len(values)
        
        if n < 5:
            return anomalies
        
        # 计算统计量
        import statistics
        mean = statistics.mean(values)
        stdev = statistics.stdev(values) if n > 1 else 0
        
        for i, (t, v) in enumerate(zip(timestamps, values)):
            # 1. 阈值突破检测
            if variable_name in self.thresholds:
                threshold = self.thresholds[variable_name]
                anomaly = self._check_threshold(
                    t, v, variable_name, unit, threshold
                )
                if anomaly:
                    anomalies.append(anomaly)
            
            # 2. 突变检测（3-sigma原则）
            if stdev > 0:
                deviation = abs(v - mean) / stdev
                if deviation > self.spike_threshold:
                    severity = self._calculate_severity(deviation, self.spike_threshold)
                    anomalies.append(Anomaly(
                        anomaly_type=AnomalyType.VALUE_SPIKE,
                        severity=severity,
                        timestamp=t,
                        variable_name=variable_name,
                        description=f"检测到{deviation:.1f}σ的突变",
                        details={'sigma': deviation, 'mean': mean, 'stdev': stdev},
                        value=v,
                        deviation=deviation
                    ))
            
            # 3. 趋势反转检测
            if 2 < i < n - 2:
                reversal = self._check_trend_reversal(values, i)
                if reversal:
                    anomalies.append(Anomaly(
                        anomaly_type=AnomalyType.TREND_REVERSAL,
                        severity=Severity.MEDIUM,
                        timestamp=t,
                        variable_name=variable_name,
                        description="检测到趋势突然反转",
                        details=reversal,
                        value=v
                    ))
            
            # 4. 振荡检测
            if 4 < i:
                oscillation = self._check_oscillation(values, i)
                if oscillation > self.oscillation_threshold:
                    anomalies.append(Anomaly(
                        anomaly_type=AnomalyType.OSCILLATION,
                        severity=Severity.MEDIUM if oscillation < 1.5 else Severity.HIGH,
                        timestamp=t,
                        variable_name=variable_name,
                        description=f"检测到异常振荡模式 (强度: {oscillation:.2f})",
                        details={'oscillation_strength': oscillation},
                        value=v
                    ))
        
        # 5. 高方差窗口检测
        variance_anomalies = self._check_variance_windows(values, timestamps, variable_name)
        anomalies.extend(variance_anomalies)
        
        # 6. 平坦期检测
        flatline = self._check_flatline(values, timestamps, variable_name)
        if flatline:
            anomalies.append(flatline)
        
        # 按时间排序
        anomalies.sort(key=lambda x: x.timestamp)
        
        return anomalies
    
    def _check_threshold(
        self,
        timestamp: float,
        value: float,
        variable: str,
        unit: str,
        threshold: Dict
    ) -> Optional[Anomaly]:
        """检查阈值突破"""
        if value < threshold['critical_min']:
            deviation = (threshold['min'] - value) / threshold['min'] * 100 if threshold['min'] != 0 else 0
            return Anomaly(
                anomaly_type=AnomalyType.THRESHOLD_BREACH,
                severity=Severity.CRITICAL if value < threshold['min'] else Severity.HIGH,
                timestamp=timestamp,
                variable_name=variable,
                description=f"值{v:.4f}{unit}低于安全下限 {threshold['min']}{unit}",
                value=value,
                threshold=threshold['min'],
                deviation=deviation
            )
        
        if value > threshold['critical_max']:
            deviation = (value - threshold['max']) / threshold['max'] * 100 if threshold['max'] != 0 else 0
            return Anomaly(
                anomaly_type=AnomalyType.THRESHOLD_BREACH,
                severity=Severity.CRITICAL if value > threshold['max'] else Severity.HIGH,
                timestamp=timestamp,
                variable_name=variable,
                description=f"值{v:.4f}{unit}超过安全上限 {threshold['max']}{unit}",
                value=value,
                threshold=threshold['max'],
                deviation=deviation
            )
        
        return None
    
    def _check_trend_reversal(
        self,
        values: List[float],
        index: int
    ) -> Optional[Dict]:
        """检查趋势反转"""
        # 前3个点和后3个点的平均斜率
        prev_slope = (values[index] - values[index - 2]) / 2
        next_slope = (values[index + 2] - values[index]) / 2
        
        # 符号相反表示反转
        if prev_slope * next_slope < 0 and abs(prev_slope) > 0.01 and abs(next_slope) > 0.01:
            return {
                'prev_slope': prev_slope,
                'next_slope': next_slope,
                'reversal_strength': abs(next_slope - prev_slope)
            }
        
        return None
    
    def _check_oscillation(
        self,
        values: List[float],
        index: int
    ) -> float:
        """检查振荡模式"""
        # 计算相邻差分的符号变化
        diffs = [values[i] - values[i - 1] for i in range(max(1, index - 4), index + 1)]
        sign_changes = sum(
            1 for i in range(1, len(diffs))
            if diffs[i] * diffs[i - 1] < 0
        )
        
        # 振荡强度 = 符号变化频率
        return sign_changes / max(1, len(diffs) - 1)
    
    def _check_variance_windows(
        self,
        values: List[float],
        timestamps: List[float],
        variable: str
    ) -> List[Anomaly]:
        """检查高方差窗口"""
        import statistics
        anomalies = []
        
        # 使用滑动窗口
        window_size = 10
        for i in range(window_size, len(values)):
            window = values[i - window_size:i]
            window_mean = statistics.mean(window)
            window_var = statistics.variance(window) if len(window) > 1 else 0
            
            # 全局方差
            full_mean = statistics.mean(values[:i])
            full_var = statistics.variance(values[:i]) if i > 1 else 0
            
            if full_var > 0:
                variance_ratio = window_var / full_var
                if variance_ratio > self.variance_threshold:
                    anomalies.append(Anomaly(
                        anomaly_type=AnomalyType.HIGH_VARIANCE,
                        severity=Severity.MEDIUM,
                        timestamp=timestamps[i],
                        variable_name=variable,
                        description=f"局部方差是全局方差的 {variance_ratio:.1f} 倍",
                        details={
                            'window_variance': window_var,
                            'global_variance': full_var,
                            'ratio': variance_ratio
                        },
                        value=values[i]
                    ))
        
        return anomalies
    
    def _check_flatline(
        self,
        values: List[float],
        timestamps: List[float],
        variable: str
    ) -> Optional[Anomaly]:
        """检查长期平坦"""
        if len(values) < 20:
            return None
        
        # 检查最后10个点是否几乎不变
        recent = values[-10:]
        recent_range = max(recent) - min(recent)
        recent_mean = sum(recent) / len(recent)
        
        if recent_mean != 0 and recent_range / recent_mean < 0.001:
            return Anomaly(
                anomaly_type=AnomalyType.FLATLINE,
                severity=Severity.LOW,
                timestamp=timestamps[-1],
                variable_name=variable,
                description=f"值在过去{len(recent)}个时间步保持稳定 (变化 < 0.1%)",
                details={
                    'mean': recent_mean,
                    'range': recent_range
                },
                value=recent_mean
            )
        
        return None
    
    def _calculate_severity(self, deviation: float, threshold: float) -> Severity:
        """计算严重程度"""
        ratio = deviation / threshold
        if ratio > 5:
            return Severity.CRITICAL
        elif ratio > 4:
            return Severity.HIGH
        elif ratio > 3:
            return Severity.MEDIUM
        else:
            return Severity.LOW
    
    def create_alert_card(self, anomaly: Anomaly) -> Dict:
        """
        创建告警卡片
        
        Args:
            anomaly: 异常对象
            
        Returns:
            告警卡片数据
        """
        severity_emoji = {
            Severity.LOW: "🔵",
            Severity.MEDIUM: "🟡",
            Severity.HIGH: "🟠",
            Severity.CRITICAL: "🔴"
        }
        
        action_suggestions = {
            AnomalyType.VALUE_SPIKE: ["检查数据源", "验证传感器", "排查突发干扰"],
            AnomalyType.THRESHOLD_BREACH: ["立即检查系统状态", "评估影响范围", "准备应急响应"],
            AnomalyType.TREND_REVERSAL: ["分析逆转原因", "评估对系统的影响", "考虑调整控制策略"],
            AnomalyType.HIGH_VARIANCE: ["检查系统稳定性", "评估噪声水平", "考虑增加平滑处理"],
            AnomalyType.OSCILLATION: ["检查反馈回路", "验证控制器参数", "排查谐振问题"],
            AnomalyType.FLATLINE: ["验证数据连接", "检查传感器状态", "确认系统是否宕机"]
        }
        
        return {
            'id': f"alert_{anomaly.timestamp}_{anomaly.variable_name}",
            'type': 'anomaly_alert',
            'severity': anomaly.severity.value,
            'severity_emoji': severity_emoji.get(anomaly.severity, "⚪"),
            'title': f"{anomaly.anomaly_type.value.replace('_', ' ').title()} - {anomaly.variable_name}",
            'description': anomaly.description,
            'details': {
                'variable': anomaly.variable_name,
                'value': f"{anomaly.value:.4f}" if anomaly.value else "N/A",
                'threshold': f"{anomaly.threshold:.4f}" if anomaly.threshold else "N/A",
                'deviation': f"{anomaly.deviation:.1f}σ" if anomaly.deviation else "N/A",
                'timestamp': anomaly.timestamp
            },
            'suggestions': action_suggestions.get(anomaly.anomaly_type, ["一般检查"]),
            'actions': [
                {'id': 'acknowledge', 'label': '确认已阅', 'style': 'secondary'},
                {'id': 'dismiss', 'label': '忽略', 'style': 'ghost'},
                {'id': 'investigate', 'label': '深入分析', 'style': 'primary'}
            ]
        }
    
    def get_summary(self, anomalies: List[Anomaly]) -> Dict:
        """获取异常摘要"""
        if not anomalies:
            return {
                'total': 0,
                'by_severity': {},
                'by_type': {},
                'risk_level': 'normal',
                'message': '未检测到异常'
            }
        
        by_severity = {}
        by_type = {}
        
        for a in anomalies:
            sev = a.severity.value
            typ = a.anomaly_type.value
            
            by_severity[sev] = by_severity.get(sev, 0) + 1
            by_type[typ] = by_type.get(typ, 0) + 1
        
        # 计算风险等级
        risk_score = 0
        risk_score += by_severity.get('critical', 0) * 10
        risk_score += by_severity.get('high', 0) * 5
        risk_score += by_severity.get('medium', 0) * 2
        risk_score += by_severity.get('low', 0) * 1
        
        if risk_score > 20:
            risk_level = 'critical'
        elif risk_score > 10:
            risk_level = 'high'
        elif risk_score > 5:
            risk_level = 'medium'
        else:
            risk_level = 'low'
        
        return {
            'total': len(anomalies),
            'by_severity': by_severity,
            'by_type': by_type,
            'risk_level': risk_level,
            'risk_score': risk_score,
            'message': self._get_risk_message(risk_level)
        }
    
    def _get_risk_message(self, risk_level: str) -> str:
        """获取风险消息"""
        messages = {
            'normal': '系统运行正常',
            'low': '检测到轻微异常，建议关注',
            'medium': '检测到中度异常，建议检查',
            'high': '检测到严重异常，需要立即处理',
            'critical': '系统处于危险状态，请立即响应！'
        }
        return messages.get(risk_level, '状态未知')
