"""
ReactCardIntegration —— **HITL（人在环）Harness**：把 ReAct 输出接到卡片系统
================================================================================

与 **行动模式**：在 ReAct 产出待确认结构化结果（变量/关系列表）后，由本模块生成
``ConfirmationCard``，阻塞或异步等待用户选择，再把结果反馈给后续轮次（扩展点）。

与 **提示词工程**：卡片标题/选项文案即面向用户的「微型提示」；与 LLM 系统提示词
应语义一致，避免用户看到与模型描述冲突的选项。

与 **记忆**：卡片历史可由 ``CardManager`` 查询，用于审计与再训练数据抽取。
================================================================================
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Optional

from uap.card.models import (
    CardType,
    CardContext,
    ConfirmationCard,
    CardOption,
    CardPriority,
)
from uap.card.manager import CardManager

_LOG = logging.getLogger("uap.core.action.react.card_integration")


class ReactCardIntegration:
    """
    ReAct与卡片系统集成

    职责：
    1. 将ReAct中的待确认项转换为卡片
    2. 处理卡片响应并继续ReAct循环
    3. 管理卡片与会话的关联
    """

    def __init__(self, card_manager: CardManager):
        """
        初始化集成器

        Args:
            card_manager: 卡片管理器
        """
        self.card_manager = card_manager

    def create_confirmation_card(
        self,
        session_id: str,
        project_id: str,
        confirm_type: str,
        title: str,
        content: str,
        options: list[dict],
        context: dict = None,
        priority: str = "normal"
    ) -> str:
        """
        创建确认卡片

        Args:
            session_id: 会话ID
            project_id: 项目ID
            confirm_type: 确认类型
            title: 卡片标题
            content: 卡片内容
            options: 选项列表 [{"id": str, "label": str, "description": str}]
            context: 额外上下文
            priority: 优先级

        Returns:
            card_id: 卡片ID
        """
        card_id = str(uuid.uuid4())

        # 映射确认类型到卡片类型
        card_type_map = {
            "variable_confirm": CardType.VARIABLE_SELECTION,
            "relation_confirm": CardType.RELATION_CLARIFICATION,
            "model_confirm": CardType.MODEL_CONFIRM,
            "method_recommend": CardType.METHOD_RECOMMENDATION,
            "prediction_exec": CardType.PREDICTION_EXECUTION,
            "skill_select": CardType.SKILL_SELECTION,
            "general": CardType.MODEL_CONFIRM,
        }

        card_type = card_type_map.get(confirm_type, CardType.MODEL_CONFIRM)
        priority_enum = CardPriority(priority)

        # 构建选项
        card_options = []
        for opt in options:
            card_options.append(CardOption(
                id=opt.get("id", str(uuid.uuid4())),
                label=opt.get("label", ""),
                description=opt.get("description"),
                metadata=opt.get("metadata", {})
            ))

        # 如果没有提供默认选项，添加"继续"和"取消"
        if not card_options:
            card_options = [
                CardOption(id="proceed", label="继续", description="继续执行当前方案"),
                CardOption(id="cancel", label="取消", description="取消当前操作"),
            ]

        card_context = CardContext(
            project_id=project_id,
            session_id=session_id,
        )
        if context:
            card_context.metadata = context

        card = ConfirmationCard(
            card_id=card_id,
            card_type=card_type,
            title=title,
            content=content,
            options=card_options,
            priority=priority_enum,
            context=card_context.to_dict(),
            icon=self._get_icon_for_type(confirm_type)
        )

        self.card_manager.create_card(card)
        _LOG.info("[ReactCardIntegration] Created card: type=%s, title=%s, options=%d",
                  card_type, title, len(card_options))

        return card_id

    def create_model_confirm_card(
        self,
        session_id: str,
        project_id: str,
        variables: list[dict],
        relations: list[dict],
        constraints: list[dict]
    ) -> str:
        """
        创建模型确认卡片

        Args:
            session_id: 会话ID
            project_id: 项目ID
            variables: 变量列表
            relations: 关系列表
            constraints: 约束列表

        Returns:
            card_id: 卡片ID
        """
        # 构建卡片内容
        content = "## 已识别的系统模型\n\n"

        if variables:
            content += "### 变量\n"
            for var in variables:
                name = var.get("name", "未命名")
                desc = var.get("description", "")
                unit = var.get("unit", "")
                content += f"- **{name}**"
                if unit:
                    content += f" ({unit})"
                if desc:
                    content += f": {desc}"
                content += "\n"
            content += "\n"

        if relations:
            content += "### 关系\n"
            for rel in relations:
                name = rel.get("name", "未命名")
                desc = rel.get("description", "")
                content += f"- **{name}**: {desc}\n"
            content += "\n"

        if constraints:
            content += "### 约束\n"
            for con in constraints:
                desc = con.get("description", str(con))
                content += f"- {desc}\n"

        options = [
            {"id": "confirm", "label": "确认模型", "description": "模型正确，继续下一步"},
            {"id": "edit", "label": "修改模型", "description": "需要添加或修改模型元素"},
            {"id": "cancel", "label": "取消建模", "description": "放弃当前建模结果"},
        ]

        return self.create_confirmation_card(
            session_id=session_id,
            project_id=project_id,
            confirm_type="model_confirm",
            title="系统模型确认",
            content=content,
            options=options,
            context={"variables": variables, "relations": relations, "constraints": constraints},
            priority="high"
        )

    def create_variable_confirm_card(
        self,
        session_id: str,
        project_id: str,
        variable: dict,
        existing_variables: list[dict]
    ) -> str:
        """
        创建变量确认卡片

        Args:
            session_id: 会话ID
            project_id: 项目ID
            variable: 待确认的变量
            existing_variables: 已存在的变量

        Returns:
            card_id: 卡片ID
        """
        var_name = variable.get("name", "未命名")
        var_type = variable.get("type", variable.get("value_type", "float"))
        var_desc = variable.get("description", "")
        var_unit = variable.get("unit", "")

        content = f"""## 变量确认

