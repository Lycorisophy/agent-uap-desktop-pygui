# UAP 目录与分层约定

本文说明仓库内 **Python 包布局、依赖方向与兼容 shim**，便于在企业级协作中统一放置新代码。

## 1. 顶层布局

| 路径 | 职责 |
|------|------|
| `src/app.py` | 桌面进程入口：日志、窗口、`js_api`、静态资源路径解析 |
| `src/uap/` | 可安装的 Python 包 `uap`（见 `pyproject.toml`） |
| `resources/web/` | 内置前端静态资源（HTML/CSS/JS），与 Python 源码分离 |
| `config/` | 示例与默认 YAML |
| `docs/` | 设计说明与本文件 |
| `.minimax/` | **非产品依赖**的外部技能资产（默认 `.gitignore`，见根 `README`） |

## 2. `uap` 包内分层

### 2.1 `uap.interfaces`（表现层 / Harness）

- **职责**：PyWebView 暴露给前端的 API；参数校验、序列化、组合调用应用服务。
- **入口**：`uap.interfaces.api.uap_api.UAPApi`（由多个 mixin 组成，避免单文件过大）。
- **兼容**：`from uap.api import UAPApi` 仍可用。

### 2.2 `uap.application`（应用层）

- **职责**：用例编排（项目生命周期、建模对话、预测执行、配置刷新等）。
- **主要模块**：`project_service.py`、`prediction_service.py`。
- **兼容**：`from uap.service import ProjectService` 仍可用（`uap.service` 为 re-export）。

### 2.3 `uap.infrastructure`（基础设施层）

- **职责**：文件系统持久化、HTTP LLM 客户端、向量检索、后台调度等 **可替换实现**。
- **子包**：
  - `persistence`：`ProjectStore`、项目目录布局
  - `llm`：Ollama、模型抽取
  - `vector`：嵌入与语义检索
  - `scheduler`：定时任务
- **兼容**：`uap.llm`、`uap.vector`、`uap.scheduler` 及 `uap.project.project_store` 仍为 **shim**，旧 import 不必一次性改完。

### 2.4 `uap.domain`（领域扩展）

- **职责**：纯领域逻辑与类型的增量归宿；与框架无关的业务规则可放此处。
- **现状**：`react`、`skill`、`project.models` 等仍在历史路径；新代码优先在本包新建子模块，避免继续增大 `interfaces`/`application`。

### 2.5 其余历史包

- `uap.project`：项目与系统模型 **领域模型**（`models.py`）；`project_store` 已迁至 `infrastructure.persistence` 并在此 re-export。
- `uap.react`、`uap.card`、`uap.engine` 等：保持模块边界清晰，逐步向 `domain` / `infrastructure` 收敛即可。

## 3. 依赖方向（必须遵守）

```
interfaces  →  application  →  domain（模型/规则）
                    ↓
              infrastructure
```

- **禁止**：`infrastructure` 依赖 `interfaces`；`domain` 依赖 `interfaces`。
- **允许**：`application` 同时依赖 `domain` 类型与 `infrastructure` 实现。

## 4. 依赖安装

- **默认**：`pip install -e .`（见 `pyproject.toml` 的 `[project.dependencies]`）。
- **可选**：`pip install -e ".[langchain,vector,legacy-db,dev]"` 或 `requirements-optional.txt`。

## 5. 与 IDE 分析

- `pyrightconfig.json` 中 `executionEnvironments.root` 为 `src`，保证 `import uap` 解析正确。
