"""
UAP 预设场景模板
内置的领域模板
"""

from .registry import (
    ScenarioTemplate,
    ScenarioCategory,
    VariableConfig,
    EquationConfig,
    PredictionConfig,
    SkillChain,
)
from uap.prompts import PromptId, load_raw


# ==================== 电网频率模板 ====================
POWER_GRID_TEMPLATE = ScenarioTemplate(
    id="power_grid_frequency",
    name="电网频率",
    display_name="电网频率监控",
    description="电网频率稳定性监控与预测，支持发电机、负荷、保护等多因素建模",
    category=ScenarioCategory.POWER_GRID,
    icon="⚡",
    variables=[
        VariableConfig(
            name="frequency",
            display_name="系统频率",
            unit="Hz",
            description="电网标称频率",
            min_value=49.0,
            max_value=51.0,
            safe_min=49.5,
            safe_max=50.5,
            critical_min=49.0,
            critical_max=51.0,
            typical_value=50.0
        ),
        VariableConfig(
            name="voltage",
            display_name="节点电压",
            unit="p.u.",
            description="电网节点电压标幺值",
            min_value=0.9,
            max_value=1.1,
            safe_min=0.95,
            safe_max=1.05,
            typical_value=1.0
        ),
        VariableConfig(
            name="power_flow",
            display_name="功率潮流",
            unit="MW",
            description="线路传输功率",
            min_value=-5000,
            max_value=5000,
            typical_value=1000
        ),
        VariableConfig(
            name="rocof",
            display_name="频率变化率",
            unit="Hz/s",
            description="Rate of Change of Frequency",
            min_value=-2.0,
            max_value=2.0,
            safe_min=-0.5,
            safe_max=0.5,
            critical_min=-1.0,
            critical_max=1.0,
            typical_value=0.0
        ),
    ],
    equations=[
        EquationConfig(
            name="swing_equation",
            expression="dω/dt = (Pm - Pe) / (2H)",
            description="发电机转子运动方程",
            variables=["frequency", "power_flow"]
        ),
        EquationConfig(
            name="frequency_response",
            expression="Δf = ΔP / (D + 1/R)",
            description="频率响应模型",
            variables=["frequency", "power_flow"]
        ),
    ],
    prediction=PredictionConfig(
        default_frequency=3600,
        default_horizon=86400,
        min_frequency=60,
        max_frequency=3600,
        suggested_methods=["koopman", "neural_ode", "transformer"]
    ),
    skill_chains=[
        SkillChain(
            name="frequency_analysis",
            description="电网频率分析",
            skills=["data_load_timeseries", "preprocess_clean", "feature_delay_embed", 
                    "model_koopman", "postprocess_chaos_detect", "viz_phase_portrait"]
        ),
    ],
    tags=["电力", "频率", "稳定性", "电网"],
    system_prompt=load_raw(PromptId.SCENARIO_POWER_GRID_SYSTEM),
    user_prompt_template="我有一个包含{n_generators}台发电机和{n_loads}个负荷的{voltage_level}电网系统",
    example_queries=[
        "三台100MW火电机组并网运行，频率经常在49.8-50.2Hz波动",
        "区域电网包含风电和光伏，考虑新能源渗透率对频率稳定性的影响",
        "微电网离网运行时如何维持频率稳定",
    ]
)


