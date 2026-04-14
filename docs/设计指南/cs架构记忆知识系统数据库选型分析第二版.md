# 记忆与知识系统数据库选型分析报告（第二版）

> 生成时间：2026-04-13  
> 分析版本：v2.0  
> 维护者：Matrix Agent  
> **变更摘要**：基于已部署组件重新设计，移除 MongoDB/InfluxDB/Meilisearch，聚焦 Elasticsearch 作为事件主存储、Milvus 语义检索、Neo4j 关系推理。  
> **全站合并视图**：与用户、对话、技能元数据及 MinIO 技能包统一的终版见 [系统数据存储方案.md](./系统数据存储方案.md)。

---

## 一、概述

本报告基于现有本地部署环境（MySQL、MinIO、Redis、Elasticsearch、Milvus、Neo4j）进行存储架构设计，旨在为 jingu3 项目的记忆与知识系统提供**无新增组件、高内聚低耦合**的数据库选型方案。

**核心结论**：

- **MySQL** → 结构化元数据枢纽（Facts 定义、会话、配置）
- **Redis** → 短期记忆缓存、实时状态追踪
- **Elasticsearch** → 事件内容主存储、全文检索、聚合分析
- **Milvus** → 事件语义向量检索
- **Neo4j** → 事件关系图谱、因果推理、GraphRAG
- **MinIO** → 大文件/附件对象存储

---

## 二、记忆系统数据模型回顾

### 2.1 三层记忆架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Agent 记忆三层架构                         │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │              第三层：长期记忆 (LTM)                   │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐           │   │
│  │  │ 语义记忆  │ │ 情景记忆  │ │ 身份记忆  │           │   │
│  │  │(Milvus)  │ │(ES+Neo4j)│ │(USER.md)  │           │   │
│  │  └──────────┘ └──────────┘ └──────────┘           │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ▲                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              第二层：情节记忆 (Episodic)               │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐           │   │
│  │  │ 会话摘要  │ │ 任务轨迹  │ │ 关系图谱  │           │   │
│  │  │ (ES)     │ │ (Redis)  │ │ (Neo4j)  │           │   │
│  │  └──────────┘ └──────────┘ └──────────┘           │   │
│  └─────────────────────────────────────────────────────┘   │
│                           ▲                                │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              第一层：工作记忆 (STM)                   │   │
│  │   [用户输入] → [思考过程] → [工具调用] → [最终输出]   │   │
│  │                      ↓                               │   │
│  │               Redis 内存存储 (TTL 自动过期)           │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 数据存储需求矩阵

| 记忆组件 | 数据量级 | 结构复杂度 | 查询模式 | 推荐组件 |
|----------|----------|------------|----------|----------|
| 短期记忆 | 小（当前会话） | 低 | 随机访问 | Redis |
| Event 内容存储 | 大（事件级） | 中 | 全文+时序+聚合 | Elasticsearch |
| Event 语义向量 | 大（向量级） | 低 | ANN 检索 | Milvus |
| Event 关系推理 | 中（关系级） | 高 | 图遍历 | Neo4j |
| Fact 元数据 | 中（用户级） | 中 | 结构化查询 | MySQL |
| 会话管理 | 中（会话级） | 低 | CRUD | MySQL |
| 大文件/附件 | 不定（大文件） | 低 | 二进制流 | MinIO |
| 实时状态追踪 | 小（瞬时） | 低 | 高频读写 | Redis |

---

## 三、精简后存储映射方案

### 3.1 核心映射表

| 记忆数据类别 | 存储组件 | 角色与职责 |
|--------------|----------|------------|
| **Event 内容** | **Elasticsearch** | 事件全文检索、时序过滤、聚合统计、原文存储 |
| **Event 向量** | **Milvus** | 事件语义向量存储与 ANN 检索 |
| **Event 关系** | **Neo4j** | 事件间因果/时序/条件关系，支持多跳推理 |
| **Fact 元数据** | **MySQL** | 结构化键值对、用户级配置、版本管理 |
| **对话历史** | **Elasticsearch** | 按会话 ID 检索消息流，支持关键词搜索历史 |
| **用户配置/工具定义** | **MySQL** | 低变更配置数据，ACID 保证 |
| **会话上下文（STM）** | **Redis** | 当前会话上下文、思考链、工具调用暂存 |
| **实时状态追踪** | **Redis** | 任务进度、限流计数器、临时锁 |
| **大文件/附件** | **MinIO** | 文档、图片、生成代码、模型快照等二进制文件 |

### 3.2 组件分工详解

#### Elasticsearch：事件主存储与检索引擎

