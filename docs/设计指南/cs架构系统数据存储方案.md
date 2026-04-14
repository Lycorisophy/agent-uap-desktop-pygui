# jingu3 AI Agent系统数据存储方案（终版）

> **文档定位**：在已选技术栈上给出**全站数据落点**的统一视图：记忆与知识系统严格对齐 [记忆知识系统数据库选型分析第二版.md](./记忆知识系统数据库选型分析第二版.md)；用户、对话、技能元数据与关联关系对齐 [服务架构.md](../服务架构.md) 与 [技能系统设计](../workspace/skill-system-design.md)；技能**完整文件包**落在 **MinIO**。  
> **说明**：下文包含目标形态与当前仓库已实现子集的对照；实施按路线图分阶段落地，不要求一次性建齐所有索引与表。

---

## 1. 存储组件总览

| 组件 | 角色 | 本方案中的主要职责 |
|------|------|-------------------|
| **MySQL** | 结构化枢纽、ACID | 用户、会话与消息主数据；技能与订阅；Fact/记忆条目元数据；横切表（定时任务、HITL、对话状态等）；审计与配置 |
| **Redis** | 低延迟、TTL | 工作记忆（STM）、会话热上下文、限流与分布式锁、热点缓存（含可选 API 缓存） |
| **Elasticsearch** | 全文与时序 | **Event** 与可检索对话片段的主内容库；关键词检索、聚合、ILM |
| **Milvus** | 向量 ANN | **Event** 语义向量；可与 **Fact/记忆条目** 向量并存（不同 collection 或分区字段区分） |
| **Neo4j** | 图遍历 | Event 间关系（因果、先后、引用），GraphRAG |
| **MinIO** | 对象存储 | **技能完整包**（SKILL.md、脚本、资源）；用户附件与生成物（与 ES `attachments` 联动） |

**记忆域设计原则**：以第二版为准——**ES 存事件全文**，**Milvus 存事件向量**，**Neo4j 存轻量关系**，**MySQL 存 Fact/会话等结构化元数据**；与第二版「检索与推理分离」一致。

---

## 2. 逻辑架构（数据流）

```mermaid
flowchart TB
  subgraph app [应用层]
    API[REST_SSE_WS]
  end
  subgraph cache [Redis]
    STM[STM与上下文]
    RL[限流锁]
  end
  subgraph vector [Milvus]
    MV[Event与记忆向量]
  end
  subgraph search [Elasticsearch]
    ES[events与检索扩展]
  end
  subgraph graph [Neo4j]
    NG[Event关系]
  end
  subgraph sql [MySQL]
    MY[用户对话技能记忆元数据]
  end
  subgraph obj [MinIO]
    SK[技能包与附件]
  end
  API --> cache
  API --> sql
  API --> search
  API --> vector
  API --> graph
  API --> obj
  search --> vector
  vector --> search
  sql --> SK
```

**写入主路径（记忆 Event，与第二版 4.2 一致）**

1. 文本嵌入 → **Milvus**（记录与 `event_id` 对齐的向量）。  
2. 完整 Event JSON → **Elasticsearch**（含 `vector_id` / `event_id` 等外键字段）。  
3. 可选：关系边 → **Neo4j**（异步）。  
4. 结构化变更 → **MySQL**（Fact、会话元数据等）。  
5. 大文件 → **MinIO**，URL 写入 ES 文档 `metadata.attachments` 或业务约定字段。

**读取主路径**：语义分支走 Milvus → 得 `event_id` → ES 取全文；关键词分支直查 ES；关系分支查 Neo4j；配置与用户技能查 MySQL。

---

## 3. MySQL：统一逻辑模型

MySQL 划分为 **身份与对话**、**技能市场**、**记忆与 Fact（结构化）**、**横切与运维** 四类。主键风格允许 **CHAR(36) UUID**（用户/会话/技能）与 **BIGINT**（部分历史表）并存，新建表建议统一 UUID 或统一雪花，由实现阶段选定。

### 3.1 用户与对话（与服务架构对齐）

承载「用户信息、用户对话」的主数据。

| 表 | 用途 | 要点 |
|----|------|------|
| **users** | 用户账号 | `id`, `username`, `password_hash`, `created_at` 等 |
| **conversations** | 会话头 | `user_id` 外键，`title`, `updated_at`，索引 `idx_user_updated` |
| **messages** | 消息行 | `conversation_id`, `role`, `content`, **`embedding_ref`**（指向向量侧点 ID 或 Milvus 主键策略）, `created_at` |
| **tool_calls**（可选） | 工具调用记录 | 挂 `message_id`，与第二版 Event 中 `tool_calls` 可互证 |

