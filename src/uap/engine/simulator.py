"""
系统模拟器

基于规则的系统模拟器，用于简单的数值预测。
"""

from datetime import datetime, timedelta, timezone
import numpy as np

from uap.engine.predictor import Predictor, PredictionMethod
from uap.project.models import SystemModel


class SystemSimulator(Predictor):
    """
    系统模拟器
    
    基于规则的简单数值模拟器。
    适用于：
    - 规则明确的确定性系统
    - 快速原型验证
    - 教学演示
    """
    
    def __init__(self, model: SystemModel):
        """
        初始化系统模拟器
        
        Args:
            model: 系统模型
        """
        super().__init__(model)
        
        # 解析系统方程
        self._parse_equations()
    
    def _parse_equations(self):
        """解析模型中的关系表达式"""
        self.equations = {}
        
        for relation in self.model.relations:
            if relation.expression:
                # 存储表达式和类型
                self.equations[relation.to_var] = {
                    "expression": relation.expression,
                    "type": relation.type,
                    "from_var": relation.from_var
                }
    
    def predict(
        self,
        initial_state: dict[str, float],
        horizon_sec: int,
        frequency_sec: int,
    ) -> "PredictionResult":
        """
        执行数值模拟预测
        
        Args:
            initial_state: 初始状态
            horizon_sec: 预测时长
            frequency_sec: 输出频率
            
        Returns:
            PredictionResult: 模拟结果
        """
        from uap.project.models import PredictionResult as PR
        
        trajectory = []
        confidence_lower = []
        confidence_upper = []
        
        current_state = initial_state.copy()
        current_time = datetime.now()
        
        num_steps = horizon_sec // frequency_sec
        
        # 简化的时间步长（秒转小时用于某些方程）
        dt = frequency_sec / 3600.0
        
        for step in range(num_steps):
            # 记录当前状态
            trajectory.append({
                "timestamp": current_time.isoformat(),
                "values": current_state.copy()
            })
            
            # 计算下一步状态
            next_state = self._step(current_state, dt)
            current_state = next_state
            
            current_time += timedelta(seconds=frequency_sec)
            
            # 简化置信区间（确定性模拟，区间很小）
            uncertainty = 0.001 * step  # 随时间略微增加
            confidence_lower.append({
                k: v * (1 - uncertainty) for k, v in current_state.items()
            })
            confidence_upper.append({
                k: v * (1 + uncertainty) for k, v in current_state.items()
            })
        
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
            method_used=PredictionMethod.SIMULATION.value,
            trajectory=trajectory,
            confidence_lower=confidence_lower,
            confidence_upper=confidence_upper,
            anomalies=anomalies,
            system_state=system_state,
            entropy_value=self._calculate_entropy(trajectory),
            turbulence_level=self._calculate_turbulence(trajectory),
        )
    
    def _step(self, state: dict, dt: float) -> dict:
        """
        执行一步模拟
        
        Args:
            state: 当前状态
            dt: 时间步长
            
        Returns:
            dict: 下一时刻状态
        """
        next_state = state.copy()
        
        # 首先处理微分方程
        for var_name, eq_info in self.equations.items():
            if eq_info["type"] == "differential":
                # 计算导数
                derivative = self._compute_derivative(eq_info, state)
                if var_name in next_state:
                    next_state[var_name] += derivative * dt
            
            elif eq_info["type"] == "equation":
                # 代数方程，直接计算
                value = self._compute_equation(eq_info, state)
                next_state[var_name] = value
        
        # 检查约束
        for constraint in self.model.constraints:
            if constraint.type == "range":
                # 应用约束
                for var in next_state:
                    if "min" in constraint.expression.lower():
                        # 提取最小值
                        import re
                        match = re.search(r'min[:\s=]*(\d+\.?\d*)', constraint.expression)
                        if match:
                            min_val = float(match.group(1))
                            next_state[var] = max(next_state.get(var, 0), min_val)
                    
                    if "max" in constraint.expression.lower():
                        import re
                        match = re.search(r'max[:\s=]*(\d+\.?\d*)', constraint.expression)
                        if match:
                            max_val = float(match.group(1))
                            next_state[var] = min(next_state.get(var, 0), max_val)
        
        return next_state
    
    def _compute_derivative(self, eq_info: dict, state: dict) -> float:
        """
        计算导数值
        
        Args:
            eq_info: 方程信息
            state: 当前状态
            
        Returns:
            float: 导数值
        """
        expr = eq_info["expression"]
        from_var = eq_info["from_var"]
        
        # 获取相关变量值
        from_value = state.get(from_var, 0.0)
        
        # 简化的导数计算
        # 支持格式: "dx/dt = k*x" 或 "dx/dt = k"
        
        import re
        
        # 提取等号右边的表达式
        match = re.search(r'=\s*(.+)', expr)
        if not match:
            return 0.0
        
        right_side = match.group(1).strip()
        
        # 简单替换变量
        for var_name, var_value in state.items():
            right_side = right_side.replace(var_name, str(var_value))
        
        # 计算表达式
        try:
            # 安全计算（只支持基本数学运算）
            result = eval(right_side, {"__builtins__": {}}, {
                "sin": np.sin,
                "cos": np.cos,
                "exp": np.exp,
                "log": np.log,
                "sqrt": np.sqrt,
                "abs": abs,
                "pi": np.pi,
                "e": np.e
            })
            return float(result)
        except:
            # 如果计算失败，返回默认值
            return 0.0
    
    def _compute_equation(self, eq_info: dict, state: dict) -> float:
        """
        计算代数方程
        
        Args:
            eq_info: 方程信息
            state: 当前状态
            
        Returns:
            float: 计算结果
        """
        return self._compute_derivative(eq_info, state)
    
    def _detect_anomalies(self, trajectory: list) -> list:
        """检测异常"""
        anomalies = []
        
        for point in trajectory:
            for var, value in point["values"].items():
                var_def = next(
                    (v for v in self.model.variables if v.name == var),
                    None
                )
                
                if var_def and var_def.range:
                    if var_def.range.get("min") and value < var_def.range["min"]:
                        anomalies.append({
                            "timestamp": point["timestamp"],
                            "variable": var,
                            "value": value,
                            "threshold": var_def.range["min"],
                            "severity": "warning",
                            "description": f"{var}低于最小值"
                        })
                    
                    if var_def.range.get("max") and value > var_def.range["max"]:
                        anomalies.append({
                            "timestamp": point["timestamp"],
                            "variable": var,
                            "value": value,
                            "threshold": var_def.range["max"],
                            "severity": "critical" if value > var_def.range["max"] * 1.1 else "warning",
                            "description": f"{var}超过最大值"
                        })
                
                # 检查NaN和Inf
                if not np.isfinite(value):
                    anomalies.append({
                        "timestamp": point["timestamp"],
                        "variable": var,
                        "value": value,
                        "threshold": 0,
                        "severity": "critical",
                        "description": f"{var}值为非有限数"
                    })
        
        return anomalies
    
    def _assess_system_state(self, trajectory: list) -> str:
        """评估系统状态"""
        anomalies = self._detect_anomalies(trajectory)
        
        # 检查是否有NaN/Inf
        for point in trajectory:
            for value in point["values"].values():
                if not np.isfinite(value):
                    return "critical"
        
        if any(a.get("severity") == "critical" for a in anomalies):
            return "critical"
        elif anomalies:
            return "warning"
        return "normal"
    
    def _calculate_entropy(self, trajectory: list) -> float:
        """计算熵"""
        if len(trajectory) < 2:
            return 0.0
        
        changes = []
        for i in range(1, len(trajectory)):
            prev = trajectory[i-1]["values"]
            curr = trajectory[i]["values"]
            diff = sum(abs(curr[k] - prev.get(k, 0)) for k in curr)
            changes.append(diff)
        
        if not changes:
            return 0.0
        
        changes = np.array(changes)
        return float(np.std(changes) / (np.mean(changes) + 1e-6))
    
    def _calculate_turbulence(self, trajectory: list) -> str:
        """计算湍流程度"""
        if len(trajectory) < 3:
            return "laminar"
        
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
        
        if cv < 0.05:
            return "laminar"
        elif cv < 0.2:
            return "transition"
        return "turbulent"
