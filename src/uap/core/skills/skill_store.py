"""
UAP 技能系统 - 技能存储模块

负责技能的持久化存储，基于项目目录结构存储技能文件。
"""

import json
import os
from pathlib import Path
from typing import Optional

from uap.core.skills.models import ProjectSkill, SkillSession, SkillCategory


class SkillStore:
    """
    技能存储管理器
    
    负责技能的读取、写入、列表等持久化操作。
    技能以 Markdown 文件格式存储，便于阅读和编辑。
    
    存储结构:
        projects/
        └── {project_id}/
            └── skills/
                ├── metadata.json        # 技能索引
                ├── modeling/
                │   ├── skill_001.md     # 技能文件
                │   └── skill_002.md
                ├── prediction/
                └── analysis/
    """
    
    def __init__(self, projects_dir: str):
        self.projects_dir = Path(projects_dir)
    
    def _get_project_skills_dir(self, project_id: str) -> Path:
        """获取项目的技能目录"""
        skills_dir = self.projects_dir / project_id / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        return skills_dir
    
    def _get_category_dir(self, project_id: str, category: SkillCategory) -> Path:
        """获取指定类别的技能目录"""
        category_dir = self._get_project_skills_dir(project_id) / category.value
        category_dir.mkdir(parents=True, exist_ok=True)
        return category_dir
    
    def _get_metadata_path(self, project_id: str) -> Path:
        """获取元数据文件路径"""
        return self._get_project_skills_dir(project_id) / "metadata.json"
    
    # ==================== 技能写入 ====================
    
    def save_skill(self, skill: ProjectSkill) -> str:
        """
        保存技能到文件
        
        Args:
            skill: 技能对象
            
        Returns:
            技能文件路径
        """
        # 确定类别目录
        category_dir = self._get_category_dir(skill.project_id, skill.category)
        
        # 生成文件名
        skill_file = category_dir / f"{skill.skill_id}.md"
        
        # 写入技能文件
        with open(skill_file, 'w', encoding='utf-8') as f:
            f.write(skill.to_skill_md())
        
        # 更新索引
        self._update_metadata(skill)
        
        return str(skill_file)
    
    def _update_metadata(self, skill: ProjectSkill) -> None:
        """更新技能索引元数据"""
        metadata_path = self._get_metadata_path(skill.project_id)
        
        # 读取现有元数据
        if metadata_path.exists():
            with open(metadata_path, 'r', encoding='utf-8') as f:
                metadata = json.load(f)
        else:
            metadata = {"skills": [], "categories": {}}
        
        # 更新技能索引
        skill_info = {
            "skill_id": skill.skill_id,
            "name": skill.name,
            "category": skill.category.value if isinstance(skill.category, SkillCategory) else skill.category,
            "confidence": skill.confidence,
            "usage_count": skill.usage_count,
            "version": skill.version,
            "is_auto_generated": skill.is_auto_generated,
            "created_at": skill.created_at.isoformat() if hasattr(skill.created_at, 'isoformat') else str(skill.created_at),
            "updated_at": skill.updated_at.isoformat() if hasattr(skill.updated_at, 'isoformat') else str(skill.updated_at),
            "file_path": f"{skill.category.value}/{skill.skill_id}.md"
        }
        
        # 查找并更新或添加
        found = False
        for i, s in enumerate(metadata.get("skills", [])):
            if s["skill_id"] == skill.skill_id:
                metadata["skills"][i] = skill_info
                found = True
                break
        
        if not found:
            metadata["skills"].append(skill_info)
        
        # 更新类别统计
        category_key = skill.category.value if isinstance(skill.category, SkillCategory) else skill.category
        if category_key not in metadata.get("categories", {}):
            metadata["categories"][category_key] = []
        if skill.skill_id not in metadata["categories"][category_key]:
            metadata["categories"][category_key].append(skill.skill_id)
        
        # 写入元数据
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    # ==================== 技能读取 ====================
    
    def get_skill(self, project_id: str, skill_id: str) -> Optional[ProjectSkill]:
        """
        获取指定技能
        
        Args:
            project_id: 项目ID
            skill_id: 技能ID
            
        Returns:
            技能对象，如果不存在返回 None
        """
        # 先尝试从元数据获取类别
        metadata = self._get_metadata(project_id)
        category = None
        
        if metadata:
            for skill_info in metadata.get("skills", []):
                if skill_info["skill_id"] == skill_id:
                    category = skill_info.get("category", "general")
                    break
        
        # 如果元数据中没有，尝试所有类别
        if not category:
            for cat in SkillCategory:
                skill_path = self._get_category_dir(project_id, cat) / f"{skill_id}.md"
                if skill_path.exists():
                    category = cat.value
                    break
        
        if not category:
            return None
        
        # 读取技能文件
        skill_path = self._get_category_dir(project_id, SkillCategory(category)) / f"{skill_id}.md"
        
        if not skill_path.exists():
            return None
        
        with open(skill_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return ProjectSkill.from_skill_md(content, project_id)
    
    def list_skills(
        self,
        project_id: str,
        category: Optional[SkillCategory] = None,
        limit: int = 100
    ) -> list[ProjectSkill]:
        """
        列出项目的技能
        
        Args:
            project_id: 项目ID
            category: 可选，按类别筛选
            limit: 返回数量限制
            
        Returns:
            技能列表
        """
        skills = []
        skills_dir = self._get_project_skills_dir(project_id)
        
        if not skills_dir.exists():
            return []
        
        # 确定要扫描的类别
        categories = [category] if category else list(SkillCategory)
        
        for cat in categories:
            cat_dir = skills_dir / cat.value
            if not cat_dir.exists():
                continue
            
            for skill_file in cat_dir.glob("*.md"):
                if len(skills) >= limit:
                    break
                
                try:
                    with open(skill_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    skill = ProjectSkill.from_skill_md(content, project_id)
                    skills.append(skill)
                except Exception as e:
                    print(f"Failed to load skill {skill_file}: {e}")
        
        return skills
    
    def get_skills_by_category(
        self,
        project_id: str,
        category: SkillCategory
    ) -> list[ProjectSkill]:
        """获取指定类别的所有技能"""
        return self.list_skills(project_id, category)
    
    def search_skills(
        self,
        project_id: str,
        query: str
    ) -> list[ProjectSkill]:
        """
        搜索技能（基于名称和描述）
        
        Args:
            project_id: 项目ID
            query: 搜索关键词
            
        Returns:
            匹配的技能列表
        """
        all_skills = self.list_skills(project_id)
        query_lower = query.lower()
        
        matched = []
        for skill in all_skills:
            # 名称匹配
            if query_lower in skill.name.lower():
                matched.append(skill)
                continue
            
            # 描述匹配
            if query_lower in skill.description.lower():
                matched.append(skill)
                continue
            
            # 触发条件匹配
            if any(query_lower in tc.lower() for tc in skill.trigger_conditions):
                matched.append(skill)
        
        return matched
    
    # ==================== 技能删除 ====================
    
    def delete_skill(self, project_id: str, skill_id: str) -> bool:
        """
        删除技能
        
        Args:
            project_id: 项目ID
            skill_id: 技能ID
            
        Returns:
            是否成功删除
        """
        skill = self.get_skill(project_id, skill_id)
        if not skill:
            return False
        
        # 删除技能文件
        skill_path = self._get_category_dir(project_id, skill.category) / f"{skill_id}.md"
        if skill_path.exists():
            skill_path.unlink()
        
        # 从元数据中移除
        self._remove_from_metadata(project_id, skill_id)
        
        return True
    
    def _remove_from_metadata(self, project_id: str, skill_id: str) -> None:
        """从元数据中移除技能"""
        metadata_path = self._get_metadata_path(project_id)
        
        if not metadata_path.exists():
            return
        
        with open(metadata_path, 'r', encoding='utf-8') as f:
            metadata = json.load(f)
        
        # 移除技能
        metadata["skills"] = [
            s for s in metadata.get("skills", [])
            if s["skill_id"] != skill_id
        ]
        
        # 写回
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
    
    # ==================== 元数据 ====================
    
    def _get_metadata(self, project_id: str) -> Optional[dict]:
        """获取技能元数据"""
        metadata_path = self._get_metadata_path(project_id)
        
        if not metadata_path.exists():
            return None
        
        with open(metadata_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def get_skill_stats(self, project_id: str) -> dict:
        """获取项目技能统计"""
        metadata = self._get_metadata(project_id)
        
        if not metadata:
            return {
                "total": 0,
                "by_category": {},
                "auto_generated": 0,
                "manual": 0
            }
        
        skills = metadata.get("skills", [])
        
        by_category = {}
        auto_generated = 0
        manual = 0
        
        for skill in skills:
            cat = skill.get("category", "general")
            by_category[cat] = by_category.get(cat, 0) + 1
            
            if skill.get("is_auto_generated"):
                auto_generated += 1
            else:
                manual += 1
        
        return {
            "total": len(skills),
            "by_category": by_category,
            "auto_generated": auto_generated,
            "manual": manual
        }
    
    # ==================== 技能会话 ====================
    
    def save_session(self, session: SkillSession) -> str:
        """
        保存技能生成会话
        
        Args:
            session: 会话对象
            
        Returns:
            会话文件路径
        """
        project_dir = self.projects_dir / session.project_id
        project_dir.mkdir(parents=True, exist_ok=True)
        
        sessions_dir = project_dir / "skill_sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        
        session_file = sessions_dir / f"{session.session_id}.json"
        
        with open(session_file, 'w', encoding='utf-8') as f:
            json.dump(session.to_dict(), f, ensure_ascii=False, indent=2)
        
        return str(session_file)
    
    def get_session(self, project_id: str, session_id: str) -> Optional[SkillSession]:
        """获取会话"""
        session_file = self.projects_dir / project_id / "skill_sessions" / f"{session_id}.json"
        
        if not session_file.exists():
            return None
        
        with open(session_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return SkillSession.from_dict(data)
    
    def list_sessions(
        self,
        project_id: str,
        status: Optional[str] = None,
        limit: int = 50
    ) -> list[SkillSession]:
        """列出项目的会话"""
        sessions_dir = self.projects_dir / project_id / "skill_sessions"
        
        if not sessions_dir.exists():
            return []
        
        sessions = []
        for session_file in sorted(
            sessions_dir.glob("*.json"),
            key=lambda f: f.stat().st_mtime,
            reverse=True
        )[:limit]:
            try:
                with open(session_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                session = SkillSession.from_dict(data)
                
                if status is None or session.status == status:
                    sessions.append(session)
            except Exception as e:
                print(f"Failed to load session {session_file}: {e}")
        
        return sessions
    
    def cleanup_old_sessions(self, project_id: str, days: int = 7) -> int:
        """
        清理旧会话
        
        Args:
            project_id: 项目ID
            days: 保留天数
            
        Returns:
            删除的会话数量
        """
        import time
        
        sessions_dir = self.projects_dir / project_id / "skill_sessions"
        
        if not sessions_dir.exists():
            return 0
        
        cutoff_time = time.time() - (days * 24 * 60 * 60)
        deleted = 0
        
        for session_file in sessions_dir.glob("*.json"):
            if session_file.stat().st_mtime < cutoff_time:
                session_file.unlink()
                deleted += 1
        
        return deleted
