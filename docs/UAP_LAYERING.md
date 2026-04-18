# UAP 后端分层与依赖规则

本文约定七域边界与 import 方向，与代码目录 `src/uap/` 对齐。

## 七域职责

| 域 | 包路径（主入口） | 职责 |
|----|------------------|------|
| 应用层 | `uap.interfaces`（桌面/API）、`uap.delivery`（对外门面转发） | PyWebView 暴露、HTTP 边界、薄编排；不实现领域算法 |
| 核心服务层 | `uap.core.*` | 行动模式、技能、记忆 RAG、提示词、上下文、约束/DST；可依赖 contract、persistence、adapters |
| 数据访问层 | `uap.persistence` | 项目目录、JSON/SQLite 等落盘；禁止依赖 `interfaces` |
| 防腐层 | `uap.adapters.*` | 第三方 HTTP/SDK（LLM、向量客户端等）；对外部形状做适配 |
| 公共实体 | `uap.contract` | 领域模型与 API 形状约定（见下节）；无 I/O |
| 公共工具 | `uap.common` | 无业务状态的工具函数 |
| 配置 | `uap.settings`（`uap.config` 为兼容入口） | Pydantic 配置模型与加载 |

## 允许的依赖方向

```
interfaces / delivery  →  core, application, contract, settings, persistence(只读编排)
core                   →  contract, persistence, adapters, settings, common
persistence            →  contract, settings
adapters               →  contract, settings
common                 →  （避免依赖 core / interfaces）
contract               →  （仅标准库 / pydantic，不依赖 adapters）
```

禁止：`persistence` → `interfaces`；`contract` → `adapters`。

## DTO / VO / PO 约定（Python）

不强制为每个概念建三套类，采用**命名空间 + 后缀/文档**区分：

- **领域对象**：`uap.project.models`、`uap.contract` 中导出的 Pydantic 模型（持久化与业务共用，相当于 PO + 领域模型合一）。
- **对外 API 形状**：优先在 `interfaces` mixin 返回的 `dict` 中组装；若需强类型，放在 `contract.api`（按需新增子模块）。
- **DTO**：跨层传递的只读结构，可用 Pydantic `model` 或 `TypedDict`，放在 `contract` 或紧邻调用方。

## 兼容与迁移

旧路径（如 `uap.infrastructure.llm`）在过渡期内以 **转发模块** 保留，新代码优先使用 `uap.adapters.llm`。

## 物理目录（canonical）

| 能力 | 实现位置 | 兼容入口（转发） |
|------|----------|------------------|
| 提示词资产 | `uap.core.prompts`（`assets/*.md`） | `uap.prompts` |
| 记忆 / 向量 | `uap.core.memory.knowledge`、`uap.core.memory.vector` | `uap.infrastructure.knowledge`、`uap.infrastructure.vector` |
| 技能系统 | `uap.core.skills` | `uap.skill` |
| ReAct / Plan / LangGraph | `uap.core.action.react`、`uap.core.action.plan` | `uap.react`、`uap.plan` |
| LLM 客户端 | `uap.adapters.llm` | `uap.infrastructure.llm`、`uap.llm` |
| 项目存储 | `uap.persistence` | `uap.infrastructure.persistence`、`uap.project.project_store` |
