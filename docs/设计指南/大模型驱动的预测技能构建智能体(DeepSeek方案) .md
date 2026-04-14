# Project Chimera：大模型驱动的预测技能构建智能体(DeepSeek方案)  
## —— 系统架构与交互设计方案  

| 文档版本 | 1.0 |
| :--- | :--- |
| 编制日期 | 2026年4月14日 |
| 核心设计理念 | **大模型是教练，小模型是运动员；用户是决策者，卡片是信任锁。** |

---

## 一、系统定位与核心差异

| 对比维度 | 传统预测平台 | 本系统（Chimera） |
| :--- | :--- | :--- |
| **建模方式** | 数据科学家手动选模型、调参 | **大模型根据用户意图自动生成小模型** |
| **用户角色** | 消费者（只看结果） | **导演**（引导方向，确认关键节点） |
| **信任机制** | 黑箱输出 | **关键步骤弹出解释卡片，用户显式确认** |
| **知识沉淀** | 模型文件散落各处 | **每次任务自动生成可复用的“技能包”** |

---

## 二、整体架构设计

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          用户交互层（Web / 桌面）                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │              对话流（自然语言） + 确认卡片（结构化选择）             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────┬───────────────────────────────────────┘
                                  │ WebSocket（实时双向）
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                       智能体核心（Python + FastAPI）                       │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    对话状态追踪器（DST）                           │   │
│  │          槽位：目标/区域/时长/数据源/方法偏好/精度要求              │   │
│  └───────────────────────────────┬─────────────────────────────────┘   │
│                                  ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                  技能规划大模型（GPT-5 / Claude-4）                 │   │
│  │   • 将槽位转换为原子技能链   • 识别需要用户确认的决策点              │   │
│  └───────────────────────────────┬─────────────────────────────────┘   │
│                                  ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      卡片生成器（ConfirmationCard）                │   │
│  │   生成结构化选项：数据源选择 / 模型类型选择 / 高风险操作授权         │   │
│  └───────────────────────────────┬─────────────────────────────────┘   │
│                                  ▼                                      │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    技能执行引擎（Skill Executor）                   │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐   │   │
│  │  │ 原子技能库    │  │ 模型训练工坊  │  │  技能包仓库           │   │   │
│  │  │（数据/特征/训练）│  │（Koopman/NODE）│  │ （用户生成的技能模板） │   │   │
│  │  └──────────────┘  └──────────────┘  └──────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 三、核心交互模式：对话 + 卡片确认

### 3.1 对话状态追踪（DST）槽位定义

| 槽位 | 类型 | 说明 | 示例 |
| :--- | :--- | :--- | :--- |
| `task_type` | 枚举 | 预测/分类/异常检测/归因分析 | `"forecast"` |
| `target` | 字符串 | 预测目标变量 | `"降水量"` |
| `location` | GeoJSON | 空间范围 | `{"type":"Polygon",...}` |
| `time_horizon` | 字符串 | 预测时长 | `"未来72小时"` |
| `data_preference` | 枚举 | `"自动获取公开数据"` / `"用户上传"` | `"auto"` |
| `model_complexity` | 枚举 | `"快速"` / `"高精度"` / `"可解释"` | `"interpretable"` |
| `output_format` | 枚举 | `"结论"` / `"图表"` / `"详细数据"` | `"chart"` |

### 3.2 确认卡片类型

| 卡片类型 | 触发时机 | 卡片内容示例 | 用户可操作 |
| :--- | :--- | :--- | :--- |
| **数据源选择卡** | 系统检测到多个可用数据源 | "您希望使用：A) ERA5（全球免费，精度0.25°） B) GFS（预报，精度0.5°） C) 上传自己的CSV" | 单选 + 确认 |
| **方法选择卡** | 任务存在多种可行算法 | "对于台风路径预测，我推荐：A) Koopman算子（可解释性强，适合分析不确定性）B) Neural ODE（精度更高，但训练较慢）。您倾向于？" | 单选 + 确认 |
| **高风险操作授权卡** | 需要调用付费API、写文件、长时间训练 | "接下来将调用DarkSky API获取数据（约消耗0.5美元），并训练一个模型（预计3分钟）。是否继续？" | 确认 / 取消 |
| **结果确认与保存卡** | 任务执行完成 | "预测已完成。结果摘要：未来24小时降水概率45%。您希望：A) 保存此技能供以后复用 B) 仅下载结果 C) 继续追问" | 多选 + 确认 |