**与第二版的关系**：第二版示例中的 **sessions** 在统一方案中**归并为 conversations**（语义等价：一次用户会话容器）。若需兼容旧字段名，可通过视图或迁移脚本映射。

**与 Elasticsearch**：可将 `messages` 或聚合后的 **Event** 异步同步到 ES 索引，用于「历史关键词检索」；MySQL 仍为对话的权威来源（OLTP）。

### 3.2 技能：元数据在 MySQL，文件在 MinIO（与技能系统设计对齐）

| 表 | 用途 |
|----|------|
| **skill** | 技能目录项：`slug`, `description`, `storage_path`, `checksum`, `status` 等 |
| **skill_version** | 版本行：`skill_id`, `version`, `storage_path`（指向 MinIO 对象前缀或 manifest） |
| **user_skill** | 用户订阅：`user_id`, `skill_id`, `status`, `local_version` / `server_version`, `is_external` |

**storage_path** 约定：与 MinIO 中 **`skills/{skillId}/{version}/`** 前缀一致（见下节）；下载接口返回预签名 URL。

### 3.3 记忆：结构化 Fact 与条目（与当前 Flyway 及第二版 MySQL 示例融合）

| 表 / 区域 | 用途 |
|-----------|------|
| **memory_entry** / **fact_metadata** | 已落地的 M1：事件/事实条目与 Fact 标签（详见 `docs/data/migration/V4__memory_m1.sql`） |
| **memory_embedding** | 已向量化标记（`V5__memory_embedding.sql`），与 Milvus 中记忆类向量对账 |
| **fact_metadata**（第二版宽表思路） | 第二版另提 `user_id + key_name` 型 Fact；可与现有 `fact_metadata.tag` 演进合并，避免重复设计时再定稿 |

**原则**：**可结构化查询、需事务** 的放 MySQL；**大段叙述、全文、向量** 走 ES + Milvus。

### 3.4 横切与其它（已实现）

| 表 | 用途 |
|----|------|
| **scheduled_task** | 定时任务 MVP |
| **hitl_approval** | 人在环审批 |
| **dialogue_state** | 侧栏状态 DST |
| **user_prompt_cipher** | 可选：原始用户提示词密文审计（`V7__user_prompt_cipher.sql`）；仅存密文，对称密钥由部署配置注入，与对话 `messages` 行并存 |

---

## 4. MinIO：对象空间规划

### 4.1 技能完整文件（主路径）

与 [技能系统设计](../workspace/skill-system-design.md) 一致：

```
skills/{skillId}/{version}/
  SKILL.md
  metadata.yaml  （可选）
  scripts/
  assets/
```

- **MySQL** `skill.storage_path` / `skill_version.storage_path` 存**逻辑前缀或 manifest 键**。  
- 客户端/服务端下载：**预签名 URL**，不长期暴露裸桶权限。

### 4.2 附件与其它桶（与第二版 5.6 对齐并命名统一）

| Bucket（示例名） | 内容 | 生命周期建议 |
|------------------|------|----------------|
| **skills** | 上表技能包（也可用前缀 `skills/` 单桶分区） | 长期 |
| **documents** | 用户上传 PDF/Word/Markdown | 按合规要求 |
| **generated-code** | Agent 生成代码 | 可迁冷存储 |
| **session-artifacts** | 会话图表、截图等 | 短 TTL |
| **embeddings-cache** | 嵌入缓存文件（若不用 Redis 足够时可选） | 短 TTL |

ES 中 Event 的 `metadata.attachments` 存 **对象键或 HTTPS URL**，便于回源 MinIO。

---

## 5. Elasticsearch

- **主索引 `events`**：基础字段见第二版 **5.1**；**主体、地点、触发词、模态、时间语义** 等要素与 **事件有向关系类型** 的规范见 [事件模型与关系类型.md](./事件模型与关系类型.md)，可执行映射见 [`docs/data/elasticsearch/events-index.json`](../data/elasticsearch/events-index.json)。  
- **对话检索**：可将 `conversation_id` 与 `messages` 同步字段对齐，或通过独立 `messages` 索引；以产品是否「仅 ES 查历史」为准。  
- **分词**：中文环境建议 IK（第二版已示例）；具体以集群插件为准。

---

## 6. Milvus

- **事件语义向量**（第二版 **5.2**）：`event_id`（VARCHAR）、`vector`（FLOAT_VECTOR）、`timestamp` 等；`metric` / `index_type` 按数据量从 IVF 到 HNSW 演进。  
- **记忆 / Fact 向量**（与当前实现衔接）：可独立 collection（如 `jingu3_memory`），主键与 `memory_entry.id` 对齐，过滤 `user_id`；详见 [milvus-collection-design.md](../v0.6/milvus-collection-design.md)。  
- **统一约定**：向量侧只存**检索必要标量**；正文永远在 ES 或 MySQL 权威表。