- **存什么**：Event 的完整 JSON 文档（`action`、`result`、`metadata`、`timestamp` 等）。
- **为什么不用 Neo4j 存内容**：ES 专为全文检索、聚合分析优化，海量日志类数据写入与查询性能远超 Neo4j。
- **与 Milvus 协作**：ES 文档中保存 `vector_id` 字段，Milvus 返回向量相似结果后，通过该 ID 回查 ES 获取完整事件内容。

#### Milvus：语义向量检索

- **存什么**：Event 文本的 Embedding 向量（维度取决于模型，如 768/1536）。
- **检索流程**：用户查询 → 生成向量 → Milvus 搜索 Top K → 获取 `event_id` → 去 ES 取完整文档。
- **优势**：专用向量数据库，支持十亿级向量毫秒级检索。

#### Neo4j：事件关系图谱

- **存什么**：事件节点（仅存 `event_id`、`type`、`timestamp` 等必要属性）及其关系（`CAUSED`、`PRECEDES`、`REFERENCES`）。
- **为什么分离内容与关系**：保持图结构轻量，提升遍历性能；内容检索走 ES，关系推理走 Neo4j。
- **GraphRAG 场景**：结合社区检测与 LLM 摘要，实现可解释推理。

#### MySQL：结构化元数据枢纽

- **存什么**：Fact 定义、用户配置、工具 Schema、会话元信息、审计日志。
- **优势**：成熟的事务支持、复杂关联查询、生态完善。

#### Redis：高速缓存与实时状态

- **存什么**：
  - 会话上下文（Hash，TTL 30min）
  - 任务进度（String，TTL 1h）
  - 短期记忆消息流（List，TTL 10min）
  - 工具调用限流（String + Expire）
- **与 ES 关系**：热点会话数据从 ES 加载到 Redis，减少 ES 查询压力。

#### MinIO：大文件对象存储

- **存什么**：用户上传的文档、Agent 生成的代码、图表、嵌入模型快照。
- **集成方式**：文件上传后返回 URL，存入 ES 对应事件的 `attachments` 字段。

---

## 四、架构图与数据流

### 4.1 整体架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                          LLM 应用层                               │
└───────────────────────────────┬──────────────────────────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         │                      │                      │
         ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     Redis       │    │     Milvus      │    │     MinIO       │
│ 短期记忆 / 缓存  │    │   向量检索       │    │  大文件存储      │
└────────┬────────┘    └────────┬────────┘    └────────┬────────┘
         │                      │                      │
         └──────────────────────┼──────────────────────┘
                                │ 元数据 / 关系 / 全文索引
         ┌──────────────────────┼──────────────────────┐
         ▼                      ▼                      ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     MySQL       │    │     Neo4j       │    │ Elasticsearch   │
│  结构化元数据    │    │   关系图谱       │    │  事件全文检索    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### 4.2 数据写入流程

```
用户交互产生 Event
        │
        ├─ 1. 提取文本 Embedding → 存入 Milvus (返回 vector_id)
        │
        ├─ 2. 构造完整 Event JSON → 写入 Elasticsearch (带 vector_id)
        │
        ├─ 3. 若事件间存在因果关系 → 异步写入 Neo4j
        │       (CREATE (e1)-[:CAUSED]->(e2))
        │
        ├─ 4. 涉及结构化元数据变更 → 写入 MySQL
        │
        └─ 5. 附件文件 → 上传 MinIO，URL 回填至 ES 文档
```

### 4.3 数据读取流程

```
用户查询请求
        │
        ├─ 语义检索分支：
        │      查询 Embedding → Milvus 检索 → 获取 event_id 列表
        │
        ├─ 关键词检索分支：
        │      直接查询 Elasticsearch (match、term、range)
        │
        ├─ 混合召回：合并 Milvus 与 ES 结果 → 去重排序
        │
        ├─ 关系推理分支：
        │      从 Neo4j 查询因果链：MATCH (e1)-[:CAUSED*1..3]->(e2)
        │
        └─ 元数据查询：直接读 MySQL
```

---

## 五、各组件详细设计

### 5.1 Elasticsearch 设计

**事件文档字段**（含主体、地点、触发词、模态、时间语义等）与 **11 种有向关系类型** 的完整约定见 **[事件模型与关系类型.md](./事件模型与关系类型.md)**；可执行映射见仓库 [`docs/data/elasticsearch/events-index.json`](../data/elasticsearch/events-index.json)（索引名可按环境使用 `jingu3-events` 等）。

**索引映射**（v8.x 语法摘要；生产可调整 `number_of_shards`）：