### 3.3 交互流程示例

```
用户：帮我预测一下上海明天会不会下大雨。

智能体：
[状态更新] target=降水强度，location=上海，time=未来24h
[卡片弹出]
┌─────────────────────────────────────────────────┐
│  📊 数据源选择                                   │
│  ─────────────────────────────────────────────  │
│  为了预测上海降水，我找到了两个可用数据源：        │
│  ○ GFS全球预报（免费，空间精度约25km）            │
│  ○ 本地气象站实时观测（需您提供站点ID或授权访问） │
│  ─────────────────────────────────────────────  │
│              [确认选择]  [换一个]                │
└─────────────────────────────────────────────────┘

用户点击“确认选择”（假设选了GFS）

智能体：
[卡片弹出]
┌─────────────────────────────────────────────────┐
│  🧠 预测方法推荐                                 │
│  ─────────────────────────────────────────────  │
│  短期降水预测，我建议使用数值预报直接提取（最快）。 │
│  如果您关心不确定性范围，我可以用历史数据训练一个   │
│  概率模型（耗时约2分钟）。                        │
│  ○ 快速查询（10秒）                              │
│  ○ 概率建模（2分钟，显示置信区间）                │
│  ─────────────────────────────────────────────  │
│              [确认]  [详细对比]                  │
└─────────────────────────────────────────────────┘

用户选择“概率建模”

智能体：
[执行技能链：fetch_gfs → extract_precip → historical_analog → ensemble]
[推送进度消息]

完成后：
[卡片弹出]
┌─────────────────────────────────────────────────┐
│  ✅ 预测完成                                     │
│  ─────────────────────────────────────────────  │
│  上海（浦东）明日降水概率：45%（小雨量级）         │
│  不确定性区间：30%～60%                          │
│  ─────────────────────────────────────────────  │
│  [查看详细图表]  [保存此技能]  [追问]            │
└─────────────────────────────────────────────────┘
```

---

## 四、原子技能库设计

原子技能是系统可执行的**最小功能单元**，每个技能都是独立的 Python 函数/类，并带有标准化的元数据描述，供大模型规划时使用。

### 4.1 原子技能元数据规范

```python
@dataclass
class AtomicSkillMeta:
    skill_id: str          # 唯一标识，如 "fetch_era5"
    name: str              # 显示名称
    description: str       # 自然语言描述（供大模型理解）
    category: str          # data / preprocessing / feature / model / postprocess
    input_schema: dict     # JSON Schema 格式的输入参数规范
    output_schema: dict    # 输出格式规范
    estimated_time: int    # 预估执行时间（秒）
    cost: float            # 预估成本（美元）
    requires_confirmation: bool  # 是否需要用户确认
```

### 4.2 核心原子技能清单

#### 数据获取类
| skill_id | 描述 | 需确认 |
| :--- | :--- | :--- |
| `fetch_era5` | 从 CDS API 获取 ERA5 再分析数据 | 否 |
| `fetch_gfs` | 从 NOAA NOMADS 获取 GFS 预报 | 否 |
| `fetch_station` | 从本地/第三方 API 获取气象站观测 | 是（若涉及授权） |
| `upload_csv` | 引导用户上传 CSV 并解析 | 是 |

#### 数据预处理类
| skill_id | 描述 |
| :--- | :--- |
| `interpolate_missing` | 插值填补缺失值 |
| `outlier_filter` | 基于 IQR 或 Z-score 剔除异常值 |
| `temporal_aggregate` | 时间聚合（小时→日） |
| `spatial_regrid` | 空间重网格化 |

#### 特征工程类
| skill_id | 描述 |
| :--- | :--- |
| `delay_embedding` | Takens 延迟嵌入（生成用于 Koopman 的 Hankel 矩阵） |
| `eof_decomposition` | EOF/PCA 降维 |
| `extract_temporal_features` | 提取月份、小时等时间特征 |
| `calculate_derivatives` | 数值微分（用于 Neural ODE） |

