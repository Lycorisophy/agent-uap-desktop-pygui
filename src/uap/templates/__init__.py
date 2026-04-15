"""
UAP 预测场景模板模块
预设领域模板，快速启动复杂系统建模
"""

from .registry import ScenarioRegistry, ScenarioTemplate
from .presets import (
    POWER_GRID_TEMPLATE,
    SUPPLY_CHAIN_TEMPLATE,
    FINANCIAL_MARKET_TEMPLATE,
    ECOLOGICAL_SYSTEM_TEMPLATE,
    CLIMATE_SYSTEM_TEMPLATE,
    CUSTOM_TEMPLATE,
)

__all__ = [
    'ScenarioRegistry',
    'ScenarioTemplate',
    'POWER_GRID_TEMPLATE',
    'SUPPLY_CHAIN_TEMPLATE',
    'FINANCIAL_MARKET_TEMPLATE',
    'ECOLOGICAL_SYSTEM_TEMPLATE',
    'CLIMATE_SYSTEM_TEMPLATE',
    'CUSTOM_TEMPLATE',
]
