"""
湍流度评估模块
评估复杂系统的湍流/混沌程度
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import math


class TurbulenceLevel(Enum):
    """湍流等级"""
    CALM = "calm"           # 平静
    MODERATE = "moderate"   # 中等
    TURBULENT = "turbulent" # 湍流
    CHAOTIC = "chaotic"     # 混沌


@dataclass
class TurbulenceMetrics:
    """湍流指标"""
    level: TurbulenceLevel
    score: float  # 0-100
    metrics: Dict[str, float]
    interpretation: str
    warnings: List[str]
    recommendations: List[str]


class TurbulenceEvaluator:
    """
    湍流度评估器
    
    综合多种指标评估系统的湍流程度
    """
    
    def __init__(self):
        self.history: List[TurbulenceMetrics] = []
    
    def evaluate(
        self,
        data: List[float],
        timestamps: Optional[List[float]] = None,
        thresholds: Optional[Dict[str, float]] = None
    ) -> TurbulenceMetrics:
        """
        评估湍流度
        
        Args:
            data: 时间序列数据
            timestamps: 时间戳列表
            thresholds: 自定义阈值
            
        Returns:
            湍流评估结果
        """
        if len(data) < 10:
            return TurbulenceMetrics(
                level=TurbulenceLevel.CALM,
                score=0,
                metrics={},
                interpretation="数据不足",
                warnings=[],
                recommendations=["需要更多数据进行分析"]
            )
        
        # 计算各项指标
        metrics = {}
        
        # 1. 波动率
        metrics['volatility'] = self._calculate_volatility(data)
        
        # 2. 变化率
        metrics['change_rate'] = self._calculate_change_rate(data)
        
        # 3. 不规则性
        metrics['irregularity'] = self._calculate_irregularity(data)
        
        # 4. 相关性衰减
        metrics['correlation_decay'] = self._calculate_correlation_decay(data)
        
        # 5. 能量分布
        metrics['energy_distribution'] = self._calculate_energy_distribution(data)
        
        # 计算综合得分
        score = self._compute_turbulence_score(metrics)
        
        # 确定等级
        level = self._determine_level(score)
        
        # 生成警告和建议
        warnings = self._generate_warnings(metrics, level)
        recommendations = self._generate_recommendations(metrics, level)
        
        result = TurbulenceMetrics(
            level=level,
            score=score,
            metrics=metrics,
            interpretation=self._interpret(level, score),
            warnings=warnings,
            recommendations=recommendations
        )
        
        # 保存历史
        self.history.append(result)
        
        return result
    
    def _calculate_volatility(self, data: List[float]) -> float:
        """计算波动率 (标准差/均值)"""
        if len(data) < 2:
            return 0.0
        
        mean = sum(data) / len(data)
        if mean == 0:
            return 0.0
        
        variance = sum((x - mean) ** 2 for x in data) / len(data)
        std = math.sqrt(variance)
        
        return (std / abs(mean)) * 100  # 百分比
    
    def _calculate_change_rate(self, data: List[float]) -> float:
        """计算变化率"""
        if len(data) < 2:
            return 0.0
        
        changes = [abs(data[i] - data[i-1]) for i in range(1, len(data))]
        
        mean_change = sum(changes) / len(changes)
        
        # 相对于数据范围的百分比
        data_range = max(data) - min(data) if data else 1
        
        return (mean_change / max(data_range, 0.001)) * 100
    
    def _calculate_irregularity(self, data: List[float]) -> float:
        """计算不规则性 (基于差分的方差)"""
        if len(data) < 3:
            return 0.0
        
        diffs = [data[i] - data[i-1] for i in range(1, len(data))]
        
        diff_mean = sum(diffs) / len(diffs)
        diff_var = sum((d - diff_mean) ** 2 for d in diffs) / len(diffs)
        
        return math.sqrt(diff_var)
    
    def _calculate_correlation_decay(self, data: List[float]) -> float:
        """计算自相关衰减速度"""
        if len(data) < 10:
            return 0.0
        
        # 计算滞后1到lag的自相关
        max_lag = min(20, len(data) // 4)
        
        correlations = []
        for lag in range(1, max_lag + 1):
            corr = self._autocorrelation(data, lag)
            if corr is not None:
                correlations.append(abs(corr))
        
        if len(correlations) < 2:
            return 100.0
        
        # 衰减速度：自相关下降到一半所需的滞后数
        threshold = correlations[0] / 2 if correlations[0] > 0 else 0.5
        
        decay_lag = max_lag
        for i, corr in enumerate(correlations):
            if corr < threshold:
                decay_lag = i
                break
        
        # 转换为百分比（越小越规则）
        return (decay_lag / max_lag) * 100
    
    def _autocorrelation(self, data: List[float], lag: int) -> Optional[float]:
        """计算自相关系数"""
        n = len(data)
        if n <= lag:
            return None
        
        mean = sum(data) / n
        c0 = sum((x - mean) ** 2 for x in data) / n
        
        if c0 == 0:
            return 0.0
        
        c_lag = sum((data[i] - mean) * (data[i + lag] - mean) for i in range(n - lag)) / (n - lag)
        
        return c_lag / c0
    
    def _calculate_energy_distribution(self, data: List[float]) -> float:
        """计算能量分布均匀度"""
        if len(data) < 4:
            return 0.0
        
        # 使用差分近似功率
        power = [(data[i] - data[i-1]) ** 2 for i in range(1, len(data))]
        
        if not power:
            return 0.0
        
        total_power = sum(power)
        if total_power == 0:
            return 0.0
        
        # 计算功率的熵
        normalized_power = [p / total_power for p in power]
        entropy = 0.0
        
        for p in normalized_power:
            if p > 0:
                entropy -= p * math.log2(p)
        
        # 最大熵
        max_entropy = math.log2(len(power)) if len(power) > 1 else 1
        
        # 返回均匀度
        return (entropy / max_entropy) * 100 if max_entropy > 0 else 0.0
    
    def _compute_turbulence_score(self, metrics: Dict[str, float]) -> float:
        """计算综合湍流得分"""
        # 权重
        weights = {
            'volatility': 0.25,
            'change_rate': 0.20,
            'irregularity': 0.20,
            'correlation_decay': 0.20,
            'energy_distribution': 0.15
        }
        
        score = sum(
            min(metrics.get(key, 0), 100) * weight
            for key, weight in weights.items()
        )
        
        return round(score, 2)
    
    def _determine_level(self, score: float) -> TurbulenceLevel:
        """确定湍流等级"""
        if score < 20:
            return TurbulenceLevel.CALM
        elif score < 50:
            return TurbulenceLevel.MODERATE
        elif score < 75:
            return TurbulenceLevel.TURBULENT
        else:
            return TurbulenceLevel.CHAOTIC
    
    def _interpret(self, level: TurbulenceLevel, score: float) -> str:
        """解释评估结果"""
        interpretations = {
            TurbulenceLevel.CALM: "系统状态平稳，波动较小，适合常规预测方法",
            TurbulenceLevel.MODERATE: "系统存在一定波动，建议使用带置信区间的预测",
            TurbulenceLevel.TURBULENT: "系统波动较大，建议增加预测频率或使用集成方法",
            TurbulenceLevel.CHAOTIC: "系统接近或处于混沌状态，预测不确定性极高"
        }
        return interpretations.get(level, "状态未知")
    
    def _generate_warnings(self, metrics: Dict[str, float], level: TurbulenceLevel) -> List[str]:
        """生成警告"""
        warnings = []
        
        if metrics.get('volatility', 0) > 30:
            warnings.append("波动率异常高，系统稳定性存疑")
        
        if metrics.get('change_rate', 0) > 40:
            warnings.append("变化率过快，可能存在异常事件")
        
        if metrics.get('correlation_decay', 0) > 60:
            warnings.append("自相关快速衰减，系统历史记忆短")
        
        if level in [TurbulenceLevel.TURBULENT, TurbulenceLevel.CHAOTIC]:
            warnings.append("系统可能处于不稳定状态，建议密切关注")
        
        return warnings
    
    def _generate_recommendations(self, metrics: Dict[str, float], level: TurbulenceLevel) -> List[str]:
        """生成建议"""
        recommendations = []
        
        if level == TurbulenceLevel.CALM:
            recommendations.append("当前预测方法可继续使用")
            recommendations.append("可适当降低预测频率以节省资源")
        
        elif level == TurbulenceLevel.MODERATE:
            recommendations.append("建议启用置信区间输出")
            recommendations.append("保持当前预测频率")
        
        elif level == TurbulenceLevel.TURBULENT:
            recommendations.append("增加预测频率，捕捉更多变化细节")
            recommendations.append("考虑使用集成预测方法")
            recommendations.append("向用户发出状态提醒")
        
        else:  # CHAOTIC
            recommendations.append("预测仅供参考，实际值可能大幅偏离")
            recommendations.append("大幅增加预测频率")
            recommendations.append("建议启动人工监控模式")
            recommendations.append("考虑触发紧急告警")
        
        return recommendations
    
    def get_trend(self) -> Dict:
        """获取湍流度趋势"""
        if len(self.history) < 2:
            return {'status': 'insufficient_data'}
        
        scores = [h.score for h in self.history]
        current = scores[-1]
        previous = scores[-2]
        change = current - previous
        
        levels = [h.level for h in self.history]
        
        return {
            'current_score': current,
            'previous_score': previous,
            'change': change,
            'trend': 'increasing' if change > 5 else 'decreasing' if change < -5 else 'stable',
            'level_history': [l.value for l in levels[-5:]]
        }


class ChaosDetector:
    """
    混沌检测器
    
    检测系统是否表现出混沌特征
    """
    
    def __init__(self):
        self.lyapunov_exponent_estimate: float = 0.0
    
    def detect_chaos(self, data: List[float]) -> Dict:
        """
        检测混沌特征
        
        Returns:
            混沌检测结果
        """
        if len(data) < 50:
            return {
                'is_chaotic': False,
                'confidence': 0,
                'reason': '数据不足'
            }
        
        # 1. 计算李雅普诺夫指数估计
        lyapunov = self._estimate_lyapunov(data)
        
        # 2. 计算最大李雅普诺夫指数
        mlp = self._max_lyapunov_exponent(data)
        
        # 3. 计算关联维数估计
        dimension = self._estimate_correlation_dimension(data)
        
        # 混沌判定
        is_chaotic = mlp > 0 and dimension > 1.5 and dimension < 5
        
        # 计算置信度
        confidence = min(abs(mlp) * 10, 1.0) if mlp > 0 else 0
        
        return {
            'is_chaotic': is_chaotic,
            'confidence': round(confidence * 100, 1),
            'metrics': {
                'lyapunov_exponent': round(lyapunov, 4),
                'max_lyapunov': round(mlp, 4),
                'correlation_dimension': round(dimension, 2)
            },
            'interpretation': self._interpret_chaos(is_chaotic, mlp, dimension)
        }
    
    def _estimate_lyapunov(self, data: List[float]) -> float:
        """估计李雅普诺夫指数"""
        if len(data) < 30:
            return 0.0
        
        # 使用简化的指数增长估计
        n = len(data) // 2
        
        divergences = []
        for i in range(n):
            if i + n < len(data):
                diff = abs(data[i + n] - data[i])
                if diff > 0:
                    divergences.append(math.log(diff))
        
        if not divergences:
            return 0.0
        
        return sum(divergences) / len(divergences)
    
    def _max_lyapunov_exponent(self, data: List[float]) -> float:
        """计算最大李雅普诺夫指数"""
        if len(data) < 50:
            return 0.0
        
        # 简化计算
        n = len(data) - 1
        lyapunov_sum = 0.0
        
        for i in range(n):
            diff = abs(data[i + 1] - data[i])
            if diff > 1e-10:
                lyapunov_sum += math.log(diff)
        
        return lyapunov_sum / n if n > 0 else 0.0
    
    def _estimate_correlation_dimension(self, data: List[float]) -> float:
        """估计关联维数"""
        if len(data) < 20:
            return 0.0
        
        # 简化的维数估计
        # 使用数据的方差和自相关来估计
        
        variance = sum((x - sum(data)/len(data))**2 for x in data) / len(data)
        
        # 计算自相关时间
        autocorr = []
        for lag in range(1, min(20, len(data)//2)):
            c = self._autocorr(data, lag)
            autocorr.append(abs(c))
        
        # 找到自相关下降到1/e的位置
        threshold = 1 / math.e
        dimension = 2.0
        
        for i, ac in enumerate(autocorr):
            if ac < threshold:
                dimension = 2.0 + i * 0.1
                break
        
        return dimension
    
    def _autocorr(self, data: List[float], lag: int) -> float:
        """自相关"""
        n = len(data)
        if n <= lag:
            return 0.0
        
        mean = sum(data) / n
        c0 = sum((x - mean) ** 2 for x in data)
        
        if c0 == 0:
            return 0.0
        
        c_lag = sum((data[i] - mean) * (data[i + lag] - mean) for i in range(n - lag))
        
        return c_lag / c0
    
    def _interpret_chaos(
        self,
        is_chaotic: bool,
        lyapunov: float,
dimension: float
    ) -> str:
        """解释混沌检测结果"""
        if is_chaotic:
            return f"检测到混沌特征 (λ≈{lyapunov:.3f}, D≈{dimension:.1f})。系统长期不可预测。"
        elif lyapunov > -0.1:
            return f"系统接近混沌边界。需密切关注。"
        else:
            return f"系统无明显混沌特征 (λ≈{lyapunov:.3f}, D≈{dimension:.1f})。"
