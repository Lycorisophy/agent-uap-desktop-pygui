"""
UAP API Class
Provides Python API for JavaScript frontend calls
"""

import json
import os
import logging
from typing import Optional, Any
from datetime import datetime

# 配置日志
_LOG = logging.getLogger("uap.api")
_LOG.setLevel(logging.DEBUG)

from uap.config import load_config, UAPConfig
from uap.project.models import (
    Project, ProjectStatus, SystemModel, PredictionConfig,
    PredictionTask, PredictionResult, ModelSource
)
from uap.project.project_store import ProjectStore
from uap.service.project_service import ProjectService
from uap.service.prediction_service import PredictionService
from uap.scheduler import TaskScheduler, SchedulerConfig
from uap.card import CardManager, CardGenerator, CardContext, CardResponse
from uap.skill import get_atomic_skills_library


class UAPApi:
    """
    UAP External API Interface
    Provides interface wrapper for frontend JavaScript calls
    """

    def __init__(self, config: Optional[UAPConfig] = None):
        self.config = config or load_config()
        # Use storage.projects_root or default ~/.uap/projects
        projects_root = self.config.storage.projects_root or os.path.join(
            os.path.expanduser("~"), ".uap", "projects"
        )
        self.project_store = ProjectStore(projects_root)
        self.project_service = ProjectService(self.project_store, self.config)
        self.prediction_service = PredictionService(self.project_store, self.config)
        self.scheduler = self._init_scheduler()
        
        # Card system initialization
        self.card_manager = CardManager(default_timeout=300)
        self.card_generator = CardGenerator()
        
        # Atomic skills library
        self.atomic_skills = get_atomic_skills_library()

    def _init_scheduler(self) -> TaskScheduler:
        """Initialize scheduler"""
        scheduler_config = SchedulerConfig(
            check_interval=self.config.scheduler.tick_interval_sec,
            max_concurrent_tasks=self.config.scheduler.max_projects_per_tick,
            task_timeout=300,
            retry_times=3,
            retry_interval=60,
            enabled=self.config.scheduler.enabled
        )

        scheduler = TaskScheduler(scheduler_config)
        scheduler.set_tasks_file(
            os.path.join(self.project_store.root, 'scheduled_tasks.json')
        )
        scheduler.set_task_callback(self._on_prediction_task)
        scheduler.load_tasks()

        return scheduler

    def _on_prediction_task(self, project_id: str):
        """Prediction task callback"""
        try:
            project = self.project_store.get_project(project_id)
            if not project:
                print(f"Project not found: {project_id}")
                return

            result = self.prediction_service.run_prediction(
                project,
                project.prediction_config
            )

            # Save prediction result
            self.project_store.save_prediction_result(project_id, result)

            # Update project status
            project.last_prediction_at = result.predicted_at
            self.project_store.save_project(project)

        except Exception as e:
            print(f"Prediction task failed: {e}")

    # ==================== Project Management API ====================

    def create_project(self, name: str, description: str = "") -> dict:
        """
        Create new project
        
        Args:
            name: Project name
            description: Project description
            
        Returns:
            Project info dict
        """
        return self.project_service.create_project(name, description)

    def get_project(self, project_id: str) -> Optional[dict]:
        """Get project info"""
        if not project_id or project_id == "undefined":
            return None
        project = self.project_store.get_project(project_id)
        return project.model_dump() if project else None

    def list_projects(self, limit: int = 50, offset: int = 0) -> dict:
        """List all projects"""
        projects = self.project_store.list_projects()
        total = len(projects)
        items = projects[offset:offset + limit]
        return {
            "items": [p.to_summary() for p in items],
            "total": total
        }

    def delete_project(self, project_id: str) -> dict:
        """Delete project"""
        if not project_id or project_id == "undefined":
            return {"success": False, "error": "Invalid project ID"}
        
        try:
            # Stop related tasks
            tasks = self.scheduler.get_project_tasks(project_id)
            for task in tasks:
                self.scheduler.remove_task(task.id)

            # Delete project
            self.project_store.delete_project(project_id)
            return {"success": True, "project_id": project_id}
        except FileNotFoundError:
            return {"success": False, "error": "Project not found"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # ==================== System Model API ====================

    def save_model(self, project_id: str, model_data: dict) -> dict:
        """Save system model"""
        model = SystemModel(**model_data)
        self.project_store.save_model(project_id, model)

        # Update project status
        project = self.project_store.get_project(project_id)
        if project:
            project.status = ProjectStatus.MODELING
            self.project_store.save_project(project)

        return {"success": True, "project_id": project_id}

    def get_model(self, project_id: str) -> Optional[dict]:
        """Get system model"""
        project = self.project_store.get_project(project_id)
        if project and project.system_model:
            return project.system_model.model_dump()
        return None

    def extract_model_from_conversation(
        self,
        project_id: str,
        messages: list[dict],
        user_prompt: str
    ) -> dict:
        """Extract system model from conversation"""
        return self.project_service.extract_model_from_conversation(
            project_id, messages, user_prompt
        )

    def modeling_chat(self, project_id: str, message: str) -> dict:
        """
        Chat with the agent for system modeling using ReAct mode
        
        ReAct模式特点：
        1. LLM决定使用哪些技能
        2. 通过DST跟踪建模进度
        3. 可以自主搜索网络获取信息
        4. 通过卡片让用户确认关键决策
        
        Args:
            project_id: Project ID
            message: User's message describing the system
            
        Returns:
            dict with message, optional model, and ReAct execution details
        """
        _LOG.info("[API] modeling_chat called: project_id=%s, message_len=%d", project_id, len(message))
        try:
            # Load existing messages for context
            messages = self.project_store.load_messages(project_id)
            _LOG.debug("[API] Loaded %d existing messages", len(messages))
            
            # Save the user message first
            messages.append({"role": "user", "content": message, "created_at": datetime.now().isoformat()})
            self.project_store.save_messages(project_id, messages)
            
            # 使用ReAct模式进行智能建模
            _LOG.info("[API] Calling react_modeling (ReAct mode)...")
            result = self.project_service.react_modeling(
                project_id=project_id,
                user_message=message,
                card_manager=self.card_manager,
                web_search_func=self._get_web_search_func(),
            )
            _LOG.info("[API] react_modeling result: ok=%s, success=%s", result.get("ok"), result.get("success"))
            
            if result.get("ok"):
                response_message = result.get("message", "建模完成")
                
                # 构建详细的执行信息
                steps_info = ""
                if result.get("steps"):
                    steps_info = f"\n\n[ReAct执行: {len(result['steps'])}步]"
                    for step in result["steps"][-3:]:  # 显示最近3步
                        if step.get("thought"):
                            steps_info += f"\n- 思考: {step['thought'][:50]}..."
                        if step.get("action") and step.get("action") != "FINAL_ANSWER":
                            steps_info += f"\n  行动: {step['action']}"
                
                # 构建DST状态信息
                dst_info = ""
                dst_state = result.get("dst_state", {})
                if dst_state:
                    progress = dst_state.get("progress", 0)
                    stage = dst_state.get("current_stage", "unknown")
                    vars_count = len(dst_state.get("variables", []))
                    rels_count = len(dst_state.get("relations", []))
                    dst_info = f"\n[进度: {progress*100:.0f}%] 阶段={stage}, 变量={vars_count}, 关系={rels_count}"
                
                full_message = response_message + steps_info + dst_info
                
                # 保存助手响应
                self.project_store.save_messages(project_id,
                    self.project_store.load_messages(project_id) + [
                        {"role": "assistant", "content": full_message, "created_at": datetime.now().isoformat()}
                    ]
                )
                
                return {
                    "ok": True,
                    "message": full_message,
                    "model": result.get("model"),
                    "session_id": result.get("session_id"),
                    "steps": result.get("steps", []),
                    "dst_state": dst_state,
                    "pending_card": result.get("pending_card"),
                    "success": result.get("success", False),
                    "tool_calls": result.get("tool_calls", 0),
                }
            else:
                error_msg = result.get("error", "建模失败")
                _LOG.warning("[API] modeling_chat failed: %s", error_msg)
                return {
                    "ok": False,
                    "message": error_msg
                }
        except Exception as e:
            _LOG.exception("[API] modeling_chat exception: %s", str(e))
            return {
                "ok": False,
                "message": str(e)
            }
    
    def _get_web_search_func(self):
        """获取Web搜索函数"""
        # 可以集成实际的搜索API
        # 这里返回None，将在react_modeling中决定是否启用
        return None

    def import_model_from_document(
        self,
        project_id: str,
        document_content: str,
        document_name: str
    ) -> dict:
        """Import system model from document"""
        return self.project_service.import_model_from_document(
            project_id, document_content, document_name
        )

    # ==================== Prediction Config API ====================

    def save_prediction_config(
        self,
        project_id: str,
        config_data: dict
    ) -> dict:
        """Save prediction config"""
        return self.project_service.save_prediction_config(project_id, config_data)

    def get_prediction_config(self, project_id: str) -> Optional[dict]:
        """Get prediction config"""
        project = self.project_store.get_project(project_id)
        if project:
            return project.prediction_config.model_dump()
        return None

    # ==================== Prediction Task API ====================

    def create_prediction_task(
        self,
        project_id: str,
        trigger_type: str = "interval",
        interval_seconds: int = 3600
    ) -> dict:
        """Create prediction task"""
        # Validate project exists
        project = self.project_store.get_project(project_id)
        if not project:
            return {"success": False, "error": "Project not found"}

        # Check if active task exists
        existing_tasks = self.scheduler.get_project_tasks(project_id)
        active_tasks = [t for t in existing_tasks if t.status.value in ['pending', 'running']]
        if active_tasks:
            return {
                "success": False,
                "error": "Active prediction task already exists",
                "task_id": active_tasks[0].id
            }

        # Create task
        if trigger_type == "interval":
            task = self.scheduler.add_interval_task(project_id, interval_seconds)
        elif trigger_type == "cron":
            task = self.scheduler.add_cron_task(project_id, "0 * * * *")
        else:
            task = self.scheduler.add_one_time_task(project_id, datetime.now())

        return {
            "success": True,
            "task_id": task.id,
            "task": task.model_dump()
        }

    def get_prediction_task(self, task_id: str) -> Optional[dict]:
        """Get task info"""
        task = self.scheduler.get_task(task_id)
        return task.model_dump() if task else None

    def get_project_tasks(self, project_id: str) -> list[dict]:
        """Get all tasks for project"""
        tasks = self.scheduler.get_project_tasks(project_id)
        return [t.model_dump() for t in tasks]

    def pause_prediction_task(self, task_id: str) -> dict:
        """Pause prediction task"""
        success = self.scheduler.pause_task(task_id)
        return {"success": success, "task_id": task_id}

    def resume_prediction_task(self, task_id: str) -> dict:
        """Resume prediction task"""
        success = self.scheduler.resume_task(task_id)
        return {"success": success, "task_id": task_id}

    def delete_prediction_task(self, task_id: str) -> dict:
        """Delete prediction task"""
        success = self.scheduler.remove_task(task_id)
        return {"success": success, "task_id": task_id}

    def run_prediction_now(self, project_id: str) -> dict:
        """Run prediction immediately"""
        _LOG.info("[API] run_prediction_now called: project_id=%s", project_id)
        project = self.project_store.get_project(project_id)
        if not project:
            _LOG.warning("[API] run_prediction_now: project not found: %s", project_id)
            return {"success": False, "error": "Project not found"}

        _LOG.info("[API] Starting prediction with config: %s", project.prediction_config)
        result = self.prediction_service.run_prediction(
            project,
            project.prediction_config
        )
        _LOG.info("[API] Prediction completed: status=%s, result_id=%s", result.status, result.id)

        self.project_store.save_prediction_result(project_id, result)
        project.last_prediction_at = result.predicted_at
        self.project_store.save_project(project)

        return {
            "success": True,
            "result": result.model_dump()
        }

    # ==================== Prediction Result API ====================

    def get_prediction_results(
        self,
        project_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> dict:
        """Get prediction result list"""
        results = self.project_store.list_prediction_results(project_id, limit, offset)
        return {
            "items": [r.model_dump() for r in results],
            "total": len(results)
        }

    def get_prediction_result(self, project_id: str, result_id: str) -> Optional[dict]:
        """Get single prediction result"""
        result = self.project_store.get_prediction_result(project_id, result_id)
        return result.model_dump() if result else None

    # ==================== Scheduler Status API ====================

    def get_scheduler_status(self) -> dict:
        """Get scheduler status"""
        return self.scheduler.get_status()

    def start_scheduler(self) -> dict:
        """Start scheduler"""
        self.scheduler.start()
        return {"success": True, "running": True}

    def stop_scheduler(self) -> dict:
        """Stop scheduler"""
        self.scheduler.stop()
        return {"success": True, "running": False}

    # ==================== Config API ====================

    def get_config(self) -> dict:
        """Get current config"""
        return {
            "prediction_defaults": self.config.prediction_defaults.model_dump(),
            "llm": self.config.llm.model_dump(),
            "storage": self.config.storage.model_dump(),
        }

    def update_config(self, config_updates: dict) -> dict:
        """Update config and persist to file"""
        try:
            _LOG.info("[API] update_config called: %s", config_updates)
            
            # 更新内存中的配置
            if "llm" in config_updates:
                llm_data = config_updates["llm"]
                if "model" in llm_data:
                    self.config.llm.model = llm_data["model"]
                if "base_url" in llm_data:
                    self.config.llm.base_url = llm_data["base_url"]
                if llm_data.get("api_key"):
                    self.config.llm.api_key = llm_data["api_key"]
            
            if "prediction_defaults" in config_updates:
                pd = config_updates["prediction_defaults"]
                freq = pd.get("frequency_sec") or pd.get("defaultFrequency") or 3600
                horizon = pd.get("horizon_sec") or pd.get("defaultHorizon") or 259200
                self.config.prediction.default_frequency_sec = int(freq)
                self.config.prediction.default_horizon_sec = int(horizon)
            
            # 持久化到配置文件
            from uap.config import local_override_config_path, save_llm_local_yaml
            config_path = local_override_config_path()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            import yaml
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(self.config.model_dump(mode="json"), f, allow_unicode=True, default_flow_style=False)
            
            # 刷新提取器使用新模型
            self.project_service.refresh_extractor()
            
            _LOG.info("[API] Config saved to: %s, model=%s", config_path, self.config.llm.model)
            return {"success": True, "message": "Config saved", "config": self.config.model_dump()}
        except Exception as e:
            _LOG.exception("[API] Failed to save config: %s", str(e))
            return {"success": False, "error": str(e)}

    # ==================== Card Confirmation API ====================

    def get_pending_card(self, project_id: str) -> Optional[dict]:
        """Get pending card for project"""
        card = self.card_manager.get_pending_card_for_project(project_id)
        return card.to_dict() if card else None

    def get_all_pending_cards(self) -> list[dict]:
        """Get all pending cards"""
        cards = self.card_manager.get_pending_cards()
        return [card.to_dict() for card in cards]

    def submit_card_response(self, card_id: str, selected_option_id: str) -> dict:
        """Submit card response"""
        response = CardResponse(
            card_id=card_id,
            selected_option_id=selected_option_id
        )
        success = self.card_manager.submit_response(response)
        return {"success": success, "card_id": card_id}

    def dismiss_card(self, card_id: str) -> dict:
        """Dismiss card"""
        success = self.card_manager.dismiss_card(card_id, "user_dismissed")
        return {"success": success, "card_id": card_id}

    def create_model_confirm_card(
        self,
        project_id: str,
        variables: list[dict],
        relations: list[dict],
        constraints: list[dict]
    ) -> dict:
        """Create model confirmation card"""
        context = CardContext(project_id=project_id)
        card = self.card_generator.generate_model_confirm_card(
            context, variables, relations, constraints
        )
        self.card_manager.create_card(card)
        return {"success": True, "card": card.to_dict()}

    def create_prediction_method_card(self, project_id: str) -> dict:
        """Create prediction method selection card"""
        context = CardContext(project_id=project_id, task_type="prediction")
        methods = self.card_generator.get_default_prediction_methods()
        card = self.card_generator.generate_prediction_method_card(context, methods)
        self.card_manager.create_card(card)
        return {"success": True, "card": card.to_dict()}

    def create_prediction_execution_card(
        self,
        project_id: str,
        method_name: str,
        horizon: int,
        frequency: int
    ) -> dict:
        """Create prediction execution confirmation card"""
        context = CardContext(project_id=project_id, task_type="prediction")
        card = self.card_generator.generate_prediction_execution_card(
            context, method_name, horizon, frequency
        )
        self.card_manager.create_card(card)
        return {"success": True, "card": card.to_dict()}

    # ==================== Skills API ====================

    def get_atomic_skills(self, category: Optional[str] = None) -> list[dict]:
        """Get atomic skills library"""
        if category:
            from uap.skill.atomic_skills import get_skills_by_category, SkillCategory
            try:
                cat = SkillCategory(category)
                skills = get_skills_by_category(cat)
                return [meta.to_dict() for meta in skills.values()]
            except ValueError:
                return []
        return [meta.to_dict() for meta in self.atomic_skills.values()]

    def get_skill_chain_recommendations(self, task_type: str) -> list[list[str]]:
        """Get skill chain recommendations"""
        from uap.skill.atomic_skills import get_skill_chain_recommendations as get_recs
        return get_recs(task_type)

    def get_card_history(self, project_id: str, limit: int = 50) -> list[dict]:
        """Get card history"""
        cards = self.card_manager.get_card_history_for_project(project_id, limit)
        return [card.to_dict() for card in cards]

    # ==================== 文件夹操作API ====================

    def get_project_folder(self, project_id: str) -> dict:
        """
        Get project folder path
        Returns the absolute path to the project's local folder
        """
        try:
            project = self.project_store.get_project(project_id)
            if not project:
                return {"success": False, "error": "项目不存在"}
            return {
                "success": True,
                "folder_path": project.folder_path,
                "project_name": project.name
            }
        except Exception as e:
            _LOG.error(f"获取项目文件夹失败: {e}")
            return {"success": False, "error": str(e)}

    def open_folder(self, folder_path: str) -> dict:
        """
        Open folder in system file explorer
        Works on Windows, macOS, and Linux
        """
        import subprocess
        import sys
        
        try:
            if not os.path.exists(folder_path):
                return {"success": False, "error": "文件夹不存在"}
            
            if sys.platform == "win32":
                os.startfile(folder_path)
            elif sys.platform == "darwin":
                subprocess.run(["open", folder_path])
            else:
                subprocess.run(["xdg-open", folder_path])
            
            return {"success": True}
        except Exception as e:
            _LOG.error(f"打开文件夹失败: {e}")
            return {"success": False, "error": str(e)}


from datetime import datetime