#### 模型训练类（大模型训练小模型的核心）
| skill_id | 描述 | 需确认 |
| :--- | :--- | :--- |
| `train_koopman_dmd` | 训练动态模式分解（DMD）模型 | 否 |
| `train_koopman_edmd` | 训练扩展 DMD（使用字典函数） | 是（字典选择需确认） |
| `train_neural_ode` | 训练神经常微分方程模型 | 是（网络结构确认） |
| `train_pinn` | 训练物理信息神经网络 | 是（方程选择确认） |
| `train_ensemble` | 训练简单集合预报模型 | 否 |

#### 预测与评估类
| skill_id | 描述 |
| :--- | :--- |
| `predict_deterministic` | 确定性轨迹预测 |
| `predict_probabilistic` | 概率预测（置信区间） |
| `evaluate_forecast` | 计算 RMSE/MAE/CRPS 等指标 |
| `plot_trajectory` | 生成预测轨迹图 |
| `plot_uncertainty` | 生成不确定性云图 |

---

## 五、技能规划大模型：从意图到技能链

### 5.1 规划提示词设计

```
你是一个气象预测智能体的规划器。你的任务是根据对话状态，从可用技能库中选择合适的原子技能，并排列成执行链。

【当前对话状态】
- 任务类型：{task_type}
- 预测目标：{target}
- 空间范围：{location}
- 时间范围：{time_horizon}
- 数据偏好：{data_preference}
- 精度要求：{model_complexity}

【可用原子技能列表】
{available_skills_json}

【输出要求】
1. 生成一个技能链（按执行顺序排列的 skill_id 列表）
2. 识别出需要用户确认的决策点（如存在多个可选数据源、模型选择分歧等），并生成对应的确认卡片内容。
3. 为整个任务生成一个简短的自然语言摘要，用于向用户解释接下来将执行的操作。

输出格式（严格JSON）：
{
  "skill_chain": ["skill_id_1", "skill_id_2", ...],
  "confirmation_cards": [
    {
      "card_type": "data_source_selection",
      "title": "数据源选择",
      "options": [...],
      "default": "..."
    }
  ],
  "summary": "我将从ERA5获取历史数据，使用Koopman算子训练模型，然后预测未来72小时的降水概率。整个过程约需3分钟。"
}
```

### 5.2 动态训练小模型的实现

当技能链中包含 `train_*` 类技能时，执行引擎会：

1. **根据用户确认的选项**，动态生成训练配置文件。
2. **调用底层训练脚本**（如 PyTorch 脚本），训练一个小型专用模型。
3. **将训练好的模型文件存入临时存储**，并注册为一个新的临时技能（供后续预测调用）。

```python
# 伪代码示例
class TrainKoopmanSkill:
    def execute(self, params):
        # 1. 准备数据
        data = load_data(params['data_path'])
        
        # 2. 根据用户选择的字典类型构建 eDMD
        if params['dict_type'] == 'polynomial':
            dict_func = polynomial_library(degree=2)
        elif params['dict_type'] == 'rbf':
            dict_func = rbf_library(centers=100)
        
        # 3. 训练模型
        koopman_model = edmd(data, dict_func)
        
        # 4. 保存模型并注册为临时技能
        model_id = save_model(koopman_model)
        register_temporary_skill(f"predict_with_{model_id}", model_id)
        
        return {"model_id": model_id, "eigenvalues": koopman_model.eigs}
```

---

## 六、技能包仓库：知识沉淀与复用

### 6.1 技能包定义

一个**技能包**是对一次成功任务的完整封装，包含：

- **技能链**：使用的原子技能序列及参数
- **训练好的模型文件**（如果有）
- **元数据**：适用场景、性能指标、创建时间
- **自然语言描述**：供大模型在后续对话中检索和推荐

### 6.2 技能包的存储结构

```json
{
  "skill_package_id": "pkg_typhoon_koopman_v1",
  "name": "西北太平洋台风路径概率预测",
  "description": "使用ERA5历史台风数据和Koopman算子，预测未来72小时路径及不确定性。",
  "tags": ["台风", "概率预测", "Koopman"],
  "created_at": "2026-04-14T10:30:00Z",
  "skill_chain": [
    {"skill_id": "fetch_era5", "params": {...}},
    {"skill_id": "delay_embedding", "params": {"dim": 10, "tau": 6}},
    {"skill_id": "train_koopman_edmd", "params": {"dict_type": "rbf"}},
    {"skill_id": "predict_probabilistic", "params": {"horizon": 72}}
  ],
  "model_artifacts": {
    "koopman_model": "s3://models/koopman_typhoon_20260414.pt",
    "scaler": "s3://models/scaler_typhoon.pkl"
  },
  "performance": {
    "rmse_24h": 45.2,
    "crps": 0.12
  }
}
```

