"""
UAP 卡片生成器

根据当前上下文自动生成确认卡片。
参考 Chimera 的卡片机制，但保持本地优先设计。
"""

import uuid
from datetime import datetime, timedelta
from typing import Optional

from uap.card.models import (
    CardType,
    CardPriority,
    CardOption,
    ConfirmationCard,
    CardContext
)


class CardGenerator:
    """卡片生成器"""
    
    def __init__(self):
        pass
    
    def _generate_card_id(self) -> str:
        """生成唯一卡片ID"""
        return f"card_{uuid.uuid4().hex[:12]}"
    
    # ==================== 建模相关卡片 ====================
    
    def generate_model_confirm_card(
        self,
        context: CardContext,
        variables: list[dict],
        relations: list[dict],
        constraints: list[dict]
    ) -> ConfirmationCard:
        """
        生成模型确认卡片
        在模型提取完成后，让用户确认模型定义
        """
        content = "我从您的描述中提取了以下系统模型，请确认是否正确：\n\n"
        
        content += "**📊 变量定义**\n"
        for v in variables:
            content += f"- `{v.get('name', 'unknown')}` ({v.get('type', 'continuous')})"
            if v.get('description'):
                content += f": {v['description']}"
            content += "\n"
        
        content += "\n**🔗 关系定义**\n"
        for r in relations:
            content += f"- `{r.get('from_var', '?')}` → `{r.get('to_var', '?')}`"
            if r.get('expression'):
                content += f": {r['expression']}"
            content += "\n"
        
        if constraints:
            content += "\n**⚠️ 约束条件**\n"
            for c in constraints:
                content += f"- {c.get('expression', c.get('description', 'constraint'))}\n"
        
        return ConfirmationCard(
            card_id=self._generate_card_id(),
            card_type=CardType.MODEL_CONFIRM,
            title="📋 系统模型确认",
            content=content,
            options=[
                CardOption(
                    id="confirm",
                    label="✅ 确认模型正确",
                    description="继续使用此模型进行预测"
                ),
                CardOption(
                    id="modify",
                    label="🔧 需要修改",
                    description="指出需要修改的部分"
                ),
                CardOption(
                    id="discard",
                    label="❌ 放弃此模型",
                    description="重新描述系统"
                )
            ],
            priority=CardPriority.HIGH,
            default_option_id="confirm",
            context={
                "variables": variables,
                "relations": relations,
                "constraints": constraints,
                **context.to_dict()
            },
            icon="📋"
        )
    
    def generate_variable_selection_card(
        self,
        context: CardContext,
        detected_variables: list[dict],
        recommended_variables: list[str]
    ) -> ConfirmationCard:
        """生成变量选择卡片"""
        content = "我发现了以下可能的变量，请选择要包含在模型中的变量：\n\n"
        
        options = []
        for v in detected_variables:
            v_name = v.get('name', 'unknown')
            is_recommended = v_name in recommended_variables
            options.append(CardOption(
                id=v_name,
                label=f"{'⭐ ' if is_recommended else ''}{v_name}",
                description=v.get('description', ''),
                metadata={"recommended": is_recommended, "variable": v}
            ))
        
        return ConfirmationCard(
            card_id=self._generate_card_id(),
            card_type=CardType.VARIABLE_SELECTION,
            title="🔢 变量选择",
            content=content,
            options=options,
            priority=CardPriority.HIGH,
            context={"detected_variables": detected_variables, **context.to_dict()},
            icon="🔢"
        )
    
    # ==================== 预测相关卡片 ====================
    
    def generate_prediction_method_card(
        self,
        context: CardContext,
        available_methods: list[dict]
    ) -> ConfirmationCard:
        """
        生成预测方法推荐卡片
        根据系统特性和数据情况推荐合适的预测方法
        """
        content = "针对您的系统，我推荐以下预测方法：\n\n"
        
        options = []
        for method in available_methods:
            pros = method.get('pros', [])
            cons = method.get('cons', [])
            
            desc = f"适用场景：{method.get('applicable_for', '通用')}\n"
            if pros:
                desc += f"优点：{', '.join(pros)}\n"
            if cons:
                desc += f"注意：{', '.join(cons)}"
            
            options.append(CardOption(
                id=method['id'],
                label=f"{method['icon']} {method['name']}",
                description=desc.strip(),
                metadata=method
            ))
            content += f"**{method['icon']} {method['name']}**: {method.get('description', '')}\n\n"
        
        return ConfirmationCard(
            card_id=self._generate_card_id(),
            card_type=CardType.METHOD_RECOMMENDATION,
            title="🧠 预测方法选择",
            content=content,
            options=options,
            priority=CardPriority.HIGH,
            default_option_id=available_methods[0]['id'] if available_methods else None,
            context={
                "methods": available_methods,
                **context.to_dict()
            },
            icon="🧠"
        )
    
    def generate_prediction_execution_card(
        self,
        context: CardContext,
        method_name: str,
        horizon: int,
        frequency: int
    ) -> ConfirmationCard:
        """生成预测执行确认卡片"""
        horizon_hours = horizon / 3600
        frequency_minutes = frequency / 60
        
        content = f"""即将执行预测任务：

- **预测方法**: {method_name}
- **预测时长**: 未来 {horizon_hours:.0f} 小时
- **预测频率**: 每 {frequency_minutes:.0f} 分钟
- **预计耗时**: 约 30-60 秒
"""
        if context.estimated_time:
            content += f"- **任务运行时长**: 约 {context.estimated_time} 秒\n"
        
        return ConfirmationCard(
            card_id=self._generate_card_id(),
            card_type=CardType.PREDICTION_EXECUTION,
            title="🚀 确认执行预测",
            content=content,
            options=[
                CardOption(
                    id="execute",
                    label="▶️ 开始预测",
                    description="立即执行预测任务"
                ),
                CardOption(
                    id="schedule",
                    label="⏰ 定时执行",
                    description="设置定时预测任务"
                ),
                CardOption(
                    id="cancel",
                    label="❌ 取消",
                    description="暂时不执行"
                )
            ],
            priority=CardPriority.NORMAL,
            default_option_id="execute",
            context=context.to_dict(),
            icon="🚀"
        )
    
    # ==================== 技能相关卡片 ====================
    
    def generate_skill_selection_card(
        self,
        context: CardContext,
        available_skills: list[dict],
        recommended_skill_ids: list[str]
    ) -> ConfirmationCard:
        """生成技能选择卡片"""
        content = "根据当前任务，我找到了以下可用的技能：\n\n"
        
        options = []
        for skill in available_skills:
            skill_id = skill['skill_id']
            is_recommended = skill_id in recommended_skill_ids
            
            desc = f"分类：{skill.get('category', 'general')}\n"
            if skill.get('estimated_time'):
                desc += f"预计耗时：{skill['estimated_time']}秒\n"
            desc += skill.get('description', '')
            
            options.append(CardOption(
                id=skill_id,
                label=f"{'⭐ ' if is_recommended else ''}{skill.get('name', skill_id)}",
                description=desc.strip(),
                metadata=skill
            ))
        
        return ConfirmationCard(
            card_id=self._generate_card_id(),
            card_type=CardType.SKILL_SELECTION,
            title="🛠️ 选择执行技能",
            content=content,
            options=options,
            priority=CardPriority.NORMAL,
            context={
                "skills": available_skills,
                "recommended": recommended_skill_ids,
                **context.to_dict()
            },
            icon="🛠️"
        )
    
    def generate_skill_save_prompt_card(
        self,
        context: CardContext,
        task_summary: str,
        skill_metrics: Optional[dict] = None
    ) -> ConfirmationCard:
        """生成技能保存提示卡片"""
        content = f"任务执行完成！\n\n**任务摘要**: {task_summary}\n"
        
        if skill_metrics:
            content += "\n**性能指标**:\n"
            for key, value in skill_metrics.items():
                content += f"- {key}: {value}\n"
        
        content += "\n是否将此任务保存为可复用的技能？"
        
        return ConfirmationCard(
            card_id=self._generate_card_id(),
            card_type=CardType.SKILL_SAVE_PROMPT,
            title="💾 保存技能",
            content=content,
            options=[
                CardOption(
                    id="save",
                    label="💾 保存为技能",
                    description="保存技能链和配置，供以后复用"
                ),
                CardOption(
                    id="save_with_model",
                    label="💾💾 保存（含训练模型）",
                    description="保存技能和训练好的模型（占用更多空间）"
                ),
                CardOption(
                    id="discard",
                    label="🚫 不保存",
                    description="仅保留本次结果"
                )
            ],
            priority=CardPriority.LOW,
            context=context.to_dict(),
            icon="💾"
        )
    
    # ==================== 高风险操作卡片 ====================
    
    def generate_high_risk_confirm_card(
        self,
        context: CardContext,
        action: str,
        risk_description: str,
        warning_text: str
    ) -> ConfirmationCard:
        """生成高风险操作确认卡片"""
        return ConfirmationCard(
            card_id=self._generate_card_id(),
            card_type=CardType.HIGH_RISK_CONFIRM,
            title="⚠️ 高风险操作确认",
            content=f"**操作**: {action}\n\n**风险说明**: {risk_description}\n\n**警告**: {warning_text}",
            options=[
                CardOption(
                    id="proceed",
                    label="⚠️ 确认执行",
                    description="我了解风险，继续执行"
                ),
                CardOption(
                    id="cancel",
                    label="🛑 取消操作",
                    description="放弃此操作"
                )
            ],
            priority=CardPriority.CRITICAL,
            default_option_id="cancel",
            context=context.to_dict(),
            icon="⚠️"
        )
    
    def generate_long_operation_warning_card(
        self,
        context: CardContext,
        operation: str,
        estimated_time: int
    ) -> ConfirmationCard:
        """生成长时间操作警告卡片"""
        minutes = estimated_time // 60
        seconds = estimated_time % 60
        time_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
        
        content = f"""🔔 此操作预计需要较长时间：

- **操作**: {operation}
- **预计耗时**: {time_str}

请确认是否继续？"""
        
        return ConfirmationCard(
            card_id=self._generate_card_id(),
            card_type=CardType.LONG_OPERATION_WARNING,
            title="⏱️ 长时间操作",
            content=content,
            options=[
                CardOption(
                    id="proceed",
                    label="▶️ 继续执行",
                    description="开始执行，可能需要等待"
                ),
                CardOption(
                    id="cancel",
                    label="❌ 稍后再说",
                    description="取消，稍后再执行"
                )
            ],
            priority=CardPriority.NORMAL,
            context={"estimated_time": estimated_time, **context.to_dict()},
            icon="⏱️"
        )
    
    # ==================== 工具方法 ====================
    
    def get_default_prediction_methods(self) -> list[dict]:
        """获取默认的预测方法列表"""
        return [
            {
                "id": "koopman",
                "name": "Koopman 算子",
                "icon": "🔄",
                "description": "基于动力学系统的Koopman算子理论，适合分析非线性系统的全局行为",
                "applicable_for": "非线性系统、混沌系统",
                "pros": ["可解释性强", "适合分析不确定性", "训练较快"],
                "cons": ["需要足够的观测数据"],
                "estimated_time": 30
            },
            {
                "id": "monte_carlo",
                "name": "Monte Carlo 模拟",
                "icon": "🎲",
                "description": "通过大量随机采样估计系统未来状态的概率分布",
                "applicable_for": "随机系统、不确定性量化",
                "pros": ["易于实现", "可并行计算", "结果直观"],
                "cons": ["计算量大", "精度依赖采样数"],
                "estimated_time": 60
            },
            {
                "id": "neural_ode",
                "name": "Neural ODE",
                "icon": "🧠",
                "description": "神经常微分方程，用神经网络建模连续时间动力学",
                "applicable_for": "连续时间系统、复杂非线性",
                "pros": ["精度高", "可处理不规则采样"],
                "cons": ["训练较慢", "需要调参"],
                "estimated_time": 120
            },
            {
                "id": "pinn",
                "name": "物理信息神经网络",
                "icon": "⚡",
                "description": "将物理定律作为约束注入神经网络",
                "applicable_for": "有明确物理规律的系统",
                "pros": ["可解释性好", "样本效率高"],
                "cons": ["需要指定物理方程", "实现复杂"],
                "estimated_time": 180
            }
        ]