```json
PUT /events
{
  "settings": {
    "number_of_shards": 3,
    "analysis": {
      "analyzer": {
        "ik_smart_analyzer": {
          "type": "custom",
          "tokenizer": "ik_smart"
        }
      }
    }
  },
  "mappings": {
    "properties": {
      "event_id": { "type": "keyword" },
      "conversation_id": { "type": "keyword" },
      "session_id": { "type": "keyword" },
      "user_id": { "type": "keyword" },
      "timestamp": { "type": "date" },
      "action": {
        "type": "text",
        "analyzer": "ik_smart_analyzer",
        "fields": { "keyword": { "type": "keyword" } }
      },
      "result": { "type": "text", "analyzer": "ik_smart_analyzer" },
      "actors": { "type": "keyword" },
      "assertion": { "type": "keyword" },
      "event_subject": { "type": "text", "analyzer": "ik_smart_analyzer" },
      "event_location": { "type": "text", "analyzer": "ik_smart_analyzer" },
      "trigger_terms": { "type": "keyword" },
      "modality": { "type": "keyword" },
      "temporal_semantic": { "type": "keyword" },
      "metadata": {
        "type": "object",
        "properties": {
          "tool_calls": { "type": "nested" },
          "attachments": { "type": "keyword" }
        }
      },
      "vector_id": { "type": "keyword" },
      "message_id": { "type": "keyword" }
    }
  }
}
```

**生命周期策略**（ILM）：

```json
PUT _ilm/policy/events_policy
{
  "phases": {
    "hot": { "min_age": "0ms", "actions": {} },
    "delete": { "min_age": "90d", "actions": { "delete": {} } }
  }
}
```

### 5.2 Milvus 设计

**Collection Schema**：

```python
from pymilvus import Collection, CollectionSchema, FieldSchema, DataType

fields = [
    FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),
    FieldSchema("event_id", DataType.VARCHAR, max_length=64),
    FieldSchema("vector", DataType.FLOAT_VECTOR, dim=768),
    FieldSchema("timestamp", DataType.INT64)
]
schema = CollectionSchema(fields, "event_vectors")
collection = Collection("events", schema)

# 创建索引
index_params = {
    "metric_type": "IP",
    "index_type": "IVF_FLAT",
    "params": {"nlist": 1024}
}
collection.create_index("vector", index_params)
```

**检索示例**：

```python
search_params = {"metric_type": "IP", "params": {"nprobe": 10}}
results = collection.search(
    data=[query_vector],
    anns_field="vector",
    param=search_params,
    limit=10,
    output_fields=["event_id"]
)
event_ids = [hit.entity.get('event_id') for hit in results[0]]
```

### 5.3 Neo4j 设计

**有向关系**共 12 种语义位（含「无关系」不存储），实际入库 **11 种**；`CAUSATION` 与 `EFFECT_CAUSE`、`TEMPORAL_BEFORE` 与 `TEMPORAL_AFTER` 等为**对偶**，边方向均为 **A → B**，须按 [事件模型与关系类型.md](./事件模型与关系类型.md) 解读端点含义。

**推荐**：单一关系类型 `EVENT_LINK`，用属性 `rel_kind` 区分；`OTHER_RELATION` 必须带 `explanation`。

```cypher
// 事件节点（轻量；正文在 ES）
CREATE (e:Event {
  id: 'evt_001',
  type: 'user_query',
  user_id: '001',
  timestamp: datetime('2026-04-13T10:00:00Z')
})

// 例：因果 A 导致 B
CREATE (a)-[:EVENT_LINK { rel_kind: 'CAUSATION', confidence: 0.9 }]->(b)

// 例：A 早于 B
CREATE (a)-[:EVENT_LINK { rel_kind: 'TEMPORAL_BEFORE' }]->(b)
```

**典型查询：因果链追溯（仅 CAUSATION）**

```cypher
MATCH path = (start:Event {id: 'evt_001'})-[:EVENT_LINK*1..3 {rel_kind: 'CAUSATION'}]->(end:Event)
RETURN path
```

**文档/实体引用**（如 `REFERENCES` 指向 `:Document`）可另设关系类型或 `EVENT_LINK` + `rel_kind: 'OTHER_RELATION'` 与 `explanation`，由产品统一一种即可。

### 5.4 MySQL 设计

**核心表结构**：

```sql
-- Fact 元数据表
CREATE TABLE fact_metadata (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    user_id VARCHAR(64) NOT NULL,
    key_name VARCHAR(255) NOT NULL,
    value_type ENUM('string','number','boolean','date') NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_user_key (user_id, key_name)
);

-- 会话表
CREATE TABLE sessions (
    session_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    closed_at DATETIME,
    status ENUM('active','closed') DEFAULT 'active',
    INDEX idx_user_status (user_id, status)
);

-- 工具定义表
CREATE TABLE tools (
    tool_name VARCHAR(64) PRIMARY KEY,
    description TEXT,
    schema_json JSON NOT NULL,
    version INT DEFAULT 1
);
```

