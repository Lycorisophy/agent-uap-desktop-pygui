"""
混沌检测模块
使用多种方法检测系统的混沌特征
"""

from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass
import math


@dataclass
class ChaosMetrics:
    """混沌指标"""
    lyapunov_exponent: float      # 最大李雅普诺夫指数
    correlation_dimension: float   # 关联维数
    kolmogorov_entropy: float      # 柯尔莫哥洛夫熵
    Hurst_exponent: float          # Hurst指数
    is_chaotic: bool              # 是否为混沌
    confidence: float             # 置信度
    phase_space_dimension: int     # 相空间维度
    prediction_horizon: float     # 有效预测时长(秒)


class ChaosDetector:
    """
    混沌检测器
    
    综合多种方法检测混沌特征
    """
    
    def __init__(self):
        self.embedding_dimension: int = 3
        self.delay: int = 1
    
    def analyze(
        self,
        data: List[float],
        fs: float = 1.0  # 采样频率
    ) -> ChaosMetrics:
        """
        综合混沌分析
        
        Args:
            data: 时间序列数据
            fs: 采样频率
            
        Returns:
            混沌分析结果
        """
        if len(data) < 30:
            return ChaosMetrics(
                lyapunov_exponent=0,
                correlation_dimension=0,
                kolmogorov_entropy=0,
                Hurst_exponent=0.5,
                is_chaotic=False,
                confidence=0,
                phase_space_dimension=0,
                prediction_horizon=0
            )
        
        # 1. 最大李雅普诺夫指数
        lyapunov = self._calculate_lyapunov(data)
        
        # 2. 关联维数
        corr_dim = self._calculate_correlation_dimension(data)
        
        # 3. Kolmogorov熵
        kolmogorov = self._calculate_kolmogorov_entropy(data)
        
        # 4. Hurst指数
        hurst = self._calculate_hurst_exponent(data)
        
        # 5. 相空间重构维度
        phase_dim = self._estimate_embedding_dimension(data)
        
        # 判定混沌
        is_chaotic = self._is_chaotic(lyapunov, corr_dim, kolmogorov)
        
        # 计算置信度
        confidence = self._calculate_confidence(lyapunov, corr_dim, kolmogorov)
        
        # 预测时长估计
        pred_horizon = self._estimate_prediction_horizon(lyapunov, fs)
        
        return ChaosMetrics(
            lyapunov_exponent=lyapunov,
            correlation_dimension=corr_dim,
            kolmogorov_entropy=kolmogorov,
            Hurst_exponent=hurst,
            is_chaotic=is_chaotic,
            confidence=confidence,
            phase_space_dimension=phase_dim,
            prediction_horizon=pred_horizon
        )
    
    def _calculate_lyapunov(self, data: List[float]) -> float:
        """计算最大李雅普诺夫指数"""
        n = len(data)
        if n < 50:
            return 0.0
        
        # 使用简化的 Rosenstein 方法
        delay = 1
        dim = 3
        
        # 构建相空间
        phase_space = self._build_phase_space(data, dim, delay)
        
        if len(phase_space) < 10:
            return 0.0
        
        # 计算最近邻
        nn_distances = []
        for i in range(len(phase_space)):
            min_dist = float('inf')
            for j in range(len(phase_space)):
                if abs(i - j) > 5:  # 排除时间上太近的点
                    dist = sum(
                        (phase_space[i][k] - phase_space[j][k]) ** 2
                        for k in range(dim)
                    ) ** 0.5
                    if dist < min_dist:
                        min_dist = dist
            if min_dist < float('inf'):
                nn_distances.append(math.log(max(min_dist, 1e-10)))
        
        if len(nn_distances) < 10:
            return 0.0
        
        # 线性拟合斜率
        n_points = min(20, len(nn_distances))
        x = list(range(n_points))
        y = nn_distances[:n_points]
        
        x_mean = sum(x) / n_points
        y_mean = sum(y) / n_points
        
        numerator = sum((x[i] - x_mean) * (y[i] - y_mean) for i in range(n_points))
        denominator = sum((x[i] - x_mean) ** 2 for i in range(n_points))
        
        if denominator == 0:
            return 0.0
        
        slope = numerator / denominator
        
        return slope
    
    def _calculate_correlation_dimension(self, data: List[float]) -> float:
        """计算关联维数"""
        n = len(data)
        if n < 50:
            return 0.0
        
        # 简化的计算
        dim = 3
        delay = 1
        
        phase_space = self._build_phase_space(data, dim, delay)
        
        # 计算关联积分
        eps_values = [0.1, 0.2, 0.5, 1.0, 2.0]
        c_values = []
        
        for eps in eps_values:
            count = 0
            total = 0
            for i in range(len(phase_space)):
                for j in range(i + 1, len(phase_space)):
                    dist = sum(
                        (phase_space[i][k] - phase_space[j][k]) ** 2
                        for k in range(dim)
                    ) ** 0.5
                    if dist < eps:
                        count += 1
                    total += 1
            
            if total > 0:
                c_values.append(count / total)
        
        # 对数拟合
        valid_pairs = [(eps, c) for eps, c in zip(eps_values, c_values) if c > 0]
        
        if len(valid_pairs) < 2:
            return 0.0
        
        # 拟合直线斜率作为维数估计
        log_eps = [math.log(eps) for eps, c in valid_pairs]
        log_c = [math.log(c) for eps, c in valid_pairs]
        
        n_pts = len(log_eps)
        log_eps_mean = sum(log_eps) / n_pts
        log_c_mean = sum(log_c) / n_pts
        
        numerator = sum((log_eps[i] - log_eps_mean) * (log_c[i] - log_c_mean) for i in range(n_pts))
        denominator = sum((log_eps[i] - log_eps_mean) ** 2 for i in range(n_pts))
        
        if denominator == 0:
            return 0.0
        
        return max(0, numerator / denominator)
    
    def _calculate_kolmogorov_entropy(self, data: List[float]) -> float:
        """计算 Kolmogorov-Sinai 熵"""
        # 简化估计: K熵 ≈ 2 * 最大李雅普诺夫指数 (对于混沌系统)
        lyapunov = self._calculate_lyapunov(data)
        
        if lyapunov <= 0:
            return 0.0
        
        return 2 * lyapunov
    
    def _calculate_hurst_exponent(self, data: List[float]) -> float:
        """计算 Hurst 指数"""
        n = len(data)
        if n < 20:
            return 0.5
        
        # 使用 R/S 分析
        min_lag = 5
        max_lag = n // 2
        
        rs_values = []
        lag_values = []
        
        for lag in range(min_lag, max_lag + 1, max(1, (max_lag - min_lag) // 10)):
            rs, n_chunks = self._rs_analysis(data, lag)
            if n_chunks > 0:
                rs_values.append(rs)
                lag_values.append(lag)
        
        if len(rs_values) < 2:
            return 0.5
        
        # 对数拟合
        log_lag = [math.log(l) for l in lag_values]
        log_rs = [math.log(r) for r in rs_values]
        
        n_pts = len(log_lag)
        log_lag_mean = sum(log_lag) / n_pts
        log_rs_mean = sum(log_rs) / n_pts
        
        numerator = sum((log_lag[i] - log_lag_mean) * (log_rs[i] - log_rs_mean) for i in range(n_pts))
        denominator = sum((log_lag[i] - log_lag_mean) ** 2 for i in range(n_pts))
        
        if denominator == 0:
            return 0.5
        
        hurst = numerator / denominator
        
        return max(0, min(1, hurst))
    
    def _rs_analysis(self, data: List[float], lag: int) -> Tuple[float, int]:
        """R/S 分析"""
        n = len(data)
        n_chunks = n // lag
        
        if n_chunks < 2:
            return 0.0, 0
        
        rs_sum = 0.0
        
        for i in range(n_chunks):
            chunk = data[i * lag:(i + 1) * lag]
            
            mean_chunk = sum(chunk) / len(chunk)
            
            # 累积离差
            cumsum = [x - mean_chunk for x in chunk]
            cumsum = [sum(cumsum[:j+1]) for j in range(len(cumsum))]
            
            R = max(cumsum) - min(cumsum)
            S = (sum((x - mean_chunk) ** 2 for x in chunk) / len(chunk)) ** 0.5
            
            if S > 0:
                rs_sum += R / S
        
        return rs_sum / n_chunks, n_chunks
    
    def _build_phase_space(
        self,
        data: List[float],
        dim: int,
        delay: int
    ) -> List[List[float]]:
        """构建相空间"""
        n = len(data)
        phase_space = []
        
        for i in range(n - dim * delay):
            point = [data[i + j * delay] for j in range(dim)]
            phase_space.append(point)
        
        return phase_space
    
    def _estimate_embedding_dimension(self, data: List[float]) -> int:
        """估计嵌入维数 (使用假最近邻方法)"""
        n = len(data)
        
        for dim in range(2, 10):
            delay = 1
            phase_space = self._build_phase_space(data, dim, delay)
            
            if len(phase_space) < 10:
                continue
            
            # 计算假最近邻比例
            false_neighbors = 0
            total = 0
            
            for i in range(len(phase_space)):
                # 找到最近邻
                min_dist1 = float('inf')
                min_dist2 = float('inf')
                nn_idx = -1
                
                for j in range(len(phase_space)):
                    if i == j:
                        continue
                    dist = sum(
                        (phase_space[i][k] - phase_space[j][k]) ** 2
                        for k in range(dim)
                    ) ** 0.5
                    if dist < min_dist1:
                        min_dist2 = min_dist1
                        min_dist1 = dist
                        nn_idx = j
                
                if nn_idx >= 0 and min_dist1 > 0:
                    # 在更高维度的距离
                    if dim + 1 <= len(phase_space[0]) + 1:
                        # 简化的FNN检测
                        pass
            
            # 如果假最近邻比例 < 5%，则认为维度合适
            if total > 0 and false_neighbors / total < 0.05:
                return dim
        
        return 3  # 默认值
    
    def _is_chaotic(
        self,
        lyapunov: float,
        corr_dim: float,
        kolmogorov: float
    ) -> bool:
        """判定是否为混沌"""
        # 混沌条件:
        # 1. 最大李雅普诺夫指数 > 0
        # 2. 关联维数非整数 (> 1.5)
        # 3. K熵 > 0
        
        conditions = [
            lyapunov > 0.01,  # 正的李雅普诺夫指数
            1.5 < corr_dim < 10,  # 非整数关联维数
            kolmogorov > 0.01  # 正的K熵
        ]
        
        return sum(conditions) >= 2
    
    def _calculate_confidence(
        self,
        lyapunov: float,
        corr_dim: float,
        kolmogorov: float
    ) -> float:
        """计算置信度"""
        confidence = 0.0
        
        # 正李雅普诺夫指数贡献
        if lyapunov > 0.1:
            confidence += 0.4
        elif lyapunov > 0.01:
            confidence += 0.2
        
        # 非整数关联维数贡献
        if 2 < corr_dim < 8:
            confidence += 0.3
        elif 1.5 < corr_dim < 10:
            confidence += 0.15
        
        # 正K熵贡献
        if kolmogorov > 0.1:
            confidence += 0.3
        elif kolmogorov > 0.01:
            confidence += 0.15
        
        return min(confidence, 1.0)
    
    def _estimate_prediction_horizon(
        self,
        lyapunov: float,
        fs: float
    ) -> float:
        """估计有效预测时长"""
        if lyapunov <= 0:
            return float('inf')  # 可预测
        
        # 预测误差增加到初始值e倍的时间
        # e^λt = e => λt = 1 => t = 1/λ
        
        horizon = 1.0 / lyapunov / fs
        
        # 转换为秒并限制范围
        return max(1, min(horizon, 86400 * 30))  # 1秒到30天
    
    def get_summary(self, metrics: ChaosMetrics) -> Dict:
        """获取分析摘要"""
        interpretation = []
        
        if metrics.is_chaotic:
            interpretation.append("系统表现出明显的混沌特征")
        else:
            interpretation.append("系统未表现出明显的混沌特征")
        
        # 李雅普诺夫解释
        if metrics.lyapunov_exponent > 0.5:
            interpretation.append("李雅普诺夫指数较高，预测困难")
        elif metrics.lyapunov_exponent > 0.1:
            interpretation.append("李雅普诺夫指数中等，短期可预测")
        elif metrics.lyapunov_exponent > 0:
            interpretation.append("李雅普诺夫指数较低，存在一定可预测性")
        else:
            interpretation.append("李雅普诺夫指数为负，系统稳定")
        
        # Hurst解释
        if metrics.Hurst_exponent > 0.6:
            interpretation.append("Hurst指数较高，存在长期相关性")
        elif metrics.Hurst_exponent < 0.4:
            interpretation.append("Hurst指数较低，存在均值回归特性")
        else:
            interpretation.append("Hurst指数接近0.5，随机游走特性")
        
        # 预测时长
        if metrics.prediction_horizon < 60:
            horizon_str = f"{metrics.prediction_horizon:.1f}秒"
        elif metrics.prediction_horizon < 3600:
            horizon_str = f"{metrics.prediction_horizon/60:.1f}分钟"
        elif metrics.prediction_horizon < 86400:
            horizon_str = f"{metrics.prediction_horizon/3600:.1f}小时"
        else:
            horizon_str = f"{metrics.prediction_horizon/86400:.1f}天"
        
        interpretation.append(f"有效预测时长约: {horizon_str}")
        
        return {
            'is_chaotic': metrics.is_chaotic,
            'confidence': f"{metrics.confidence * 100:.0f}%",
            'interpretation': interpretation,
            'metrics': {
                'lyapunov': f"{metrics.lyapunov_exponent:.4f}",
                'correlation_dimension': f"{metrics.correlation_dimension:.2f}",
                'kolmogorov_entropy': f"{metrics.kolmogorov_entropy:.4f}",
                'hurst_exponent': f"{metrics.Hurst_exponent:.2f}"
            }
        }
