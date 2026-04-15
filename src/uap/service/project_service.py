"""
ProjectService —— **领域编排层**（介于 Harness ``UAPApi`` 与存储 ``ProjectStore`` 之间）
================================================================================

典型链路：
- **建模**：``modeling_chat`` / ``react_modeling`` —— 组装 LLM、ReAct、技能注册表、
  DST、卡片（**RADH = ReAct + DST + HITL**）。
- **记忆**：对话 JSON、系统模型文件经 ``ProjectStore``；可选向量检索在 API/服务扩展。
- **提示词/上下文**：ReAct 的内置模板在 ``ReactAgent._build_context``；本服务负责
  **注入业务事实**（项目路径、已有模型字典等）。

不宜在本类直接写 PyWebView 或 HTTP 路由逻辑，保持可单测。
================================================================================
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from uap.config import UapConfig
from uap.llm import ModelExtractor, create_default_extractor
from uap.llm.ollama_client import OllamaClient, OllamaConfig
from uap.project.models import (
    ModelSource,
    PredictionConfig,
    Project,
    ProjectStatus,
    SystemModel,
    Variable,
    Relation,
)
from uap.project.project_store import ProjectStore

_LOG = logging.getLogger("uap.project_service")


class ProjectService:
    """
    项目级用例的 **编排服务**：创建/打开项目、持久化消息、触发 **行动模式** 建模、
    与文档导入、模型抽取等交叉能力。

    依赖注入：``store`` 管文件与 SQLite 侧持久化；``cfg`` 提供 LLM/记忆/上下文开关。
    """

    def __init__(
        self,
        store: ProjectStore,
        cfg: UapConfig,
        extractor: Optional[ModelExtractor] = None
    ) -> None:
        """
        初始化项目服务
        
        Args:
            store: 项目存储实例
            cfg: 应用配置
            extractor: 模型提取器，默认创建Ollama提取器
        """
        self._store = store
        self._cfg = cfg
        # 使用配置中的模型创建提取器
        from uap.llm.ollama_client import OllamaClient, OllamaConfig
        from uap.llm.model_extractor import ModelExtractor
        ollama_cfg = OllamaConfig(
            base_url=cfg.llm.base_url,
            model=cfg.llm.model,
        )
        ollama_client = OllamaClient(ollama_cfg)
        self._extractor = extractor or ModelExtractor(ollama_client)
    
    def refresh_extractor(self):
        """重新创建提取器以使用最新配置"""
        from uap.llm.ollama_client import OllamaClient, OllamaConfig
        from uap.llm.model_extractor import ModelExtractor
        ollama_cfg = OllamaConfig(
            base_url=self._cfg.llm.base_url,
            model=self._cfg.llm.model,
        )
        ollama_client = OllamaClient(ollama_cfg)
        self._extractor = ModelExtractor(ollama_client)
        _LOG = logging.getLogger("uap.project_service")
        _LOG.info(f"Extractor refreshed with model={self._cfg.llm.model}")
    
    @property
    def store(self) -> ProjectStore:
        """获取项目存储"""
        return self._store
    
    @property
    def extractor(self) -> ModelExtractor:
        """获取模型提取器"""
        return self._extractor
    
    def set_extractor(self, extractor: ModelExtractor):
        """
        设置模型提取器
        
        Args:
            extractor: 新的模型提取器实例
        """
        self._extractor = extractor
    
    # ============ 项目管理 ============
    
    def create_project(
        self,
        name: str,
        description: str = "",
        workspace: str = ""
    ) -> dict:
        """
        创建新项目
        
        Args:
            name: 项目名称
            description: 项目描述
            workspace: 工作空间路径
            
        Returns:
            dict: 创建结果，包含project和project_id
        """
        if not name.strip():
            return {"ok": False, "error": "项目名称不能为空"}
        
        project = self._store.create_project(
            name=name.strip(),
            description=description.strip(),
            workspace=workspace.strip()
        )
        
        _LOG.info("创建项目: %s (id=%s)", project.name, project.id)
        
        return {
            "ok": True,
            "project": project.to_summary(),
            "project_id": project.id,
        }
    
    def get_project(self, project_id: str) -> dict:
        """
        获取项目信息
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 项目信息和系统模型
        """
        try:
            project = self._store.get_project(project_id)
            return {
                "ok": True,
                "project": project.model_dump(),
                "system_model": project.system_model.model_dump() if project.system_model else None,
            }
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def list_projects(self) -> list[dict]:
        """
        列出所有项目
        
        Returns:
            list[dict]: 项目摘要列表
        """
        projects = self._store.list_projects()
        return [p.to_summary() for p in projects]
    
    def search_projects(self, query: str) -> list[dict]:
        """
        搜索项目
        
        Args:
            query: 搜索关键词
            
        Returns:
            list[dict]: 匹配的项目列表
        """
        projects = self._store.search_projects(query)
        return [p.to_summary() for p in projects]
    
    def delete_project(self, project_id: str) -> dict:
        """
        删除项目
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 删除结果
        """
        try:
            self._store.delete_project(project_id)
            _LOG.info("删除项目: %s", project_id)
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def update_project(
        self,
        project_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        tags: Optional[list[str]] = None,
    ) -> dict:
        """
        更新项目信息
        
        Args:
            project_id: 项目ID
            name: 新名称
            description: 新描述
            tags: 新标签
            
        Returns:
            dict: 更新结果
        """
        try:
            project = self._store.get_project(project_id)
            if name is not None:
                project.name = name.strip()
            if description is not None:
                project.description = description.strip()
            if tags is not None:
                project.tags = tags
            
            project = self._store.update_project(project)
            return {"ok": True, "project": project.to_summary()}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    # ============ 系统模型 ============
    
    def save_model(self, project_id: str, model: SystemModel) -> dict:
        """
        保存系统模型
        
        Args:
            project_id: 项目ID
            model: 系统模型对象
            
        Returns:
            dict: 保存结果
        """
        try:
            project = self._store.get_project(project_id)
            project.system_model = model
            project = self._store.update_project(project)
            self._store.save_model(project_id, model)
            _LOG.info("保存模型: project=%s, model_id=%s", project_id, model.id)
            return {"ok": True, "model_id": model.id}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def load_model(self, project_id: str) -> dict:
        """
        加载系统模型
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 模型数据
        """
        model = self._store.load_model(project_id)
        if model is None:
            return {"ok": False, "error": "模型不存在"}
        return {"ok": True, "model": model.model_dump()}
    
    def extract_model_from_conversation(
        self,
        project_id: str,
        messages: list[dict],
        user_prompt: str,
    ) -> dict:
        """
        从对话中提取系统模型
        
        使用LLM分析对话历史和用户描述，自动提取系统的数学模型。
        
        Args:
            project_id: 项目ID
            messages: 对话历史消息列表
            user_prompt: 用户当前的系统描述
            
        Returns:
            dict: 提取结果，包含模型数据
        """
        try:
            project = self._store.get_project(project_id)
            
            _LOG.info("开始从对话提取模型: project=%s", project_id)
            
            # 调用LLM提取模型
            result = self._extractor.extract_from_conversation(
                messages=messages,
                user_prompt=user_prompt
            )
            
            if not result.success:
                _LOG.warning("模型提取失败: %s", result.error)
                return {
                    "ok": False,
                    "error": result.error or "模型提取失败"
                }
            
            model = result.model
            model.name = f"{project.name} - 对话建模"
            model.source = ModelSource.LLM_EXTRACTED
            model.modeling_prompt = user_prompt
            
            # 验证模型
            is_valid, errors = self._extractor.validate_model(model)
            if not is_valid:
                _LOG.warning("模型验证失败: %s", errors)
                return {
                    "ok": False,
                    "error": f"模型验证失败: {', '.join(errors)}"
                }
            
            # 保存模型和项目
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._store.save_model(project_id, model)
            
            _LOG.info(
                "模型提取成功: project=%s, variables=%d, relations=%d, confidence=%.2f",
                project_id, len(model.variables), len(model.relations), model.confidence
            )
            
            return {
                "ok": True,
                "model": model.model_dump(),
                "reasoning": result.reasoning,
                "message": f"成功提取模型，包含{len(model.variables)}个变量和{len(model.relations)}个关系"
            }
            
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
        except Exception as e:
            _LOG.error("模型提取异常: %s", str(e))
            return {"ok": False, "error": f"模型提取异常: {str(e)}"}
    
    def import_model_from_document(
        self,
        project_id: str,
        document_content: str,
        document_name: str = "",
    ) -> dict:
        """
        从文档导入系统模型
        
        使用LLM分析文档内容，自动提取系统的数学模型。
        
        Args:
            project_id: 项目ID
            document_content: 文档文本内容
            document_name: 文档名称
            
        Returns:
            dict: 提取结果，包含模型数据
        """
        try:
            project = self._store.get_project(project_id)
            
            _LOG.info(
                "开始从文档提取模型: project=%s, doc=%s",
                project_id, document_name
            )
            
            # 调用LLM提取模型
            result = self._extractor.extract_from_document(
                document_content=document_content,
                document_name=document_name
            )
            
            if not result.success:
                _LOG.warning("文档模型提取失败: %s", result.error)
                return {
                    "ok": False,
                    "error": result.error or "文档模型提取失败"
                }
            
            model = result.model
            model.name = f"{project.name} - 文档导入"
            model.source = ModelSource.LLM_EXTRACTED
            model.modeling_prompt = f"文档: {document_name}"
            
            # 验证模型
            is_valid, errors = self._extractor.validate_model(model)
            if not is_valid:
                _LOG.warning("模型验证失败: %s", errors)
                return {
                    "ok": False,
                    "error": f"模型验证失败: {', '.join(errors)}"
                }
            
            # 保存模型和项目
            project.system_model = model
            project.status = ProjectStatus.MODELING
            project = self._store.update_project(project)
            self._store.save_model(project_id, model)
            
            _LOG.info(
                "文档模型提取成功: project=%s, variables=%d, relations=%d",
                project_id, len(model.variables), len(model.relations)
            )
            
            return {
                "ok": True,
                "model": model.model_dump(),
                "reasoning": result.reasoning,
                "message": f"成功从文档'{document_name}'提取模型"
            }
            
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
        except Exception as e:
            _LOG.error("文档模型提取异常: %s", str(e))
            return {"ok": False, "error": f"文档模型提取异常: {str(e)}"}
    
    # ============ 预测配置 ============
    
    def save_prediction_config(
        self,
        project_id: str,
        config: PredictionConfig,
    ) -> dict:
        """
        保存预测配置
        
        Args:
            project_id: 项目ID
            config: 预测配置对象
            
        Returns:
            dict: 保存结果
        """
        try:
            project = self._store.get_project(project_id)
            project.prediction_config = config
            project = self._store.update_project(project)
            self._store.save_prediction_config(project_id, config)
            _LOG.info(
                "保存预测配置: project=%s, frequency=%ds, horizon=%ds",
                project_id, config.frequency_sec, config.horizon_sec
            )
            return {"ok": True}
        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
    
    def load_prediction_config(self, project_id: str) -> dict:
        """
        加载预测配置
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 配置数据
        """
        config = self._store.load_prediction_config(project_id)
        return {"ok": True, "config": config.model_dump()}
    
    # ============ 对话 ============
    
    def get_messages(self, project_id: str) -> list[dict]:
        """
        获取对话消息
        
        Args:
            project_id: 项目ID
            
        Returns:
            list[dict]: 消息列表
        """
        return self._store.load_messages(project_id)
    
    def save_message(
        self,
        project_id: str,
        role: str,
        content: str,
    ) -> dict:
        """
        保存对话消息
        
        Args:
            project_id: 项目ID
            role: 消息角色（user/assistant）
            content: 消息内容
            
        Returns:
            dict: 保存结果
        """
        try:
            messages = self._store.load_messages(project_id)
            messages.append({
                "role": role,
                "content": content,
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            self._store.save_messages(project_id, messages)
            return {"ok": True, "message_count": len(messages)}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    
    def append_assistant_message(self, project_id: str, content: str) -> dict:
        """
        追加助手消息
        
        Args:
            project_id: 项目ID
            content: 助手回复内容
            
        Returns:
            dict: 保存结果
        """
        return self.save_message(project_id, "assistant", content)
    
    def clear_messages(self, project_id: str) -> dict:
        """
        清空对话历史
        
        Args:
            project_id: 项目ID
            
        Returns:
            dict: 清空结果
        """
        try:
            self._store.save_messages(project_id, [])
            return {"ok": True}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ============ ReAct 智能建模 ============

    def react_modeling(
        self,
        project_id: str,
        user_message: str,
        card_manager=None,
        web_search_func=None,
    ) -> dict:
        """
        **RADH 智能建模主入口**：ReAct（行动）+ DST（槽位上下文）+ HITL（卡片）。

        与 ``UAPApi.modeling_chat`` 搭配：API 层负责落盘用户句；本方法负责
        **技能与工具注册表组装**、**单次会话内 ReAct 循环**、以及可选 **卡片确认**。

        Args:
            project_id: 目标项目
            user_message: 本轮用户自然语言输入（已进入 store 的消息列表由 API 维护）
            card_manager: 传入则启用 ``ReactCardIntegration``（人在环确认建模结果）
            web_search_func: 传入则注册 ``web_search`` 工具（否则不暴露网络能力）

        Returns:
            dict: 含 ``ok``、``message``、``steps``、``dst_state``、``pending_card`` 等，
            供 **Harness** 前端刷新「进程 / DST / 卡片」。
        """
        try:
            from uap.react import (
                ReactAgent,
                DstManager,
                create_web_search_skill,
                ReactCardIntegration,
            )
            from uap.skill.atomic_skills import get_atomic_skills_library, AtomicSkill

            project = self._store.get_project(project_id)

            _LOG.info("[ReactModeling] Starting: project=%s, message=%s",
                      project_id, user_message[:50])

            # --- 1. DST：会话内「建模阶段 + 槽位」状态机（上下文工程）---
            dst_manager = DstManager()

            # --- 2. LLM 客户端：提示词工程在 ReactAgent 内；此处只配端点与模型名 ---
            llm_cfg = OllamaConfig(
                base_url=self._cfg.llm.base_url,
                model=self._cfg.llm.model,
            )
            llm_client = OllamaClient(llm_cfg)

            # --- 3. 技能注册表 = 原子库 + 动态业务技能（工具系统「白名单」）---
            skills_registry = {}

            # 内置原子技能：来自静态元数据字典，一般不含项目闭包
            atomic_skills = get_atomic_skills_library()
            for skill_id, skill_meta in atomic_skills.items():
                skills_registry[skill_id] = AtomicSkill(skill_meta)

            # 可选：Web 搜索（需 Harness 注入合规的 search 函数，避免任意 SSRF）
            if web_search_func:
                web_skill = create_web_search_skill(web_search_func)
                skills_registry["web_search"] = web_skill

            # 动态技能：闭包捕获 self，实现「提取 / 变量 / 关系」与 ProjectStore 交互
            model_extract_skill = self._create_model_extraction_skill()
            skills_registry["extract_model"] = model_extract_skill

            variable_skill = self._create_variable_definition_skill()
            skills_registry["define_variable"] = variable_skill

            relation_skill = self._create_relation_discovery_skill()
            skills_registry["discover_relations"] = relation_skill

            # 项目沙箱内读文件：缩小 **工具授权面**（仅 project_folder 下）
            from uap.react.file_access_skill import create_file_access_skill
            file_skill = create_file_access_skill(
                project_folder=project.folder_path
            )
            skills_registry["file_access"] = file_skill

            # --- 4. ReAct 引擎：迭代上限与时间上限在构造参数体现（安全 Harness）---
            react_agent = ReactAgent(
                llm_client=llm_client,
                skills_registry=skills_registry,
                dst_manager=dst_manager,
                max_iterations=15,
                max_time_seconds=180.0,
            )

            # 5. 创建卡片集成
            card_integration = None
            if card_manager:
                card_integration = ReactCardIntegration(card_manager)

            # 6. 构建上下文
            context = {
                "project_id": project_id,
                "project_name": project.name,
                "existing_model": project.system_model.model_dump() if project.system_model else None,
            }

            # 7. 执行ReAct循环
            result = react_agent.run(user_message, context)

            _LOG.info("[ReactModeling] Completed: success=%s, steps=%d",
                      result.success, result.total_steps)

            # 8. 从DST状态提取模型
            model = self._build_model_from_dst(dst_manager, result.session_id, project.name)

            # 9. 弹出确认卡片
            pending_card = None
            if model and card_integration and (model.variables or model.relations):
                card_id = card_integration.create_model_confirm_card(
                    session_id=result.session_id,
                    project_id=project_id,
                    variables=[v.model_dump() for v in model.variables],
                    relations=[r.model_dump() for r in model.relations],
                    constraints=model.constraints or [],
                )
                pending_card = card_id

            # 10. 保存结果
            if model:
                project.system_model = model
                project.status = ProjectStatus.MODELING
                project = self._store.update_project(project)
                self._store.save_model(project_id, model)

            return {
                "ok": True,
                "message": self._generate_response_message(result, model),
                "model": model.model_dump() if model else None,
                "session_id": result.session_id,
                "steps": [s.model_dump() for s in result.steps],
                "dst_state": result.dst_state,
                "pending_card": pending_card,
                "success": result.success,
            }

        except FileNotFoundError:
            return {"ok": False, "error": "项目不存在"}
        except Exception as e:
            _LOG.exception("[ReactModeling] Error: %s", str(e))
            return {"ok": False, "error": f"ReAct建模异常: {str(e)}"}

    def _create_model_extraction_skill(self):
        """创建模型提取技能"""
        from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory, SkillComplexity

        metadata = SkillMetadata(
            skill_id="extract_model",
            name="提取系统模型",
            description="从对话中提取复杂系统的数学模型，包括变量、关系和约束",
            category=SkillCategory.MODELING,
            subcategory="extraction",
            input_schema={
                "type": "object",
                "required": ["user_description"],
                "properties": {
                    "user_description": {"type": "string", "description": "用户对系统的描述"}
                }
            },
            estimated_time=10,
            complexity=SkillComplexity.MODERATE,
            provides_skills=["variable_collection", "relation_discovery"]
        )

        skill = AtomicSkill(metadata)

        def executor(s, user_description="", **kwargs):
            try:
                result = self._extractor.extract_from_conversation(
                    messages=[{"role": "user", "content": user_description}],
                    user_prompt=user_description
                )
                if result.success:
                    model = result.model
                    return {
                        "observation": f"提取到模型：{len(model.variables)}个变量，{len(model.relations)}个关系",
                        "variables": [v.model_dump() for v in model.variables],
                        "relations": [r.model_dump() for r in model.relations],
                    }
                else:
                    return {"error": result.error, "observation": f"提取失败: {result.error}"}
            except Exception as e:
                return {"error": str(e), "observation": f"提取异常: {str(e)}"}

        skill.set_executor(executor)
        return skill

    def _create_variable_definition_skill(self):
        """创建变量定义技能"""
        from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory, SkillComplexity

        metadata = SkillMetadata(
            skill_id="define_variable",
            name="定义系统变量",
            description="定义系统的状态变量，包括名称、类型、单位、取值范围等",
            category=SkillCategory.MODELING,
            subcategory="variable",
            input_schema={
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string", "description": "变量名称"},
                    "value_type": {"type": "string", "description": "变量类型"},
                    "description": {"type": "string", "description": "变量描述"},
                    "unit": {"type": "string", "description": "物理单位"},
                }
            },
            estimated_time=2,
            complexity=SkillComplexity.SIMPLE,
        )

        skill = AtomicSkill(metadata)

        def executor(s, name="", description="", value_type="float", unit="", **kwargs):
            var = Variable(
                name=name,
                value_type=value_type,
                description=description,
                unit=unit or "",
            )
            return {
                "observation": f"定义变量：{name} (类型={value_type})",
                "variable": var.model_dump(),
                "needs_confirmation": True,
            }

        skill.set_executor(executor)
        return skill

    def _create_relation_discovery_skill(self):
        """创建关系发现技能"""
        from uap.skill.atomic_skills import AtomicSkill, SkillMetadata, SkillCategory, SkillComplexity

        metadata = SkillMetadata(
            skill_id="discover_relations",
            name="发现系统关系",
            description="识别系统中变量之间的数学关系或物理规律",
            category=SkillCategory.MODELING,
            subcategory="relation",
            input_schema={
                "type": "object",
                "required": ["from_var", "to_var", "relationship"],
                "properties": {
                    "from_var": {"type": "string", "description": "源变量"},
                    "to_var": {"type": "string", "description": "目标变量"},
                    "relationship": {"type": "string", "description": "关系描述"},
                }
            },
            estimated_time=5,
            complexity=SkillComplexity.MODERATE,
        )

        skill = AtomicSkill(metadata)

        def executor(s, from_var="", to_var="", relationship="", **kwargs):
            rel = Relation(
                name=f"{from_var}_to_{to_var}",
                source=from_var,
                target=to_var,
                description=relationship
            )
            return {
                "observation": f"发现关系：{from_var} → {to_var}",
                "relation": rel.model_dump(),
                "needs_confirmation": True,
            }

        skill.set_executor(executor)
        return skill

    def _build_model_from_dst(self, dst_manager, session_id: str, project_name: str) -> Optional[SystemModel]:
        """从DST状态构建系统模型"""
        model_summary = dst_manager.get_model_summary(session_id)
        if not model_summary:
            return None

        variables = [Variable(**v) if isinstance(v, dict) else v for v in model_summary.get("variables", [])]
        relations = [Relation(**r) if isinstance(r, dict) else r for r in model_summary.get("relations", [])]

        model = SystemModel(
            id=str(uuid.uuid4()),
            name=f"{project_name} - ReAct建模",
            source=ModelSource.LLM_EXTRACTED,
            variables=variables,
            relations=relations,
            constraints=model_summary.get("constraints", []),
            confidence=model_summary.get("confidence", 0.5),
        )
        return model

    def _generate_response_message(self, result, model) -> str:
        """生成响应消息"""
        if result.success and model:
            parts = []
            if model.variables:
                parts.append(f"已识别 {len(model.variables)} 个变量")
            if model.relations:
                parts.append(f"发现 {len(model.relations)} 个关系")
            if parts:
                return "建模进度：" + "，".join(parts) + "。"
        return "建模完成。" if result.success else f"建模问题：{result.error_message or '未知错误'}"