# ==================== 供应链模板 ====================
SUPPLY_CHAIN_TEMPLATE = ScenarioTemplate(
    id="supply_chain",
    name="供应链",
    display_name="供应链风险管理",
    description="供应链库存、物流、需求预测，支持多级库存优化",
    category=ScenarioCategory.SUPPLY_CHAIN,
    icon="📦",
    variables=[
        VariableConfig(
            name="inventory",
            display_name="库存水平",
            unit="件",
            description="当前库存数量",
            min_value=0,
            max_value=10000,
            typical_value=1000
        ),
        VariableConfig(
            name="demand",
            display_name="需求量",
            unit="件/天",
            description="日均需求量",
            min_value=0,
            max_value=1000,
            typical_value=100
        ),
        VariableConfig(
            name="lead_time",
            display_name="交付周期",
            unit="天",
            description="供应商交付时间",
            min_value=1,
            max_value=30,
            typical_value=7
        ),
        VariableConfig(
            name="stockout_prob",
            display_name="缺货概率",
            unit="%",
            description="缺货风险概率",
            min_value=0,
            max_value=100,
            typical_value=5
        ),
    ],
    equations=[
        EquationConfig(
            name="inventory_balance",
            expression="I(t+1) = I(t) + Q(t) - D(t)",
            description="库存平衡方程",
            variables=["inventory", "demand"]
        ),
        EquationConfig(
            name=" reorder_point",
            expression="ROP = D × LT + SS",
            description="再订货点计算",
            variables=["demand", "lead_time"]
        ),
    ],
    prediction=PredictionConfig(
        default_frequency=7200,
        default_horizon=604800,
        min_frequency=3600,
        max_frequency=86400,
        suggested_methods=["transformer", "monte_carlo"]
    ),
    skill_chains=[
        SkillChain(
            name="demand_forecast",
            description="需求预测",
            skills=["data_load_timeseries", "preprocess_resample", "feature_statistical",
                    "model_transformer", "postprocess_uncertainty"]
        ),
    ],
    tags=["库存", "物流", "需求预测", "风险管理"],
    example_queries=[
        "电商仓库日出货量预测，考虑节假日波动",
        "多级供应链库存优化，最小化牛鞭效应",
        "供应商交付周期不确定下的安全库存计算",
    ]
)


# ==================== 金融市场模板 ====================
FINANCIAL_MARKET_TEMPLATE = ScenarioTemplate(
    id="financial_market",
    name="金融市场",
    display_name="金融市场分析",
    description="股票、期货、外汇等金融时序数据的预测与风险评估",
    category=ScenarioCategory.FINANCIAL,
    icon="📈",
    variables=[
        VariableConfig(
            name="price",
            display_name="价格",
            unit="元",
            description="资产价格",
            min_value=0,
            max_value=1000000,
            typical_value=100
        ),
        VariableConfig(
            name="return",
            display_name="收益率",
            unit="%",
            description="对数收益率",
            min_value=-20,
            max_value=20,
            typical_value=0
        ),
        VariableConfig(
            name="volatility",
            display_name="波动率",
            unit="%",
            description="历史波动率",
            min_value=0,
            max_value=100,
            typical_value=20
        ),
        VariableConfig(
            name="volume",
            display_name="交易量",
            unit="手",
            description="成交量",
            min_value=0,
            max_value=10000000,
            typical_value=100000
        ),
    ],
    equations=[
        EquationConfig(
            name="log_return",
            expression="r(t) = ln(P(t) / P(t-1))",
            description="对数收益率",
            variables=["price"]
        ),
        EquationConfig(
            name="garch",
            expression="σ²(t) = ω + α·ε²(t-1) + β·σ²(t-1)",
            description="GARCH波动率模型",
            variables=["volatility", "return"]
        ),
    ],
    prediction=PredictionConfig(
        default_frequency=3600,
        default_horizon=86400,
        min_frequency=300,
        max_frequency=86400,
        suggested_methods=["neural_ode", "transformer", "monte_carlo"]
    ),
    skill_chains=[
        SkillChain(
            name="volatility_forecast",
            description="波动率预测",
            skills=["data_load_timeseries", "preprocess_normalize", "feature_statistical",
                    "model_transformer", "postprocess_uncertainty", "viz_prediction_interval"]
        ),
    ],
    tags=["股票", "期货", "风险", "量化交易"],
    example_queries=[
        "沪深300指数日收益预测，考虑宏观因素",
        "期权隐含波动率曲面构建",
        "加密货币高波动性下的风险评估",
    ]
)


