"""
SkillManager —— **技能与工具系统**的「持久化技能编排器」（区别于 ReAct 的 AtomicSkill）
================================================================================

定位：
- ``AtomicSkill``：轻量、无项目级存储、适合 **ReAct 工具注册表**。
- ``ProjectSkill`` + 本管理器：带步骤模板（``SkillStep.prompt_template``）、可落盘、
  适合 **Workflow / 半自动技能链** 与 **提示词模板化**。

与 **记忆**：技能 JSON 存于项目目录（经 ``SkillStore``）；执行轨迹写 ``SkillExecution``。

与 **Harness**：一般由服务层构造，不经 PyWebView 直接暴露。
================================================================================
"""

import re
import uuid
from datetime import datetime
from typing import Optional, Callable, Any

from uap.core.skills.models import (
    ProjectSkill, SkillSession, SkillCategory,
    SkillExecution, ActionNode, ActionType, SessionStatus
)
from uap.core.skills.skill_store import SkillStore
from uap.infrastructure.llm.response_text import assistant_text_from_chat_response
from uap.core.skills.generator import SkillGenerator, SkillTemplateGenerator


def _context_lookup_path(context: dict | None, path: str) -> Any:
    """从扁平 ``context`` 中按 ``a.b.c`` 取嵌套键；路径非法或缺失时返回 ``None``。"""
    if context is None or not path:
        return None
    cur: Any = context
    for part in path.split("."):
        part = part.strip()
        if not part:
            continue
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


