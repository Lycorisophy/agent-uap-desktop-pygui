# UAP - 复杂系统未来势态量化预测统一智能体

> Unified Agent for Quantifying Future States of Complex Systems

## 项目介绍

UAP 是一款**纯客户端桌面应用**，旨在帮助用户对复杂系统进行建模和未来势态预测。用户可以通过对话或导入文档的方式让智能体自动提取系统模型，然后系统会定时预测复杂系统的未来行为。

### 核心特性

- **对话建模**：通过自然语言对话描述复杂系统，智能体自动提取数学模型
- **文档导入**：支持导入文档自动提取系统结构
- **定时预测**：可配置预测频率（默认每小时）和预测时长（默认3天）
- **本地优先**：所有数据存储在本地，无需网络（除连接大模型外）

### 仓库布局与第三方资产

- **产品代码**：[`src/uap/`](src/uap/)（分层 Python 包）、[`src/app.py`](src/app.py)（桌面入口）、[`resources/web/`](resources/web/)（内置前端静态资源）。
- **`.minimax/`**：MiniMax 等**外部技能/脚本资产**，**不属于 UAP 运行时依赖**；默认已写入 [`.gitignore`](.gitignore)，避免与产品代码混搜。若需在本地使用，可单独克隆到仓库外并自行挂载，或按需改为 [git submodule](https://git-scm.com/book/en/v2/Git-Tools-Submodules)。
- **配置样例**：[`config/`](config/) 下的 `uap.example.yaml` 等。

更完整的分层约定见 [`docs/architecture/folder-conventions.md`](docs/architecture/folder-conventions.md)。

### 技术架构

| 层级 | 技术选型 | 说明 |
|------|----------|------|
| 桌面框架 | PyWebView | 轻量级跨平台桌面应用框架 |
| AI推理 | Ollama (本地) | 支持Llama3、Qwen等大语言模型 |
| 嵌入模型 | Ollama Embeddings | 本地向量嵌入 |
| 数据存储 | SQLite + JSONL | 内置数据库，无需额外搭建 |
| 向量检索 | sqlite-vss (可选) | SQLite向量扩展，轻量级方案 |
| 预测引擎 | Koopman/PESM/PINN | 复杂系统动力学预测 |

### 存储设计原则

> **本地优先，避免用户额外搭建服务**

| 数据类型 | 存储方案 | 理由 |
|----------|----------|------|
| 项目元数据 | SQLite | 关系型数据，ACID，文件型 |
| 系统模型 | JSON文件 | 结构化数据，便于编辑 |
| 预测结果 | JSONL | 追加写入，适合时序数据 |
| 对话历史 | JSONL | 同上 |
| 向量索引 | sqlite-vss | SQLite扩展，轻量 |
| 缓存 | 本地JSON | 简单高效 |

---

## LLM 与建模相关配置

桌面端连接大模型与建模行为主要由 **[`config/uap.example.yaml`](config/uap.example.yaml)**（复制为 `uap.yaml` 或用户目录下的 `uap.local.yaml`）与 **[`src/uap/config.py`](src/uap/config.py)** 中的 **`LLMConfig`**、**`AgentConfig`** 驱动。

| 配置块 / 字段 | 说明 |
|---------------|------|
| **`llm.provider`** | 如 `ollama`、`minimax`、`deepseek`、`qwen` 等；非 Ollama 时强制走 OpenAI 兼容 HTTP。 |
| **`llm.base_url`** | 厂商 API 根地址（须与控制台文档一致，例如 MiniMax 控制台给出的网关）。 |
| **`llm.model`** | 控制台注册的 **精确 model id**（勿填带空格的展示名）。 |
| **`llm.api_key`** | 云端厂商密钥；本地 Ollama 可为 `null`。 |
| **`llm.api_mode`** | Ollama 可用 `native`；其余厂商一般为 `openai`。 |
| **`agent.modeling_agent_mode`** | 默认 `react` / `plan` / `auto`；前端每轮选择的模式优先。 |
| **`agent.react_max_steps_default`** | 单次用户发送内 ReAct 最大决策轮数（1–32，默认 8）。 |
| **`agent.react_max_time_seconds`** | ReAct 墙钟超时（秒）。 |
| **`agent.plan_max_time_seconds`** | Plan 墙钟超时（秒）。 |
| **`agent.ask_user_card_timeout_seconds`** | 建模追问卡片过期秒数。 |

**MiniMax**：`llm.model` 须与控制台 **注册 model id** 完全一致（勿用带空格的展示名）；`llm.base_url` 与控制台文档一致。代码内默认示例见 [`src/uap/config.py`](src/uap/config.py) 中 `llm_provider_presets()` 的 `minimax` 项。

**冒烟与回归**：见 [`docs/MODELING_SMOKE_CHECKLIST.md`](docs/MODELING_SMOKE_CHECKLIST.md) 与 [`docs/MODELING_DELIVERY_PLAN.md`](docs/MODELING_DELIVERY_PLAN.md) 文首「阶段完成情况」中的 pytest 命令。

**领域数据（CSV 等）**：见 [`docs/MODELING_DOMAIN_DATA.md`](docs/MODELING_DOMAIN_DATA.md)。

---

## 开发进度

### ✅ 已完成

| 模块 | 状态 | 说明 |
|------|------|------|
| 项目基础结构 | ✅ | 目录组织、配置文件 |
| 核心数据模型 | ✅ | Project、SystemModel、PredictionTask |
| 项目存储模块 | ✅ | SQLite + JSONL 持久化 |
| 服务层 | ✅ | ProjectService、PredictionService |
| 任务调度器 | ✅ | 定时预测任务执行 |
| 主入口与API | ✅ | PyWebView 集成 |
| 前端基础结构 | ✅ | HTML/CSS/JS 界面 |
| LLM集成 | ✅ | Ollama客户端、模型提取器 |
| 技能系统 | ✅ | DST追踪、技能生成器、管理器、执行器 |
| 预测引擎 | ✅ | Koopman/Monte Carlo/Simulation |
| 向量检索 | ✅ | sqlite-vss集成、语义搜索、RAG支持 |
| 文档导入解析 | ✅ | PDF/Word/Markdown解析、LLM增强提取 |
| 预测可视化 | ✅ | 预测视图轨迹 SVG、置信带与异常竖线标注 |
| 预测结果分析 | ✅ | 基于 `PredictionResult` 的熵/湍流卡片与异常摘要（`predictionAnalysis` 区） |
| 高级建模工具 | ✅ | 变量表格编辑、关系表格、`save_model`；力导向关系图（与实体图边规则一致） |

### 🔄 进行中

### ⏳ 待开发

当前无必选排期项；可按产品需求在此增列。

---

## 开发规范

### 1. 关键代码写注释

所有核心模块和公共函数必须包含文档字符串（docstring）：

```python
class PredictionService:
    """
    预测服务类
    
    负责执行复杂系统的未来状态预测，支持多种预测方法。
    """
    
    def run_prediction(self, project: Project, config: PredictionConfig) -> PredictionResult:
        """
        执行预测任务
        
        Args:
            project: 项目实体，包含系统模型
            config: 预测配置，包含频率和时长
            
        Returns:
            PredictionResult: 预测结果，包含轨迹、置信区间、异常检测
            
        Raises:
            ValueError: 当模型为空时抛出
        """
        pass
```

### 2. 开发完检查开发进度

每次完成功能开发后，必须更新本文件「开发进度」章节：
- 在对应模块后添加 ✅ 表示完成
- 新增功能添加新行，标注 🔄 表示进行中
- 包含简要说明

### 3. Git提交规范

使用标准Angular提交格式：

```
<type>(<scope>): <subject>

<body>

<footer>
```

**Type类型**：
| Type | 说明 |
|------|------|
| feat | 新功能 |
| fix | 修复bug |
| docs | 文档更新 |
| style | 代码格式（不影响功能） |
| refactor | 重构（不是新功能也不是修复） |
| perf | 性能优化 |
| test | 测试相关 |
| chore | 构建/工具相关 |

**示例**：
```
feat(models): 添加SystemModel数据模型

- 新增Variable变量定义
- 新增Relation关系定义
- 新增Constraint约束定义

Closes #123
```

```
fix(scheduler): 修复任务重复执行问题

当trigger_type为INTERVAL时，正确计算下次执行时间
```

### 4. 先设计再开发

复杂功能开发前必须：
1. 在 `docs/design/` 目录下创建设计文档
2. 包含数据结构、流程图、接口定义
3. 评审通过后再编码

---

## 文档索引

### 项目文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 本文件 | `README.md` | 项目总览和开发规范 |
| 需求报告 | `复杂系统未来势态量化预测统一智能体可行性研究与总体实施方案报告.md` | 完整需求分析和方案设计 |
| 交接说明 | `handoff-ruyi72-to-uap.md` | 从如意72到UAP的技术交接 |
| 架构总结 | `ruyi72-architecture-summary.md` | 如意72架构参考 |
| **最新交接** | `HANDOFF-2026-04-15.md` | **Matrix Agent详细交接（含待完成工作）** |

### 设计指南 (`docs/设计指南/`)

| 文档 | 说明 |
|------|------|
| AI智能体记忆体系设计指南.md | 三层记忆架构、事实分级、事件管理 |
| 记忆知识系统数据库选型分析第二版.md | 存储组件选型（参考，本地化时需调整） |
| 系统数据存储方案.md | 完整数据存储架构设计 |
| AI智能体技能工具系统设计指南.md | MCP协议、Function Calling、工具安全 |
| AI智能体技能工具系统扩展设计指南-自动技能工匠.md | 技能自动生成模块 |
| AI智能体行动模式设计指南.md | ReAct/Plan/Workflow等八种行动模式 |

### 设计指南分类索引

**记忆与存储类**
- `AI智能体记忆体系设计指南.md` - 核心参考
- `记忆知识系统数据库选型分析第二版.md` - 存储选型参考
- `系统数据存储方案.md` - 存储架构总览

**技能与工具类**
- `AI智能体技能工具系统设计指南.md` - 工具调用协议
- `AI智能体技能工具系统扩展设计指南-自动技能工匠.md` - 技能生成

**行动模式类**
- `AI智能体行动模式设计指南.md` - Agent执行模式

### 源码与资源目录（概要）

```
agent-uap-desktop-pygui/
├── pyproject.toml            # 包元数据与依赖（推荐 pip install -e .）
├── requirements-base.txt   # 核心依赖列表
├── requirements-optional.txt # 可选依赖（向量/中间件等；LangChain 已为主依赖）
├── resources/web/          # 内置前端（HTML/CSS/JS）
├── config/                 # 配置样例
├── docs/                   # 文档与设计指南
└── src/
    ├── app.py              # PyWebView 桌面入口
    └── uap/
        ├── api.py          # 兼容：转发至 interfaces
        ├── interfaces/   # 表现层：UAPApi 与按领域拆分的 mixin
        ├── application/    # 应用层：项目/预测用例编排
        ├── infrastructure/# 基础设施：持久化、LLM、向量、调度
        ├── domain/         # 领域扩展占位（约定见 docs/architecture）
        ├── project/        # 项目领域模型（models；store 为兼容 shim）
        ├── llm/            # 兼容 shim → infrastructure.llm
        ├── vector/         # 兼容 shim → infrastructure.vector
        ├── scheduler/      # 兼容 shim → infrastructure.scheduler
        ├── service/        # 兼容 shim → application
        ├── react/ …        # ReAct / DST 等（逐步向 domain 收敛）
        └── …
```

更完整的分层与依赖规则见 [`docs/architecture/folder-conventions.md`](docs/architecture/folder-conventions.md)。

---

## 快速开始

### 环境要求

- Python 3.10+
- Ollama (用于本地LLM)
- Windows/macOS/Linux

### 安装依赖

推荐（可编辑安装，与 IDE 分析一致）：

```bash
pip install -e .
```

或仅安装核心依赖文件：

```bash
pip install -r requirements-base.txt
```

### 配置Ollama

确保Ollama运行中，并下载所需模型：

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

### 运行应用

```bash
cd src
python app.py
```

---

## 本地存储说明

### 为什么不用MySQL/ES/Neo4j？

作为**纯客户端应用**，我们的原则是：

1. **用户无需额外搭建服务** - MySQL/ES/Neo4j需要单独安装和配置
2. **简化部署** - 用户只需安装应用，双击运行
3. **数据主权** - 所有数据存储在用户本地目录

### SQLite的优势

- **零配置**：数据库就是一个文件
- **ACID事务**：数据安全有保障
- **成熟稳定**：生产级数据库
- **跨平台**：Windows/macOS/Linux通用
- **性能足够**：对于桌面应用场景完全足够

### 向量搜索方案

使用 `sqlite-vss`（SQLite向量扩展）：
- 轻量级，无需额外服务
- 支持ANN向量检索
- 与SQLite无缝集成

---

## 贡献指南

1. Fork本仓库
2. 创建特性分支 (`git checkout -b feat/your-feature`)
3. 遵循开发规范编写代码
4. 提交代码 (`git commit -m 'feat(scope): add some feature'`)
5. 推送到分支 (`git push origin feat/your-feature`)
6. 创建Pull Request

---

*最后更新：2026-04-15*
