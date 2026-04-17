"""
预测器基类和预测方法定义
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional, Any

import numpy as np

from uap.project.models import SystemModel, PredictionConfig, PredictionResult


class PredictionMethod(Enum):
    """预测方法枚举"""
    MONTE_CARLO = "monte_carlo"  # 蒙特卡洛模拟
    KOOPMAN = "koopman"          # Koopman算子方法
    SIMULATION = "simulation"      # 简单数值模拟


@dataclass
class TrajectoryPoint:
    """轨迹上的单个点"""
    timestamp: datetime
    values: dict[str, float]  # 变量名 -> 值
    uncertainty: Optional[dict[str, float]] = None  # 不确定性估计


@dataclass 
class Anomaly:
    """检测到的异常"""
    timestamp: datetime
    variable: str
    value: float
    threshold: float
    severity: str  # "warning" | "critical"
    description: str


class Predictor(ABC):
    """
    预测器抽象基类
    
    所有预测方法都必须实现此接口。
    支持对复杂系统进行未来状态预测。
    """
    
    def __init__(self, model: SystemModel):
        """
        初始化预测器
        
        Args:
            model: 系统数学模型
        """
        self.model = model
        self._validate_model()
    
    def _validate_model(self):
        """验证模型有效性"""
        if not self.model.variables:
            raise ValueError("模型必须包含至少一个变量")
    
    @abstractmethod
    def predict(
        self,
        initial_state: dict[str, float],
        horizon_sec: int,
        frequency_sec: int,
    ) -> PredictionResult:
        """
        执行预测
        
        Args:
            initial_state: 初始状态 {变量名: 值}
            horizon_sec: 预测时长（秒）
            frequency_sec: 输出频率（秒）
            
        Returns:
            PredictionResult: 预测结果
        """
        pass
    
    def _generate_trajectory(
        self,
        initial_state: dict[str, float],
        horizon_sec: int,
        frequency_sec: int,
        step_func
    ) -> tuple[list[TrajectoryPoint], list[Anomaly]]:
        """
        生成预测轨迹的通用方法
        
        Args:
            initial_state: 初始状态
            horizon_sec: 预测时长
            frequency_sec: 输出频率
            step_func: 每步计算函数 (state, dt) -> new_state
            
        Returns:
            tuple: (轨迹点列表, 异常列表)
        """
        trajectory = []
        anomalies = []
        
        current_time = datetime.now()
        current_state = initial_state.copy()
        num_steps = horizon_sec // frequency_sec
        
        for step in range(num_steps):
            # 记录当前点
            trajectory.append(TrajectoryPoint(
                timestamp=current_time,
                values=current_state.copy()
            ))
            
            # 计算下一步状态
            dt = frequency_sec
            current_state = step_func(current_state, dt)
            current_time += timedelta(seconds=frequency_sec)
            
            # 检查异常
            for var_name, value in current_state.items():
                # 获取变量的范围约束
                for constraint in self.model.constraints:
                    if constraint.type == "range":
                        # 解析约束表达式，如 "x > 0" 或 "y < 100"
                        try:
                            var_value = value
                            expr = constraint.expression
                            
                            # 简单检查超出范围
                            var_def = next(
                                (v for v in self.model.variables if v.name == var_name),
                                None
                            )
                            if var_def and var_def.range:
                                min_val = var_def.range.get("min")
                                max_val = var_def.range.get("max")
                                
                                if min_val is not None and value < min_val:
                                    anomalies.append(Anomaly(
                                        timestamp=current_time,
                                        variable=var_name,
                                        value=value,
                                        threshold=min_val,
                                        severity="warning",
                                        description=f"{var_name}低于最小值{min_val}"
                                    ))
                                
                                if max_val is not None and value > max_val:
                                    anomalies.append(Anomaly(
                                        timestamp=current_time,
                                        variable=var_name,
                                        value=value,
                                        threshold=max_val,
                                        severity="critical" if value > max_val * 1.1 else "warning",
                                        description=f"{var_name}超过最大值{max_val}"
                                    ))
                        except Exception:
                            pass
        
        return trajectory, anomalies
    
    def _calculate_entropy(self, trajectory: list[TrajectoryPoint]) -> float:
        """
        计算轨迹的香农熵
        
        用于衡量系统的不确定性/混沌程度。
        
        Args:
            trajectory: 预测轨迹
            
        Returns:
            float: 熵值 (0 = 完全确定, 更高 = 更多不确定性)
        """
        if len(trajectory) < 2:
            return 0.0
        
        # 简化实现：基于状态变化的方差计算熵
        all_values = []
        for point in trajectory:
            all_values.extend(point.values.values())
        
        if not all_values:
            return 0.0
        
        # 将连续值离散化为直方图
        values_array = np.array(all_values)
        
        # 计算相邻变化的分布
        if len(values_array) > 10:
            changes = np.diff(values_array[:100])
            hist, _ = np.histogram(changes, bins=10, density=True)
            hist = hist[hist > 0]  # 移除零概率
            
            if len(hist) > 0:
                entropy = -np.sum(hist * np.log(hist + 1e-10))
                return float(entropy)
        
        return 0.0
    
    def _assess_turbulence(
        self,
        trajectory: list[TrajectoryPoint]
    ) -> tuple[str, float]:
        """
        评估系统的湍流程度
        
        Args:
            trajectory: 预测轨迹
            
        Returns:
            tuple: (湍流级别, 湍流指数)
        """
        if len(trajectory) < 3:
            return "laminar", 0.0
        
        # 计算状态变化的方差
        changes = []
        for i in range(1, len(trajectory)):
            prev_vals = list(trajectory[i-1].values.values())
            curr_vals = list(trajectory[i].values.values())
            
            if len(prev_vals) == len(curr_vals) and len(prev_vals) > 0:
                diff = np.mean(np.abs(np.array(curr_vals) - np.array(prev_vals)))
                changes.append(diff)
        
        if not changes:
            return "laminar", 0.0
        
        changes_array = np.array(changes)
        
        # 计算变异系数
        mean_change = np.mean(changes_array)
        std_change = np.std(changes_array)
        
        if mean_change == 0:
            return "laminar", 0.0
        
        cv = std_change / mean_change  # 变异系数
        
        # 基于变异系数判断湍流程度
        if cv < 0.1:
            return "laminar", cv
        elif cv < 0.5:
            return "transition", cv
        else:
            return "turbulent", cv
    
    def _calculate_confidence_intervals(
        self,
        trajectory: list[TrajectoryPoint]
    ) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
        """
        计算各变量的置信区间
        
        Args:
            trajectory: 预测轨迹
            
        Returns:
            tuple: (lower_bounds, upper_bounds) - 每个时间点的置信区间
        """
        if not trajectory:
            return {}, {}
        
        variables = list(trajectory[0].values.keys())
        
        lower = {v: [] for v in variables}
        upper = {v: [] for v in variables}
        
        # 简化实现：使用固定百分比扩展置信区间
        for point in trajectory:
            for var in variables:
                value = point.values.get(var, 0)
                # ±5% 作为置信区间
                lower[var].append(value * 0.95)
                upper[var].append(value * 1.05)
        
        return lower, upper


class MonteCarloPredictor(Predictor):
    """
    蒙特卡洛预测器
    
    通过多次随机模拟来估计系统的不确定性。
    """
    
    def __init__(self, model: SystemModel, n_simulations: int = 100):
        """
        初始化蒙特卡洛预测器
        
        Args:
            model: 系统模型
            n_simulations: 模拟次数
        """
        super().__init__(model)
        self.n_simulations = n_simulations
    
    def predict(
        self,
        initial_state: dict[str, float],
        horizon_sec: int,
        frequency_sec: int,
    ) -> PredictionResult:
        """
        执行蒙特卡洛预测
        
        通过多次模拟计算轨迹的统计特性。
        """
        all_trajectories = []
        
        for _ in range(self.n_simulations):
            # 每次模拟添加少量噪声
            state = initial_state.copy()
            trajectory = []
            
            current_time = datetime.now()
            num_steps = horizon_sec // frequency_sec
            
            for _ in range(num_steps):
                trajectory.append({
                    "time": current_time,
                    "values": state.copy()
                })
                
                # 添加随机扰动并更新状态
                for var in state:
                    noise = np.random.normal(0, 0.01 * abs(state[var]) + 0.001)
                    state[var] = state[var] + noise
                
                current_time += timedelta(seconds=frequency_sec)
            
            all_trajectories.append(trajectory)
        
        # 计算统计量
        mean_trajectory = self._compute_mean_trajectory(all_trajectories)
        lower, upper = self._compute_percentile_bands(all_trajectories, 5, 95)
        
        # 构建结果
        points = []
        for i, mean_point in enumerate(mean_trajectory):
            points.append({
                "timestamp": mean_point["time"].isoformat(),
                "values": mean_point["values"],
                "confidence_lower": {k: lower[i]["values"][k] for k in lower[i]["values"]},
                "confidence_upper": {k: upper[i]["values"][k] for k in upper[i]["values"]}
            })
        
        # 检测异常
        anomalies = self._detect_anomalies(mean_trajectory)
        
        # 计算系统状态
        system_state = self._assess_system_state(mean_trajectory)
        
        # 计算熵和湍流度
        trajectory_points = [
            TrajectoryPoint(
                timestamp=p["time"],
                values=p["values"]
            ) for p in mean_trajectory
        ]
        entropy = self._calculate_entropy(trajectory_points)
        turbulence_level, _ = self._assess_turbulence(trajectory_points)
        
        now = datetime.now(timezone.utc)
        return PredictionResult(
            project_id="_engine",
            task_id="_engine",
            prediction_time_start=now.isoformat(),
            prediction_time_end=(
                now + timedelta(seconds=horizon_sec)
            ).isoformat(),
            method_used=PredictionMethod.MONTE_CARLO.value,
            trajectory=points,
            confidence_lower=[lower[i]["values"] for i in range(len(lower))],
            confidence_upper=[upper[i]["values"] for i in range(len(upper))],
            anomalies=[{
                "timestamp": a.timestamp.isoformat(),
                "variable": a.variable,
                "value": a.value,
                "threshold": a.threshold,
                "severity": a.severity,
                "description": a.description
            } for a in anomalies],
            system_state=system_state,
            entropy_value=entropy,
            turbulence_level=turbulence_level,
        )
    
    def _compute_mean_trajectory(self, trajectories: list) -> list:
        """计算平均轨迹"""
        if not trajectories:
            return []
        
        n_points = len(trajectories[0])
        n_vars = len(trajectories[0][0]["values"])
        var_names = list(trajectories[0][0]["values"].keys())
        
        mean_traj = []
        for i in range(n_points):
            mean_values = {}
            for var in var_names:
                values = [t[i]["values"][var] for t in trajectories]
                mean_values[var] = np.mean(values)
            
            mean_traj.append({
                "time": trajectories[0][i]["time"],
                "values": mean_values
            })
        
        return mean_traj
    
    def _compute_percentile_bands(
        self,
        trajectories: list,
        lower_pct: float,
        upper_pct: float
    ) -> tuple[list, list]:
        """计算百分位置信带"""
        if not trajectories:
            return [], []
        
        n_points = len(trajectories[0])
        var_names = list(trajectories[0][0]["values"].keys())
        
        lower_bounds = []
        upper_bounds = []
        
        for i in range(n_points):
            lower = {"values": {}}
            upper = {"values": {}}
            
            for var in var_names:
                values = [t[i]["values"][var] for t in trajectories]
                lower["values"][var] = np.percentile(values, lower_pct)
                upper["values"][var] = np.percentile(values, upper_pct)
            
            lower_bounds.append(lower)
            upper_bounds.append(upper)
        
        return lower_bounds, upper_bounds
    
    def _detect_anomalies(self, trajectory: list) -> list[Anomaly]:
        """检测异常点"""
        anomalies = []
        
        for point in trajectory:
            for var, value in point["values"].items():
                # 检查变量范围
                var_def = next(
                    (v for v in self.model.variables if v.name == var),
                    None
                )
                
                if var_def and var_def.range:
                    if var_def.range.get("min") and value < var_def.range["min"]:
                        anomalies.append(Anomaly(
                            timestamp=point["time"],
                            variable=var,
                            value=value,
                            threshold=var_def.range["min"],
                            severity="warning",
                            description=f"{var}低于最小值"
                        ))
                    if var_def.range.get("max") and value > var_def.range["max"]:
                        anomalies.append(Anomaly(
                            timestamp=point["time"],
                            variable=var,
                            value=value,
                            threshold=var_def.range["max"],
                            severity="critical",
                            description=f"{var}超过最大值"
                        ))
        
        return anomalies
    
    def _assess_system_state(self, trajectory: list) -> str:
        """评估系统状态"""
        if not trajectory:
            return "normal"
        
        # 简单逻辑：如果没有异常则为normal
        anomalies = self._detect_anomalies(trajectory)
        
        if any(a.severity == "critical" for a in anomalies):
            return "critical"
        elif anomalies:
            return "warning"
        
        return "normal"


def create_predictor(
    model: SystemModel,
    method: PredictionMethod = PredictionMethod.MONTE_CARLO
) -> Predictor:
    """
    工厂函数：创建预测器
    
    Args:
        model: 系统模型
        method: 预测方法
        
    Returns:
        Predictor: 预测器实例
    """
    if method == PredictionMethod.MONTE_CARLO:
        return MonteCarloPredictor(model)
    elif method == PredictionMethod.KOOPMAN:
        from uap.engine.koopman import KoopmanPredictor
        return KoopmanPredictor(model)
    elif method == PredictionMethod.SIMULATION:
        from uap.engine.simulator import SystemSimulator
        return SystemSimulator(model)
    else:
        return MonteCarloPredictor(model)
