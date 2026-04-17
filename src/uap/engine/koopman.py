"""
Koopman算子预测器实现

基于Koopman算子理论的复杂系统预测方法。
Koopman算子将非线性动力系统提升到无穷维函数空间进行线性表示。
"""

from typing import Optional
import numpy as np

from uap.engine.predictor import Predictor, PredictionMethod
from uap.project.models import SystemModel


class KoopmanPredictor(Predictor):
    """
    Koopman算子预测器
    
    实现基于Koopman算子理论的预测方法。
    
    Koopman算子的核心思想：
    - 原始系统: dx/dt = f(x) (非线性)
    - Koopman系统: g(K) = K(g) (线性算子作用于观测函数)
    
    通过数据驱动方法（如DMD、EDMD）近似Koopman算子，
    然后在提升空间中执行线性预测。
    """
    
    def __init__(
        self,
        model: SystemModel,
        n_lifting_functions: int = 20,
        n_delays: int = 3
    ):
        """
        初始化Koopman预测器
        
        Args:
            model: 系统模型
            n_lifting_functions: 提升函数数量
            n_delays: 时间延迟嵌入维度
        """
        super().__init__(model)
        self.n_lifting_functions = n_lifting_functions
        self.n_delays = n_delays
        
        # Koopman矩阵（将在fit时学习）
        self.K = None
        self.lifting_functions = None
        
        # 状态归一化参数
        self.state_mean = None
        self.state_std = None
    
    def fit(
        self,
        training_trajectories: list[dict],
        method: str = "dmd"
    ):
        """
        从训练轨迹学习Koopman算子
        
        Args:
            training_trajectories: 训练轨迹数据
            method: 学习方法 ("dmd" | "edmd")
        """
        if method == "dmd":
            self._fit_dmd(training_trajectories)
        elif method == "edmd":
            self._fit_edmd(training_trajectories)
        else:
            self._fit_dmd(training_trajectories)
    
    def _fit_dmd(self, trajectories: list[dict]):
        """
        动态模态分解(DMD)方法
        
        DMD是一种数据驱动的矩阵分解方法，
        可以从高维数据中提取低维动力学特征。
        """
        # 收集所有状态快照
        X = []
        Y = []
        
        for traj in trajectories:
            states = traj.get("states", [])
            for i in range(len(states) - 1):
                x = self._state_to_vector(states[i])
                y = self._state_to_vector(states[i + 1])
                X.append(x)
                Y.append(y)
        
        if len(X) < 10:
            # 数据不足，使用简化的单位矩阵
            n = len(X[0]) if X else self._get_state_dim()
            self.K = np.eye(n)
            return
        
        X = np.array(X)
        Y = np.array(Y)
        
        # 归一化
        self.state_mean = np.mean(X, axis=0)
        self.state_std = np.std(X, axis=0) + 1e-8
        X_norm = (X - self.state_mean) / self.state_std
        Y_norm = (Y - self.state_mean) / self.state_std
        
        # DMD: X^+ = A X
        # 最小二乘求解 A = Y X^+ = Y X^T (XX^T)^-1
        XTX = X_norm.T @ X_norm
        XTY = Y_norm.T @ X_norm
        
        # 加正则化防止奇异
        XTX += 0.01 * np.eye(XTX.shape[0])
        
        self.K = XTY @ np.linalg.inv(XTX)
        
        # 简化处理：返回状态均值偏移
        self.K = self.K @ np.diag(1.0 / self.state_std) @ np.diag(self.state_std)
    
    def _fit_edmd(self, trajectories: list[dict]):
        """
        扩展动态模态分解(EDMD)方法
        
        EDMD使用提升函数将状态映射到高维特征空间，
        然后在特征空间中执行DMD。
        """
        # 使用多项式提升函数
        self._init_lifting_functions()
        
        X = []
        Y = []
        
        for traj in trajectories:
            states = traj.get("states", [])
            for i in range(len(states) - 1):
                x = self._lift(self._state_to_vector(states[i]))
                y = self._lift(self._state_to_vector(states[i + 1]))
                X.append(x)
                Y.append(y)
        
        if len(X) < 10:
            n = self.n_lifting_functions
            self.K = np.eye(n)
            return
        
        X = np.array(X)
        Y = np.array(Y)
        
        # 同样求解 A
        XTX = X.T @ X
        XTY = Y.T @ X
        XTX += 0.01 * np.eye(XTX.shape[0])
        
        self.K = XTY @ np.linalg.inv(XTX)
    
    def _init_lifting_functions(self):
        """初始化提升函数"""
        n_vars = self._get_state_dim()
        
        # 创建简单的多项式提升函数
        def lifting_fn(x):
            features = list(x)  # 原始状态
            
            # 添加二次项
            for i in range(n_vars):
                for j in range(i, n_vars):
                    features.append(x[i] * x[j])
            
            # 添加一些非线性项
            for i in range(n_vars):
                features.append(np.sin(x[i]))
                features.append(np.cos(x[i]))
            
            return np.array(features[:self.n_lifting_functions])
        
        self.lifting_functions = lifting_fn
    
    def _lift(self, x: np.ndarray) -> np.ndarray:
        """将状态提升到特征空间"""
        if self.lifting_functions is not None:
            return self.lifting_functions(x)
        
        # 默认：使用状态本身
        return x
    
    def _get_state_dim(self) -> int:
        """获取状态维度"""
        return len(self.model.variables) if self.model.variables else 1
    
    def _state_to_vector(self, state: dict) -> np.ndarray:
        """将状态字典转换为向量"""
        if isinstance(state, dict):
            return np.array([state.get(v.name, 0.0) for v in self.model.variables])
        return np.array(state)
    
    def _vector_to_state(self, vec: np.ndarray) -> dict:
        """将向量转换回状态字典"""
        return {
            v.name: vec[i] if i < len(vec) else 0.0
            for i, v in enumerate(self.model.variables)
        }
    
    def predict(
        self,
        initial_state: dict[str, float],
        horizon_sec: int,
        frequency_sec: int,
    ) -> "PredictionResult":
        """
        使用Koopman算子执行预测
        
        Args:
            initial_state: 初始状态
            horizon_sec: 预测时长
            frequency_sec: 输出频率
            
        Returns:
            PredictionResult: 预测结果
        """
        from datetime import datetime, timedelta, timezone
        from uap.project.models import PredictionResult as PR
        
        # 如果没有训练过，使用简化的线性外推
        if self.K is None:
            return self._predict_linear(initial_state, horizon_sec, frequency_sec)
        
        # 构建轨迹
        trajectory = []
        confidence_lower = []
        confidence_upper = []
        
        current_vec = self._state_to_vector(initial_state)
        current_time = datetime.now()
        
        num_steps = horizon_sec // frequency_sec
        
        for step in range(num_steps):
            # 记录当前点
            state_dict = self._vector_to_state(current_vec)
            trajectory.append({
                "timestamp": current_time.isoformat(),
                "values": state_dict
            })
            
            # Koopman预测: x_{k+1} = K x_k
            # 简化处理：直接用K更新
            try:
                next_vec = self.K @ current_vec
                
                # 确保数值稳定
                next_vec = np.clip(next_vec, -1e6, 1e6)
            except:
                # 如果矩阵乘法失败，使用线性外推
                next_vec = current_vec * 1.01
            
            current_vec = next_vec
            current_time += timedelta(seconds=frequency_sec)
            
            # 计算置信区间（基于预测的不确定性传播）
            uncertainty = 0.05 * step  # 简化的不确定性估计
            lower = {k: v * (1 - uncertainty) for k, v in state_dict.items()}
            upper = {k: v * (1 + uncertainty) for k, v in state_dict.items()}
            confidence_lower.append(lower)
            confidence_upper.append(upper)
        