已识别新变量: **{var_name}**

- 类型: {var_type}
- 单位: {var_unit or '无'}
- 描述: {var_desc or '无'}

"""
        if existing_variables:
            content += "### 已有变量\n"
            for v in existing_variables[:5]:
                content += f"- {v.get('name', '?')}: {v.get('description', '')}\n"

        # 检查是否可能重复
        is_duplicate = any(v.get("name") == var_name for v in existing_variables)

        options = []
        if is_duplicate:
            options = [
                {"id": "merge", "label": "合并", "description": "与现有变量合并"},
                {"id": "rename", "label": "重命名", "description": "使用新名称"},
                {"id": "cancel", "label": "取消", "description": "不使用此变量"},
            ]
        else:
            options = [
                {"id": "confirm", "label": "确认添加", "description": "将此变量添加到模型"},
                {"id": "edit", "label": "修改", "description": "修改变量属性"},
                {"id": "skip", "label": "跳过", "description": "暂时不添加"},
            ]

        return self.create_confirmation_card(
            session_id=session_id,
            project_id=project_id,
            confirm_type="variable_confirm",
            title=f"确认变量: {var_name}",
            content=content,
            options=options,
            context={"variable": variable},
            priority="normal"
        )

    def create_skill_selection_card(
        self,
        session_id: str,
        project_id: str,
        available_skills: list[dict],
        recommended_skills: list[str],
        reason: str = ""
    ) -> str:
        """
        创建技能选择卡片

        Args:
            session_id: 会话ID
            project_id: 项目ID
            available_skills: 可用技能列表
            recommended_skills: 推荐的技能ID列表
            reason: 推荐理由

        Returns:
            card_id: 卡片ID
        """
        content = f"## 技能选择\n\n"
        if reason:
            content += f"推荐理由: {reason}\n\n"

        content += "### 可用技能\n"
        for skill in available_skills[:8]:
            skill_id = skill.get("skill_id", skill.get("id", "?"))
            name = skill.get("name", skill_id)
            desc = skill.get("description", "")
            is_recommended = skill_id in recommended_skills

            prefix = "[推荐] " if is_recommended else ""
            content += f"- **{prefix}{name}** ({skill_id}): {desc}\n"

        options = []
        for skill_id in recommended_skills[:3]:
            skill = next((s for s in available_skills if s.get("skill_id") == skill_id), {})
            options.append({
                "id": skill_id,
                "label": f"使用 {skill.get('name', skill_id)}",
                "description": skill.get("description", "")
            })

        options.extend([
            {"id": "manual", "label": "手动选择", "description": "从列表中选择"},
            {"id": "auto", "label": "自动决定", "description": "让AI自动选择"},
        ])

        return self.create_confirmation_card(
            session_id=session_id,
            project_id=project_id,
            confirm_type="skill_select",
            title="选择执行技能",
            content=content,
            options=options,
            context={"available_skills": available_skills, "recommended": recommended_skills},
            priority="normal"
        )

    def create_method_recommend_card(
        self,
        session_id: str,
        project_id: str,
        recommended_method: str,
        alternative_methods: list[str],
        model_complexity: str = ""
    ) -> str:
        """
        创建预测方法推荐卡片

        Args:
            session_id: 会话ID
            project_id: 项目ID
            recommended_method: 推荐的方法
            alternative_methods: 备选方法列表
            model_complexity: 模型复杂度

        Returns:
            card_id: 卡片ID
        """
        content = "## 预测方法选择\n\n"

        if model_complexity:
            content += f"模型复杂度: {model_complexity}\n\n"

        method_descriptions = {
            "koopman_dmd": "动态模式分解 (DMD)，适合线性/弱非线性系统，计算效率高",
            "koopman_edmd": "扩展DMD，使用字典函数逼近非线性，适合复杂系统",
            "monte_carlo": "蒙特卡洛采样，适合不确定性量化",
            "neural_ode": "神经常微分方程，适合强非线性系统，需要GPU",
            "pinn": "物理信息神经网络 (PINN)，需要物理先验知识",
        }

        content += f"### 推荐方法: **{recommended_method}**\n"
        content += f"{method_descriptions.get(recommended_method, '')}\n\n"

        if alternative_methods:
            content += "### 备选方法\n"
            for method in alternative_methods:
                content += f"- {method}: {method_descriptions.get(method, '')}\n"

        options = [
            {"id": "use_recommended", "label": "使用推荐方法", "description": f"使用 {recommended_method}"},
        ]
        for method in alternative_methods[:2]:
            options.append({
                "id": method,
                "label": f"选择 {method}",
                "description": method_descriptions.get(method, "")
            })

        return self.create_confirmation_card(
            session_id=session_id,
            project_id=project_id,
            confirm_type="method_recommend",
            title="选择预测方法",
            content=content,
            options=options,
            context={
                "recommended": recommended_method,
                "alternatives": alternative_methods
            },
            priority="high"
        )

    def wait_for_card_response(
        self,
        card_id: str,
        timeout: int = 300
    ) -> Optional[dict]:
        """
        等待卡片响应

        Args:
            card_id: 卡片ID
            timeout: 超时时间（秒）

        Returns:
            dict: {"selected_id": str, "card": dict} 或 None
        """
        _LOG.info("[ReactCardIntegration] Waiting for card response: %s", card_id)

        response = self.card_manager.wait_for_response(card_id, timeout)

        if response:
            _LOG.info("[ReactCardIntegration] Card response received: %s", response.selected_option_id)
            return {
                "selected_id": response.selected_option_id,
                "card_id": card_id,
                "metadata": response.metadata
            }
        else:
            _LOG.warning("[ReactCardIntegration] Card response timeout: %s", card_id)
            return None

    def handle_card_response(self, session_id: str, response: dict) -> dict:
        """
        处理卡片响应，返回继续ReAct所需的信息

        Args:
            session_id: 会话ID
            response: 卡片响应 {"selected_id": str, ...}

        Returns:
            dict: {"action": str, "params": dict}
        """
        selected = response.get("selected_id", "")

        # 根据选择决定后续行动
        if selected == "confirm":
            return {"action": "continue", "params": {}}
        elif selected == "cancel" or selected == "dismissed":
            return {"action": "abort", "params": {"reason": "user_cancelled"}}
        elif selected == "edit":
            return {"action": "request_edit", "params": {}}
        elif selected == "skip":
            return {"action": "skip", "params": {}}
        elif selected == "use_recommended":
            return {"action": "use_recommended", "params": {}}
        elif selected == "merge":
            return {"action": "merge_variable", "params": {}}
        elif selected == "rename":
            return {"action": "request_rename", "params": {}}
        elif selected == "auto":
            return {"action": "auto_select", "params": {}}
        elif selected.startswith("model_"):
            return {"action": "select_model", "params": {"model_type": selected}}
        else:
            # 其他情况，继续执行选中的技能
            return {"action": "execute_skill", "params": {"skill_id": selected}}

    def _get_icon_for_type(self, confirm_type: str) -> str:
        """获取确认类型对应的图标"""
        icons = {
            "variable_confirm": "📊",
            "relation_confirm": "🔗",
            "model_confirm": "🏗️",
            "method_recommend": "⚙️",
            "prediction_exec": "🔮",
            "skill_select": "🛠️",
            "general": "❓",
        }
        return icons.get(confirm_type, "📋")