### 5.5 Redis 设计

| 用途 | 数据结构 | Key 模式 | TTL |
|------|----------|----------|-----|
| 当前会话上下文 | Hash | `session:{id}:context` | 30min |
| 任务进度追踪 | String | `task:{id}:progress` | 1h |
| 工具调用限流 | String | `rate:tool:{name}:{user}` | 1min |
| 短期记忆消息流 | List | `stm:queue:{session}` | 10min |
| 热点事件缓存 | String (JSON) | `event:cache:{event_id}` | 5min |

### 5.6 MinIO 设计

**存储桶规划**：

| Bucket | 内容 | 生命周期规则 |
|--------|------|--------------|
| `documents` | 用户上传的 PDF/Word/Markdown | 永久保存 |
| `generated-code` | Agent 生成代码 | 90 天后迁移至冷存储 |
| `session-artifacts` | 会话临时产物（图表、截图） | 7 天后自动删除 |
| `embeddings-cache` | 嵌入模型缓存 | 30 天后删除 |

---

## 六、实施建议与优先级

### 6.1 分阶段落地路线

| 阶段 | 组件组合 | 目标 | 预计工作量 |
|------|----------|------|------------|
| **Phase 1 (MVP)** | MySQL + Redis + Elasticsearch | 打通基础记忆流：会话管理、事件存储与关键词检索 | 1 周 |
| **Phase 2** | + Milvus | 接入语义向量检索，提升记忆召回精度 | 3 天 |
| **Phase 3** | + Neo4j | 构建事件关系图谱，支持因果推理 | 1 周 |
| **Phase 4** | + MinIO | 集成文件上传与附件管理 | 2 天 |

### 6.2 组件复用检查清单

| 组件 | 当前版本要求 | 配置建议 |
|------|-------------|----------|
| Elasticsearch | 8.x | 安装 IK 分词插件，开启 `xpack.security.enabled=false`（内网） |
| Milvus | 2.3+ | 使用 `standalone` 模式，CPU 版即可 |
| Neo4j | 5.x | 社区版，配置 `dbms.memory.heap.max_size=2G` |
| Redis | 7.x | 开启 AOF 持久化 |
| MySQL | 8.0 | 默认配置即可 |
| MinIO | 最新稳定版 | 单机模式，纠删码可选 |

### 6.3 简化与扩展建议

- **若初期不想启用 Neo4j**：可将事件关系降级为 ES 中的 `join` 字段或 MySQL 关联表，牺牲多跳查询性能，但架构更简单。
- **若向量检索量巨大**：可考虑 Milvus 集群模式或使用 ES 的 `dense_vector` 字段（8.0+ 支持 ANN）作为过渡方案。
- **监控与运维**：建议统一接入 Prometheus + Grafana，各组件均有官方 Exporter。

---

## 七、总结

### 7.1 最终组件职责矩阵

| 组件 | 核心职责 | 关键能力 |
|------|----------|----------|
| **MySQL** | 元数据枢纽 | 结构化存储、ACID、关联查询 |
| **Redis** | 实时缓存 | 低延迟读写、TTL 自动清理 |
| **Elasticsearch** | 事件内容库 | 全文检索、聚合分析、时序过滤 |
| **Milvus** | 语义向量库 | ANN 检索、十亿级向量支持 |
| **Neo4j** | 关系推理引擎 | 多跳遍历、因果链、图算法 |
| **MinIO** | 大文件存储 | S3 兼容、海量扩展、生命周期 |

### 7.2 方案优势

- **零新增组件**：完全基于已部署环境，无额外学习与运维成本。
- **职责高度内聚**：每个组件做最擅长的事，避免“万能存储”陷阱。
- **渐进式演进**：可按阶段启用复杂组件，风险可控。
- **检索与推理分离**：ES+Milvus 负责“找到什么”，Neo4j 负责“为什么关联”，清晰可维护。

---

## 八、附录：变更记录

| 日期 | 版本 | 变更内容 | 作者 |
|------|------|----------|------|
| 2026-04-13 | 1.0 | 初稿（含 MongoDB/InfluxDB 等） | Matrix Agent |
| 2026-04-13 | 2.0 | 基于现有组件重构，精简至六组件方案 | Matrix Agent |
| 2026-04-13 | 2.1 | ES 事件要素字段；Neo4j `EVENT_LINK` + `rel_kind`（11 种）；详见 [事件模型与关系类型.md](./事件模型与关系类型.md) | Matrix Agent |