# ==================== 生态系统模板 ====================
ECOLOGICAL_SYSTEM_TEMPLATE = ScenarioTemplate(
    id="ecological_system",
    name="生态系统",
    display_name="生态系统建模",
    description="捕食者-猎物、种群动态、生态演替等生态系统建模",
    category=ScenarioCategory.ECOLOGICAL,
    icon="🌿",
    variables=[
        VariableConfig(
            name="population",
            display_name="种群数量",
            unit="只",
            description="物种个体数量",
            min_value=0,
            max_value=1000000,
            typical_value=10000
        ),
        VariableConfig(
            name="biomass",
            display_name="生物量",
            unit="kg",
            description="总生物量",
            min_value=0,
            max_value=10000000,
            typical_value=100000
        ),
        VariableConfig(
            name="diversity",
            display_name="多样性指数",
            unit="",
            description="物种多样性指数",
            min_value=0,
            max_value=1,
            typical_value=0.5
        ),
    ],
    equations=[
        EquationConfig(
            name="lotka_volterra",
            expression="dX/dt = αX - βXY\ndY/dt = δXY - γY",
            description="Lotka-Volterra捕食者-猎物模型",
            variables=["population"]
        ),
        EquationConfig(
            name="logistic_growth",
            expression="dN/dt = rN(1 - N/K)",
            description="逻辑斯蒂增长模型",
            variables=["population"]
        ),
    ],
    prediction=PredictionConfig(
        default_frequency=86400,
        default_horizon=2592000,
        min_frequency=3600,
        max_frequency=604800,
        suggested_methods=["neural_ode", "koopman"]
    ),
    skill_chains=[
        SkillChain(
            name="population_dynamics",
            description="种群动态预测",
            skills=["data_load_timeseries", "preprocess_interpolate", "feature_delay_embed",
                    "model_neural_ode", "viz_phase_portrait"]
        ),
    ],
    tags=["生态", "种群", "生物多样性"],
    example_queries=[
        "某湖泊鱼群数量随季节变化预测",
        "外来物种入侵对本地生态的影响评估",
        "保护区的最优种群规模计算",
    ]
)


# ==================== 气候系统模板 ====================
CLIMATE_SYSTEM_TEMPLATE = ScenarioTemplate(
    id="climate_system",
    name="气候系统",
    display_name="气候预测",
    description="温度、降水、气压等气象要素的中长期预测",
    category=ScenarioCategory.CLIMATE,
    icon="🌡️",
    variables=[
        VariableConfig(
            name="temperature",
            display_name="温度",
            unit="°C",
            description="大气温度",
            min_value=-50,
            max_value=60,
            typical_value=20
        ),
        VariableConfig(
            name="precipitation",
            display_name="降水量",
            unit="mm",
            description="日降水量",
            min_value=0,
            max_value=500,
            typical_value=10
        ),
        VariableConfig(
            name="pressure",
            display_name="气压",
            unit="hPa",
            description="海平面气压",
            min_value=900,
            max_value=1100,
            safe_min=980,
            safe_max=1030,
            typical_value=1013
        ),
        VariableConfig(
            name="humidity",
            display_name="湿度",
            unit="%",
            description="相对湿度",
            min_value=0,
            max_value=100,
            typical_value=60
        ),
    ],
    equations=[
        EquationConfig(
            name="energy_balance",
            expression="C·dT/dt = R_net - H - LE",
            description="能量平衡方程",
            variables=["temperature"]
        ),
        EquationConfig(
            name="adiabatic_lapse",
            expression="Γ = -dT/dz",
            description="气温直减率",
            variables=["temperature"]
        ),
    ],
    prediction=PredictionConfig(
        default_frequency=21600,
        default_horizon=604800,
        min_frequency=3600,
        max_frequency=259200,
        suggested_methods=["transformer", "pinn", "neural_ode"]
    ),
    skill_chains=[
        SkillChain(
            name="weather_forecast",
            description="天气预报",
            skills=["data_load_timeseries", "preprocess_clean", "feature_multiscale_entropy",
                    "model_transformer", "postprocess_uncertainty", "viz_heatmap_evolution"]
        ),
    ],
    tags=["气候", "天气", "温度", "预测"],
    example_queries=[
        "未来一周最高温度预报",
        "台风路径概率预测",
        "极端降水事件风险评估",
    ]
)


# ==================== 自定义模板 ====================
CUSTOM_TEMPLATE = ScenarioTemplate(
    id="custom",
    name="自定义",
    display_name="自定义系统",
    description="从零开始定义自己的复杂系统模型",
    category=ScenarioCategory.CUSTOM,
    icon="🔧",
    variables=[],
    equations=[],
    prediction=PredictionConfig(
        default_frequency=3600,
        default_horizon=259200,
        min_frequency=60,
        max_frequency=604800,
        suggested_methods=["koopman", "neural_ode", "monte_carlo"]
    ),
    skill_chains=[],
    tags=["自定义", "通用"],
    system_prompt=load_raw(PromptId.SCENARIO_CUSTOM_SYSTEM),
    example_queries=[
        "我想建模一个无人机编队飞行控制系统",
        "人体体温调节系统如何建模",
        "社交网络的信息传播动力学",
    ]
)