class SkillManager:
    """
    **项目技能**生命周期：加载/缓存、相关性检索、按步骤执行（每步可调用 LLM）。

    执行路径中会拼接 ``prompt_template`` —— 属于 **提示词工程**；调用方传入的
    ``context`` dict 则是 **上下文工程** 的注入槽（前置条件校验见 ``_check_preconditions``）。
    """

    def __init__(
        self,
        skill_store: SkillStore,
        llm_client: Any,
    ):
        """
        Args:
            skill_store: 项目目录下技能 JSON 的 DAO
            llm_client: 用于步骤级补全 / 生成的统一客户端
        """
        self.store = skill_store  # 持久化：**技能记忆**载体
        self.llm = llm_client  # **推理 Harness**：执行期逐步调用

        # 生成器：偏 **自动技能工匠**（元技能），与运行时执行解耦
        self.generator = SkillGenerator(llm_client)
        self.template_generator = SkillTemplateGenerator(llm_client)

        self.skill_cache: dict[str, list[ProjectSkill]] = {}  # project_id → 技能列表缓存

        self.step_executor: Optional[Callable] = None  # 可选外部钩子：测试/遥测插入点
    
    # ==================== 技能加载 ====================
    
    def load_project_skills(self, project_id: str) -> list[ProjectSkill]:
        """
        加载项目的所有技能
        
        Args:
            project_id: 项目ID
            
        Returns:
            技能列表
        """
        if project_id in self.skill_cache:
            return self.skill_cache[project_id]
        
        skills = self.store.list_skills(project_id)
        self.skill_cache[project_id] = skills
        return skills
    
    def get_skill(
        self,
        project_id: str,
        skill_id: str
    ) -> Optional[ProjectSkill]:
        """获取指定技能"""
        # 先从缓存查找
        if project_id in self.skill_cache:
            for skill in self.skill_cache[project_id]:
                if skill.skill_id == skill_id:
                    return skill
        
        # 从存储加载
        skill = self.store.get_skill(project_id, skill_id)
        
        if skill and project_id in self.skill_cache:
            self.skill_cache[project_id].append(skill)
        
        return skill
    
    def refresh_cache(self, project_id: str) -> None:
        """刷新技能缓存"""
        self.skill_cache[project_id] = self.store.list_skills(project_id)
    
    # ==================== 技能发现 ====================
    
    def get_relevant_skills(
        self,
        project_id: str,
        query: str
    ) -> list[ProjectSkill]:
        """
        根据查询获取相关技能
        
        Args:
            project_id: 项目ID
            query: 用户查询
            
        Returns:
            相关技能列表，按相关性排序
        """
        skills = self.load_project_skills(project_id)
        
        if not skills:
            return []
        
        query_lower = query.lower()
        scored_skills = []
        
        for skill in skills:
            score = 0
            
            # 触发条件匹配
            for tc in skill.trigger_conditions:
                if query_lower in tc.lower():
                    score += 3
            
            # 名称匹配
            if query_lower in skill.name.lower():
                score += 2
            
            # 描述匹配
            if query_lower in skill.description.lower():
                score += 1
            
            # 置信度加成
            score += skill.confidence
            
            if score > 0:
                scored_skills.append((skill, score))
        
        # 按分数排序
        scored_skills.sort(key=lambda x: x[1], reverse=True)
        
        return [s[0] for s in scored_skills]
    
    def get_skills_by_category(
        self,
        project_id: str,
        category: SkillCategory
    ) -> list[ProjectSkill]:
        """获取指定类别的技能"""
        skills = self.load_project_skills(project_id)
        return [s for s in skills if s.category == category]
    
    def get_best_skill_for_task(
        self,
        project_id: str,
        task_description: str,
        category: Optional[SkillCategory] = None
    ) -> Optional[ProjectSkill]:
        """
        获取最适合任务的最优技能
        
        Args:
            project_id: 项目ID
            task_description: 任务描述
            category: 可选，限定类别
            
        Returns:
            最优技能
        """
        skills = self.get_relevant_skills(project_id, task_description)
        
        if category:
            skills = [s for s in skills if s.category == category]
        
        # 按置信度排序
        if skills:
            skills.sort(key=lambda s: s.confidence, reverse=True)
            return skills[0]
        
        return None
    
    # ==================== 技能执行 ====================
    
    def execute_skill(
        self,
        skill: ProjectSkill,
        parameters: dict,
        context: dict = None
    ) -> SkillExecution:
        """
        执行技能
        
        Args:
            skill: 要执行的技能
            parameters: 执行参数
            context: 执行上下文
            
        Returns:
            执行结果
        """
        execution = SkillExecution(
            execution_id=str(uuid.uuid4()),
            skill_id=skill.skill_id,
            project_id=skill.project_id,
            parameters=parameters,
            context=context or {}
        )
        
        try:
            # 1. 验证前置条件
            if not self._check_preconditions(skill, context):
                execution.fail("前置条件不满足")
                return execution
            
            # 2. 合并参数
            merged_params = self._merge_parameters(skill, parameters)
            
            # 3. 执行步骤
            for i, step in enumerate(skill.steps):
                step_result = self._execute_step(
                    step, merged_params, context
                )
                
                execution.step_results.append(step_result)
                
                # 4. 验证步骤输出
                if step_result.get("status") == "failed":
                    execution.fail(f"步骤 {i+1} 执行失败: {step_result.get('error')}")
                    return execution
            
            # 5. 执行成功
            execution.complete({
                "steps_completed": len(skill.steps),
                "final_result": execution.step_results[-1].get("output") 
                if execution.step_results else None
            })
            
        except Exception as e:
            execution.fail(str(e))
        
        # 6. 更新技能统计
        skill.record_usage(execution.status == "completed")
        self.store.save_skill(skill)
        
        return execution
    
    def _check_preconditions(
        self,
        skill: ProjectSkill,
        context: dict
    ) -> bool:
        """检查前置条件。

        支持：
        - ``ctx:foo`` / ``context:foo.bar``：要求 ``context`` 路径上为真值；
        - 纯 ``foo`` 或 ``foo.bar``（仅字母数字下划线与点）：同上；
        - 含「需要」「必须有」的自由文本：向后兼容，尝试从句中提取首个连续词并在 ``context`` 顶层查找键。
        """
        if not skill.preconditions:
            return True
        ctx = context or {}
        for precond in skill.preconditions:
            if not self._precondition_line_ok(str(precond), ctx):
                return False
        return True

    def _precondition_line_ok(self, line: str, context: dict) -> bool:
        s = line.strip()
        if not s:
            return True
        low = s.lower()
        if low.startswith("ctx:") or low.startswith("context:"):
            path = s.split(":", 1)[1].strip()
            if not path:
                return True
            val = _context_lookup_path(context, path)
            return val is not None and bool(val)
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*", s):
            val = _context_lookup_path(context, s)
            return val is not None and bool(val)
        if "需要" in s or "必须有" in s:
            field_match = re.search(r"[\u4e00-\u9fa5a-zA-Z_]+", s)
            if field_match:
                field = field_match.group()
                if field not in context:
                    return False
        return True
    
    def _merge_parameters(
        self,
        skill: ProjectSkill,
        provided: dict
    ) -> dict:
        """合并参数"""
        merged = {}
        
        # 先填默认值
        for param in skill.parameters:
            if param.default is not None:
                merged[param.name] = param.default
        
        # 再用提供的值覆盖
        for key, value in provided.items():
            merged[key] = value
        
        return merged
    
    def _execute_step(
        self,
        step,
        parameters: dict,
        context: dict
    ) -> dict:
        """执行单个步骤"""
        result = {
            "step_number": step.step_number,
            "title": step.title,
            "status": "running"
        }
        
        try:
            # 根据行动类型执行
            if step.action_type == ActionType.THOUGHT:
                # 思考类型：使用 LLM 生成分析
                prompt = step.prompt_template.format(**parameters) if step.prompt_template else step.description
                
                response = self.llm.chat([
                    {"role": "user", "content": prompt}
                ])

                result["output"] = assistant_text_from_chat_response(response)
                result["status"] = "completed"
                
            elif step.action_type == ActionType.TOOL_CALL:
                # 工具调用类型：使用配置的 executor
                if self.step_executor:
                    output = self.step_executor(
                        tool_name=step.tool_name,
                        parameters=parameters,
                        context=context
                    )
                    result["output"] = output
                    result["status"] = "completed"
                else:
                    # 没有配置执行器时，使用 LLM 模拟
                    prompt = step.prompt_template.format(**parameters) if step.prompt_template else step.description
                    
                    response = self.llm.chat([
                        {"role": "user", "content": f"执行以下任务: {prompt}"}
                    ])

                    result["output"] = assistant_text_from_chat_response(response)
                    result["status"] = "completed"
            else:
                result["status"] = "completed"
                result["output"] = step.description
                
        except Exception as e:
            result["status"] = "failed"
            result["error"] = str(e)
        
        return result
    
    # ==================== 技能生命周期 ====================
    
    def create_skill(
        self,
        session: SkillSession,
        project_info: dict
    ) -> Optional[ProjectSkill]:
        """
        从会话创建技能
        
        Args:
            session: DST 追踪的会话
            project_info: 项目信息
            
        Returns:
            创建的技能
        """
        skill = self.generator.generate(session, project_info)
        
        if skill:
            self.store.save_skill(skill)
            
            # 更新缓存
            if skill.project_id in self.skill_cache:
                self.skill_cache[skill.project_id].append(skill)
        
        return skill
    
    def update_skill(
        self,
        skill: ProjectSkill,
        updates: dict
    ) -> ProjectSkill:
        """
        更新技能
        
        Args:
            skill: 要更新的技能
            updates: 更新内容
            
        Returns:
            更新后的技能
        """
        # 应用更新
        for key, value in updates.items():
            if hasattr(skill, key):
                setattr(skill, key, value)
        
        skill.increment_version()
        skill.updated_at = datetime.now()
        
        # 保存
        self.store.save_skill(skill)
        
        # 更新缓存
        if skill.project_id in self.skill_cache:
            for i, s in enumerate(self.skill_cache[skill.project_id]):
                if s.skill_id == skill.skill_id:
                    self.skill_cache[skill.project_id][i] = skill
                    break
        
        return skill
    
    def delete_skill(
        self,
        project_id: str,
        skill_id: str
    ) -> bool:
        """
        删除技能
        
        Args:
            project_id: 项目ID
            skill_id: 技能ID
            
        Returns:
            是否成功删除
        """
        result = self.store.delete_skill(project_id, skill_id)
        
        if result and project_id in self.skill_cache:
            self.skill_cache[project_id] = [
                s for s in self.skill_cache[project_id]
                if s.skill_id != skill_id
            ]
        
        return result
    
    def merge_skill(
        self,
        base_skill: ProjectSkill,
        new_session: SkillSession,
        project_info: dict
    ) -> ProjectSkill:
        """
        合并新经验到现有技能
        
        Args:
            base_skill: 基础技能
            new_session: 新会话
            project_info: 项目信息
            
        Returns:
            合并后的技能
        """
        # 从新会话生成增量技能
        incremental = self.generator.generate(new_session, project_info)
        
        if not incremental:
            return base_skill
        
        # 智能合并步骤
        merged_steps = self._smart_merge_steps(
            base_skill.steps,
            incremental.steps
        )
        
        # 合并触发条件
        merged_triggers = list(set(
            base_skill.trigger_conditions + incremental.trigger_conditions
        ))
        
        # 更新技能
        base_skill.steps = merged_steps
        base_skill.trigger_conditions = merged_triggers
        base_skill.version += 1
        base_skill.usage_count += 1
        base_skill.updated_at = datetime.now()
        
        # 重新计算置信度
        base_skill.confidence = (
            base_skill.confidence * 0.7 + incremental.confidence * 0.3
        )
        
        # 保存
        self.store.save_skill(base_skill)
        
        return base_skill
    
    def _smart_merge_steps(
        self,
        base_steps: list,
        incremental_steps: list
    ) -> list:
        """智能合并步骤"""
        # 简单策略：追加新步骤，标记为可选
        merged = list(base_steps)
        
        for step in incremental_steps:
            # 检查是否已存在相似步骤
            exists = False
            for base_step in base_steps:
                if self._steps_similar(base_step, step):
                    exists = True
                    break
            
            if not exists:
                # 标记为备选方案
                step.title = f"[可选] {step.title}"
                merged.append(step)
        
        return merged
    
    def _steps_similar(self, step1, step2, threshold: float = 0.6) -> bool:
        """判断两个步骤是否相似"""
        # 简单的文本相似度比较
        text1 = step1.title.lower() + " " + step1.description.lower()
        text2 = step2.title.lower() + " " + step2.description.lower()
        
        # 字符集重叠度
        set1 = set(text1)
        set2 = set(text2)
        
        if not set1 or not set2:
            return False
        
        overlap = len(set1 & set2) / len(set1 | set2)
        
        return overlap >= threshold
    
    # ==================== 技能模板 ====================
    
    def create_from_template(
        self,
        project_id: str,
        template_name: str,
        project_info: dict,
        customizations: dict = None
    ) -> Optional[ProjectSkill]:
        """
        从模板创建技能
        
        Args:
            project_id: 项目ID
            template_name: 模板名称
            project_info: 项目信息
            customizations: 自定义配置
            
        Returns:
            创建的技能
        """
        try:
            skill = self.template_generator.generate_from_template(
                template_name,
                {**project_info, "project_id": project_id},
                customizations
            )
            
            skill.project_id = project_id
            skill.skill_id = f"skill_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            self.store.save_skill(skill)
            
            return skill
        except ValueError as e:
            print(f"Template error: {e}")
            return None
    
    def list_available_templates(self) -> list[str]:
        """列出可用的模板"""
        return [
            "lotka_volterra_modeling",
            "sir_epidemic_modeling",
            "prey_predator_forecast",
            "chaos_detection",
            "stability_analysis"
        ]
    
    # ==================== 统计信息 ====================
    
    def get_skill_stats(self, project_id: str) -> dict:
        """获取项目技能统计"""
        skills = self.load_project_skills(project_id)
        
        by_category = {}
        total_usage = 0
        total_success = 0
        auto_generated = 0
        
        for skill in skills:
            cat = skill.category.value if hasattr(skill.category, 'value') else str(skill.category)
            by_category[cat] = by_category.get(cat, 0) + 1
            
            total_usage += skill.usage_count
            total_success += skill.success_count
            
            if skill.is_auto_generated:
                auto_generated += 1
        
        return {
            "total": len(skills),
            "by_category": by_category,
            "total_usage": total_usage,
            "overall_success_rate": (
                total_success / total_usage if total_usage > 0 else 0
            ),
            "auto_generated": auto_generated,
            "manual": len(skills) - auto_generated
        }
    
    # ==================== DST 会话管理 ====================
    
    def start_session(
        self,
        project_id: str,
        user_query: str
    ) -> SkillSession:
        """
        开始新的技能追踪会话
        
        Args:
            project_id: 项目ID
            user_query: 用户问题
            
        Returns:
            新建的会话
        """
        session = SkillSession(
            session_id=f"sess_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            project_id=project_id,
            user_query=user_query,
            status=SessionStatus.ACTIVE
        )
        
        return session
    
    def record_action(
        self,
        session: SkillSession,
        action: ActionNode
    ) -> None:
        """记录会话中的操作"""
        session.add_action(action)
    
    def complete_session(
        self,
        session: SkillSession,
        final_output: Any = None
    ) -> None:
        """完成会话"""
        session.final_output = final_output
        session.end_time = datetime.now()
        session.status = SessionStatus.COMPLETED
        
        # 计算总耗时
        if session.end_time and session.start_time:
            session.total_duration_ms = int(
                (session.end_time - session.start_time).total_seconds() * 1000
            )
        
        # 保存会话
        self.store.save_session(session)
    
    def abort_session(self, session: SkillSession) -> None:
        """中止会话"""
        session.end_time = datetime.now()
        session.status = SessionStatus.ABORTED
        
        self.store.save_session(session)
    
    def should_generate_skill(
        self,
        session: SkillSession
    ) -> tuple[bool, str]:
        """
        评估是否应该生成技能
        
        Returns:
            (should_generate, reason) 元组
        """
        return session.should_generate_skill({
            "min_steps": 5,
            "min_corrections": 0,
            "min_duration_ms": 30000,
        })
    
    def auto_generate_skill(
        self,
        session: SkillSession,
        project_info: dict
    ) -> Optional[ProjectSkill]:
        """
        自动从会话生成技能
        
        如果会话满足触发条件，则生成技能。
        """
        should_gen, reason = self.should_generate_skill(session)
        
        if not should_gen:
            return None
        
        return self.create_skill(session, project_info)