---

## 7. Neo4j

- 节点 **Event**：`id`, `type`, `timestamp`（轻量）；建议 `user_id`。  
- 关系：推荐 **`EVENT_LINK`** + 属性 **`rel_kind`**（11 种有向语义 + `OTHER_RELATION` 须 `explanation`），见 [事件模型与关系类型.md](./事件模型与关系类型.md) 与第二版 **5.3**。  
- 内容与全文仍回 **ES**，避免图库膨胀。

---

## 8. Redis

键模式与 TTL 建议沿用第二版 **5.5**，并与业务对齐：

| 用途 | Key 示例 | 说明 |
|------|----------|------|
| 会话上下文 | `session:{conversationId}:context` | Hash，TTL 30min 量级 |
| STM 队列 | `stm:queue:{conversationId}` | List |
| 限流 | `rate:tool:{name}:{userId}` | String + EXPIRE |
| API 缓存 | `jingu3:mem:list:v1:{userId}:{max}` | 已实现记忆列表示例 |

---

## 9. 跨存储标识与一致性

| 标识 | 出现位置 | 说明 |
|------|----------|------|
| **user_id** | MySQL / ES / Milvus / Redis | 全链路隔离维度 |
| **conversation_id** | MySQL conversations/messages；ES `session_id` 或 `conversation_id` | 统一命名优先 **conversation_id** |
| **event_id** | ES `event_id`；Neo4j 节点；Milvus 标量 | Event 主键 |
| **message_id** | MySQL messages；可选进 ES | 与 Event 可一对多或合并建模 |
| **vector_id** | ES 字段；messages.embedding_ref | 指向 Milvus 内部 id 或业务主键策略需统一 |
| **skill_id / version** | MySQL skill；MinIO 路径 | 与 `storage_path` 一致 |

**删除与 GDPR**：删用户需级联：MySQL 行、ES 按 `user_id` 删除、Milvus expr 删除、Neo4j 删节点、MinIO 按前缀清理（异步任务）。

---

## 10. 分阶段落地（与第二版 6.1 及路线图对齐）

| 阶段 | 组件 | 目标 |
|------|------|------|
| Phase 1 | MySQL + Redis + ES | 用户、对话、Event 写入与关键词检索；Redis STM/限流 |
| Phase 2 | + Milvus | 语义检索；与现有 `memory_entry` 向量能力合并规划 |
| Phase 3 | + Neo4j | 关系与 GraphRAG |
| Phase 4 | MinIO 全流程 | 技能包与附件生产级生命周期 |

当前仓库已部分完成：**MySQL 横切表 + 记忆 M1/M5**、**Redis 可选缓存**、**Milvus 记忆向量 MVP**；**用户/技能/对话宽表**与 **ES/Neo4j** 可按上表继续迭代。

---

## 11. 相关文档索引

| 文档 | 关系 |
|------|------|
| [系统数据存储-物化清单与测试数据.md](./系统数据存储-物化清单与测试数据.md) | MySQL 全表与 Flyway 清单、ES/MinIO/Milvus/Neo4j 物化文件与联调种子 |
| [记忆知识系统数据库选型分析第二版.md](./记忆知识系统数据库选型分析第二版.md) | 记忆域组件分工与 ES/Milvus/Neo4j 详设 |
| [记忆知识系统数据库选型分析.md](./记忆知识系统数据库选型分析.md) | 第一版（历史对照） |
| [技能系统设计](../workspace/skill-system-design.md) | skill / user_skill / skill_version 与 MinIO 目录 |
| [工作空间系统设计](../workspace/workspace-design.md) | 与工作区文件、沙箱边界（非本方案存储核心） |
| [服务架构.md](../服务架构.md) | users / conversations / messages 参考 DDL |
| [milvus-collection-design.md](../v0.6/milvus-collection-design.md) | 记忆类 Milvus 集合字段 |
| [事件模型与关系类型.md](./事件模型与关系类型.md) | 事件要素字段、11 种存储型有向关系与 Neo4j `EVENT_LINK` |

---

## 12. 修订记录

| 日期 | 说明 |
|------|------|
| 2026-04-13 | 终版：整合第二版记忆选型 + MySQL 用户/对话/技能 + MinIO 技能包与附件桶 |
| 2026-04-13 | ES/Neo4j 与 [事件模型与关系类型.md](./事件模型与关系类型.md) 对齐 |