# 检测异常
        anomalies = self._detect_anomalies(trajectory)
        
        # 评估系统状态
        system_state = self._assess_system_state(trajectory)
        
        now = datetime.now(timezone.utc)
        return PR(
            project_id="_engine",
            task_id="_engine",
            prediction_time_start=now.isoformat(),
            prediction_time_end=(
                now + timedelta(seconds=horizon_sec)
            ).isoformat(),
            method_used=PredictionMethod.KOOPMAN.value,
            trajectory=trajectory,
            confidence_lower=confidence_lower,
            confidence_upper=confidence_upper,
            anomalies=anomalies,
            system_state=system_state,
            entropy_value=self._estimate_entropy(trajectory),
            turbulence_level=self._estimate_turbulence(trajectory),
        )
    
    def _predict_linear(
        self,
        initial_state: dict,
        horizon_sec: int,
        frequency_sec: int
    ):
        """简化的线性外推预测"""
        from datetime import datetime, timedelta, timezone
        from uap.project.models import PredictionResult as PR
        
        trajectory = []
        confidence_lower = []
        confidence_upper = []
        
        current_state = initial_state.copy()
        current_time = datetime.now()
        
        # 从模型关系中推断变化趋势
        growth_rates = self._infer_growth_rates()
        
        num_steps = horizon_sec // frequency_sec
        
        for step in range(num_steps):
            trajectory.append({
                "timestamp": current_time.isoformat(),
                "values": current_state.copy()
            })
            
            # 线性外推
            dt = frequency_sec / 3600.0  # 转换为小时单位
            for var in current_state:
                rate = growth_rates.get(var, 0.01)  # 默认1%增长率
                current_state[var] *= (1 + rate * dt)
            
            current_time += timedelta(seconds=frequency_sec)
            
            # 简化置信区间
            uncertainty = 0.03 * step
            confidence_lower.append({
                k: v * (1 - uncertainty) for k, v in current_state.items()
            })
            confidence_upper.append({
                k: v * (1 + uncertainty) for k, v in current_state.items()
            })
        
        anomalies = self._detect_anomalies(trajectory)
        system_state = self._assess_system_state(trajectory)
        
        now = datetime.now(timezone.utc)
        return PR(
            project_id="_engine",
            task_id="_engine",
            prediction_time_start=now.isoformat(),
            prediction_time_end=(
                now + timedelta(seconds=horizon_sec)
            ).isoformat(),
            method_used=PredictionMethod.KOOPMAN.value,
            trajectory=trajectory,
            confidence_lower=confidence_lower,
            confidence_upper=confidence_upper,
            anomalies=anomalies,
            system_state=system_state,
            entropy_value=self._estimate_entropy(trajectory),
            turbulence_level=self._estimate_turbulence(trajectory),
        )
    
    def _infer_growth_rates(self) -> dict:
        """从模型关系中推断变量的增长率"""
        rates = {}
        
        for relation in self.model.relations:
            if relation.type in ["differential", "causal"]:
                # 从因果关系推断
                if relation.expression:
                    # 简单解析微分形式
                    if "d" in relation.expression or "'" in relation.expression:
                        rates[relation.to_var] = 0.01  # 默认增长率
        
        # 如果没有找到，给默认值
        for var in self.model.variables:
            if var.name not in rates:
                rates[var.name] = 0.005
        
        return rates
    
    def _detect_anomalies(self, trajectory: list) -> list:
        """检测轨迹中的异常"""
        anomalies = []
        
        for point in trajectory:
            for var, value in point["values"].items():
                var_def = next(
                    (v for v in self.model.variables if v.name == var),
                    None
                )
                
                if var_def and var_def.bounds_max is not None:
                    vmax = var_def.bounds_max
                    if value > vmax:
                        anomalies.append({
                            "timestamp": point["timestamp"],
                            "variable": var,
                            "value": value,
                            "threshold": vmax,
                            "severity": "critical" if value > vmax * 1.1 else "warning",
                            "description": f"{var}超过最大值",
                        })
        
        return anomalies
    
    def _assess_system_state(self, trajectory: list) -> str:
        """评估系统状态"""
        anomalies = self._detect_anomalies(trajectory)
        
        if any(a.get("severity") == "critical" for a in anomalies):
            return "critical"
        elif anomalies:
            return "warning"
        return "normal"
    
    def _estimate_entropy(self, trajectory: list) -> float:
        """估计轨迹的熵"""
        if len(trajectory) < 2:
            return 0.0
        
        # 简化的熵估计
        changes = []
        for i in range(1, len(trajectory)):
            prev = trajectory[i-1]["values"]
            curr = trajectory[i]["values"]
            diff = sum(abs(curr[k] - prev.get(k, 0)) for k in curr)
            changes.append(diff)
        
        if not changes:
            return 0.0
        
        # 基于变化率的熵
        import numpy as np
        changes = np.array(changes)
        mean_change = np.mean(changes)
        std_change = np.std(changes)
        
        # 熵与变化的不确定性成正比
        return float(std_change / (mean_change + 1e-6))
    
    def _estimate_turbulence(self, trajectory: list) -> str:
        """估计湍流程度"""
        if len(trajectory) < 3:
            return "laminar"
        
        import numpy as np
        
        changes = []
        for i in range(1, len(trajectory)):
            prev = list(trajectory[i-1]["values"].values())
            curr = list(trajectory[i]["values"].values())
            if len(prev) == len(curr) and len(prev) > 0:
                diff = np.mean(np.abs(np.array(curr) - np.array(prev)))
                changes.append(diff)
        
        if not changes:
            return "laminar"
        
        changes = np.array(changes)
        cv = np.std(changes) / (np.mean(changes) + 1e-6)
        
        if cv < 0.1:
            return "laminar"
        elif cv < 0.5:
            return "transition"
        return "turbulent"
