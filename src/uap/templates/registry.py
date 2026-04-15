"""
场景模板注册表
管理所有预测场景模板
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field
from enum import Enum
import json
from pathlib import Path


class ScenarioCategory(Enum):
    """场景类别"""
    POWER_GRID = "power_grid"
    SUPPLY_CHAIN = "supply_chain"
    FINANCIAL = "financial"
    ECOLOGICAL = "ecological"
    CLIMATE = "climate"
    INDUSTRIAL = "industrial"
    TRANSPORTATION = "transportation"
    SOCIAL = "social"
    CUSTOM = "custom"


@dataclass
class VariableConfig:
    """变量配置"""
    name: str
    display_name: str
    unit: str
    description: str
    min_value: float
    max_value: float
    safe_min: Optional[float] = None
    safe_max: Optional[float] = None
    critical_min: Optional[float] = None
    critical_max: Optional[float] = None
    is_state_variable: bool = True
    typical_value: Optional[float] = None


@dataclass
class EquationConfig:
    """方程配置"""
    name: str
    expression: str
    description: str
    variables: List[str] = field(default_factory=list)


@dataclass
class PredictionConfig:
    """预测配置"""
    default_frequency: int = 3600
    default_horizon: int = 259200
    min_frequency: int = 300
    max_frequency: int = 86400
    suggested_methods: List[str] = field(default_factory=list)


@dataclass
class SkillChain:
    """技能链"""
    name: str
    description: str
    skills: List[str] = field(default_factory=list)


@dataclass
class ScenarioTemplate:
    """场景模板"""
    id: str
    name: str
    display_name: str
    description: str
    category: ScenarioCategory
    icon: str
    
    variables: List[VariableConfig] = field(default_factory=list)
    equations: List[EquationConfig] = field(default_factory=list)
    prediction: PredictionConfig = field(default_factory=PredictionConfig)
    skill_chains: List[SkillChain] = field(default_factory=list)
    
    author: str = "UAP Team"
    version: str = "1.0"
    tags: List[str] = field(default_factory=list)
    
    system_prompt: str = ""
    user_prompt_template: str = ""
    example_queries: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'description': self.description,
            'category': self.category.value,
            'icon': self.icon,
            'variables': [{'name': v.name, 'display': v.display_name, 'unit': v.unit} for v in self.variables],
            'prediction': {
                'frequency': self.prediction.default_frequency,
                'horizon': self.prediction.default_horizon
            },
            'tags': self.tags
        }
    
    def get_threshold_config(self) -> Dict:
        """获取阈值配置"""
        thresholds = {}
        for var in self.variables:
            if var.safe_min is not None or var.safe_max is not None:
                thresholds[var.name] = {
                    'safe_min': var.safe_min,
                    'safe_max': var.safe_max
                }
        return thresholds


class ScenarioRegistry:
    """场景模板注册表"""
    
    def __init__(self):
        self.templates: Dict[str, ScenarioTemplate] = {}
        self._load_builtin_templates()
    
    def _load_builtin_templates(self) -> None:
        """加载内置模板"""
        from .presets import (
            POWER_GRID_TEMPLATE,
            SUPPLY_CHAIN_TEMPLATE,
            FINANCIAL_MARKET_TEMPLATE,
            ECOLOGICAL_SYSTEM_TEMPLATE,
            CLIMATE_SYSTEM_TEMPLATE,
            CUSTOM_TEMPLATE,
        )
        
        for template in [
            POWER_GRID_TEMPLATE,
            SUPPLY_CHAIN_TEMPLATE,
            FINANCIAL_MARKET_TEMPLATE,
            ECOLOGICAL_SYSTEM_TEMPLATE,
            CLIMATE_SYSTEM_TEMPLATE,
            CUSTOM_TEMPLATE,
        ]:
            self.register(template)
    
    def register(self, template: ScenarioTemplate) -> None:
        """注册模板"""
        self.templates[template.id] = template
    
    def get(self, template_id: str) -> Optional[ScenarioTemplate]:
        """获取模板"""
        return self.templates.get(template_id)
    
    def list_by_category(self, category: ScenarioCategory) -> List[ScenarioTemplate]:
        """按类别列出模板"""
        return [t for t in self.templates.values() if t.category == category]
    
    def list_all(self) -> List[ScenarioTemplate]:
        """列出所有模板"""
        return list(self.templates.values())
    
    def search(self, query: str) -> List[ScenarioTemplate]:
        """搜索模板"""
        query_lower = query.lower()
        return [
            t for t in self.templates.values()
            if query_lower in t.name.lower() or query_lower in t.description.lower()
        ]
    
    def get_quick_start_prompt(self, template_id: str) -> str:
        """获取快速启动提示"""
        template = self.get(template_id)
        if not template:
            return "请描述您的系统"
        
        prompts = [f"您选择了「{template.display_name}」场景。", f"描述: {template.description}", ""]
        
        if template.example_queries:
            prompts.append("示例查询：")
            for q in template.example_queries[:3]:
                prompts.append(f"  • \"{q}\"")
        
        return "\n".join(prompts)
