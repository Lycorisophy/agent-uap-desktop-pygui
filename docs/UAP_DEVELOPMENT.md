# UAP 开发与运行指南

本文补充 [`UAP_LAYERING.md`](UAP_LAYERING.md) 的**落地配置**：canonical 路径、向量库环境、测试基线与记忆子系统相关说明。

## 1. 分层与 import（canonical）

| 能力 | 新代码应使用 | 兼容入口（过渡期） |
|------|----------------|----------------------|
| 提示词 | `uap.core.prompts` | `uap.prompts` |
| 项目知识库 / Milvus | `uap.core.memory.knowledge` | `uap.infrastructure.knowledge` |
| 智能体 Episode / 抽取进度（SQLite） | `uap.core.memory.agent_memory_persistence` | — |
| LLM | `uap.adapters.llm` | `uap.infrastructure.llm` |
| 项目存储 | `uap.persistence.project_store` | `uap.infrastructure.persistence` |

禁止：`persistence` → `interfaces`；新功能避免在 `interfaces` 内实现领域算法。

## 2. Milvus 运行环境

- **Windows**：PyPI 的 `milvus-lite` 常**无** `win_amd64` 轮子，本地文件模式可能不可用；代码在 `milvus_project_kb` 中会抛出明确错误提示。
- **推荐**：使用 **Docker** 运行 Milvus 2.x 独立服务，在设置中将「Milvus 后端」设为 `standalone`，`host`/`port` 指向容器（常见 `19530`）。
- **嵌入**：项目知识库与记忆片段写入依赖 **Ollama**（或配置中的 embedding），需与 `embedding.dimension` 一致。

## 3. 记忆子系统（与《智能体记忆系统设计方案参考指南》对齐）

- **Episode**：对话等原始单元落在 `_uap_index/agent_memory.sqlite`（与 `cards.sqlite` 同目录），供增量抽取锚点。
- **与文档知识库关系**：抽取后的文本片段写入**同一项目** Milvus collection（`kb_*`），`source_name` 以 `agent_mem|…` 前缀区分于上传文档；后续可演进为独立 `agent_memory` collection（见路线图风险节）。
- **统一检索**：`memory_search` 与 `search_knowledge` 共享底层语义检索，前者面向「文档 + 抽取记忆」的统一入口描述。

## 4. 测试基线

```bash
python -m pytest tests/ -q
```

合并前至少保证上述命令通过；关键路径：ReAct/Plan、意图分类、定时任务辅助流、卡片持久化、知识库检索。

## 5. 观测与安全（摘要）

- 结构化日志：优先带 `project_id` / `session_id`（见 `uap.common.observability`）。
- 密钥与 Token：勿写入仓库；向量元数据避免放敏感原文。