### 6.3 技能复用流程

当用户再次提出类似需求时，大模型首先检索技能包仓库：

> *"我注意到您之前保存过一个'台风路径概率预测'技能，适用于西北太平洋区域。是否直接使用它来预测新台风？"*

用户确认后，系统直接加载技能包中的模型和参数，跳过训练步骤，快速执行预测。

---

## 七、技术选型建议

| 组件 | 推荐选型 | 理由 |
| :--- | :--- | :--- |
| **后端框架** | FastAPI (Python) | 异步支持好，适合 WebSocket 流式通信；与 Python 科学生态无缝集成 |
| **推理大模型** | Claude-4 / GPT-5 API | 意图理解与规划能力强，支持结构化输出 |
| **向量数据库** | LanceDB（嵌入式） | 轻量、无需单独部署，适合存储技能包向量索引 |
| **关系数据库** | SQLite（单机）/ PostgreSQL（生产） | SQLite 适合初期快速迭代 |
| **任务队列** | Celery + Redis | 处理耗时训练任务 |
| **模型训练后端** | PyTorch + PyKoopman / torchdiffeq | 工业标准，社区活跃 |
| **前端框架** | Next.js + Tailwind CSS + shadcn/ui | 快速构建高质量确认卡片与仪表盘 |
| **可视化** | Plotly.js / D3.js | 支持复杂的科学图表（相图、不确定性云图） |
| **通信协议** | WebSocket（主）+ REST（辅） | WebSocket 用于实时对话与进度推送 |

---

## 八、关键流程伪代码

```python
class ChimeraAgent:
    def __init__(self):
        self.dst = DialogueStateTracker()
        self.planner = SkillPlanner(llm=ClaudeModel())
        self.executor = SkillExecutor()
        self.card_generator = ConfirmationCardGenerator()
        self.skill_repo = SkillPackageRepository()

    async def handle_user_message(self, user_input: str, websocket: WebSocket):
        # 1. 更新对话状态
        state = self.dst.update(user_input)
        await websocket.send_json({"type": "state_update", "state": state.dict()})

        # 2. 检查是否需要确认卡片
        pending_cards = self.dst.get_pending_confirmations(state)
        if pending_cards:
            for card in pending_cards:
                await websocket.send_json({"type": "confirmation_card", "card": card})
            return  # 等待用户确认

        # 3. 规划技能链
        skill_chain, new_cards, summary = self.planner.plan(state)
        
        # 4. 如果有新卡片，先发送让用户确认
        if new_cards:
            for card in new_cards:
                await websocket.send_json({"type": "confirmation_card", "card": card})
            return

        # 5. 发送执行摘要
        await websocket.send_json({"type": "execution_summary", "summary": summary})

        # 6. 执行技能链（带进度推送）
        results = await self.executor.run(skill_chain, 
                                          progress_callback=lambda p: websocket.send_json(p))

        # 7. 发送最终结果与保存选项
        await websocket.send_json({
            "type": "result",
            "data": results,
            "save_options": ["save_skill_package", "download_data", "continue_chat"]
        })

    async def handle_card_response(self, response: dict, websocket: WebSocket):
        # 用户对卡片的确认结果更新到状态中
        self.dst.apply_confirmation(response)
        # 继续流程
        await self.handle_user_message("__internal_continue__", websocket)
```

---

## 九、总结

这套名为 **Chimera** 的独立智能体应用设计，将“大模型训练小模型”的愿景落地为可交互的现实。其核心特征包括：

1. **对话式意图澄清**：通过 DST 槽位逐步收敛用户需求，无需用户具备专业知识。
2. **卡片式关键确认**：在数据源选择、方法决策、高风险操作等节点弹出结构化卡片，建立用户信任。
3. **原子技能+动态规划**：大模型根据意图自动编排技能链，实现从数据到预测的全流程自动化。
4. **技能包沉淀复用**：每次成功任务都转化为可复用的知识资产，系统能力随使用增长。

下一步建议：先实现一个最小可行产品（MVP），包含 5-8 个核心原子技能（如数据获取、Koopman 训练、预测绘图）和基础的对话卡片交互，在真实用户测试中迭代优化。