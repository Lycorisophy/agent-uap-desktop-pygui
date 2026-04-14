# AI智能体记忆体系设计指南

> **文档版本**：v1.0
> **更新时间**：2026-04-12
> **作者**：Matrix Agent
> **内容来源**：综合ruyi72记忆系统设计文档(v1.0/v2.0/v3.0) + 行业研究资料

---

## 目录

1. [概述：记忆系统的核心地位](#1-概述记忆系统的核心地位)
2. [记忆理论基础](#2-记忆理论基础)
3. [记忆体系架构总览](#3-记忆体系架构总览)
4. [数据模型设计](#4-数据模型设计)
5. [事实分级体系](#5-事实分级体系)
6. [事件与关系管理](#6-事件与关系管理)
7. [存储与索引方案](#7-存储与索引方案)
8. [检索策略](#8-检索策略)
9. [抽取协议](#9-抽取协议)
10. [集成与实现](#10-集成与实现)
11. [行业方案对比](#11-行业方案对比)
12. [演进路线](#12-演进路线)
13. [参考资料](#13-参考资料)

---

## 1. 概述：记忆系统的核心地位

### 1.1 从"工具"到"伙伴"的跨越

AI记忆系统是智能体核心基础设施，历经工程化、结构化、认知架构三阶段发展。根据Lilian Weng（OpenAI安全研究副总裁）的定义：

```
Agent = LLM + 规划(Planning) + 记忆(Memory) + 工具(Tools) + 行动(Action)
```

**三个时代演进**：
- **2022-2023：模型时代** - GPT-4等大模型具备通用语言与推理能力
- **2024-2025：智能体时代** - RAG与工具调用让AI拥有"手和眼"
- **2026+：认知时代** - AI开始拥有"长期记忆"与"连贯人格"

### 1.2 记忆系统的核心问题

如何让AI**记住过去，从而理解未来**？

| 维度 | 上下文压缩 | 记忆管理 |
|:-----|:-----------|:---------|
| **核心问题** | 单次会话过长，超出上下文窗口 | 跨会话记住用户偏好、历史决策 |
| **触发时机** | 实时，Token接近窗口上限 | 异步，会话结束后或后台轮询 |
| **典型方案** | 摘要、裁剪、外存、Token剪枝 | 向量库持久化、结构化用户画像 |
| **工程目标** | 防止API报错，维持任务连续性 | 个性化体验，长期知识积累 |

### 1.3 记忆系统的三大核心能力

```
┌─────────────────────────────────────────────────────────────────┐
│                    AI智能体记忆体系                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐    │
│  │   感知能力    │  │   记忆能力    │  │   推理能力    │    │
│  │  理解用户输入 │  │  跨会话存储   │  │  关联历史经验 │    │
│  └───────────────┘  └───────────────┘  └───────────────┘    │
│                                                                 │
│  记忆 = 存储 + 检索 + 推理                                     │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. 记忆理论基础

### 2.1 人类记忆启发

从人类认知科学中，AI记忆系统可借鉴以下分类：

| 记忆类型 | 人类对应 | AI实现 | 特点 |
|:---------|:---------|:-------|:-----|
| **工作记忆** | 短时记忆 | 上下文窗口/KV Cache | 容量有限，快速访问 |
| **情景记忆** | 事件记忆 | 对话历史/Event存储 | 时间序列，关联检索 |
| **语义记忆** | 概念知识 | 向量库/知识图谱 | 语义相似性，去情境化 |
| **程序记忆** | 技能记忆 | Prompt模板/工具定义 | 行为模式，可复用 |

### 2.2 Agent记忆的三层架构

```
┌─────────────────────────────────────────────────────────────────┐
│                     Agent记忆三层架构                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              第三层：长期记忆 (LTM)                       │  │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐          │  │
│  │  │  语义记忆  │ │  情景记忆  │ │  身份记忆  │          │  │
│  │  │  (向量库)  │ │  (事件库)  │ │ (USER.md)  │          │  │
│  │  └────────────┘ └────────────┘ └────────────┘          │  │
│  │  持久化存储，跨会话保留                                  │  │
│  └─────────────────────────────────────────────────────────┘  │
│                           ▲                                    │
│                           │                                    │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              第二层：情节记忆 (Episodic)                   │  │
│  │  ┌────────────┐ ┌────────────┐ ┌────────────┐          │  │
│  │  │  会话摘要  │ │  任务轨迹  │ │  关系图谱  │          │  │
│  │  └────────────┘ └────────────┘ └────────────┘          │  │
│  │  State Tracking历史轨迹，经验积累                          │  │
│  └─────────────────────────────────────────────────────────┘  │
│                           ▲                                    │
│                           │                                    │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │              第一层：工作记忆 (STM)                       │  │
│  │                                                          │  │
│  │   [用户输入] → [思考过程] → [工具调用] → [最终输出]      │  │
│  │                                                          │  │
│  │   当前会话上下文、对话历史、工作内存                       │  │
│  └─────────────────────────────────────────────────────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 2.3 记忆与其他组件的关系

```
                    ┌──────────────┐
                    │     LLM      │
                    │   (大脑)     │
                    └──────┬───────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│    记忆      │  │    规划     │  │    工具      │
│   Memory     │  │   Planning   │  │    Tools     │
├──────────────┤  ├──────────────┤  ├──────────────┤
│• 上下文窗口  │  │• 任务分解    │  │• API调用    │
│• 向量检索   │  │• 自我反思    │  │• 代码执行    │
│• 事件存储   │  │• 重规划      │  │• 知识查询    │
└──────────────┘  └──────────────┘  └──────────────┘
        │
        ▼
┌──────────────┐
│    行动      │
│   Action     │
├──────────────┤
│• 工具执行    │
│• 结果反馈    │
│• 状态更新    │
└──────────────┘
```

---

## 3. 记忆体系架构总览

### 3.1 整体架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                      记忆系统完整架构                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐                                             │
│  │  对话片段    │ ← 用户输入 / 手动文本                        │
│  │   Input      │                                             │
│  └──────┬───────┘                                             │
│         │                                                      │
│         ▼                                                      │
│  ┌──────────────┐                                             │
│  │   抽取器     │ ← LLM智能抽取                                │
│  │  Extractor   │                                             │
│  └──────┬───────┘                                             │
│         │                                                      │
│         ▼                                                      │
│  ┌──────────────┐                                             │
│  │   分级路由   │ ← tier: trivial / important / permanent     │
│  │    Router    │                                             │
│  └──────┬───────┘                                             │
│         │                                                      │
│  ┌──────┴──────┬──────────────┐                              │
│  │              │              │                               │
│  ▼              ▼              ▼                               │
│ ┌────────┐ ┌─────────┐ ┌─────────────┐                      │
│ │  丢弃   │ │  向量库  │ │ USER.md等  │                      │
│ │ trivial │ │important │ │ permanent  │                      │
│ └────────┘ └─────────┘ └─────────────┘                      │
│                                                                 │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                     持久化存储层                          │ │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐          │ │
│  │  │ facts  │ │ events │ │relat-  │ │向量索引│          │ │
│  │  │ .jsonl │ │ .jsonl │ │ ions   │ │  (FAISS)│          │ │
│  │  └────────┘ └────────┘ └────────┘ └────────┘          │ │
│  └──────────────────────────────────────────────────────────┘ │
││
│  ┌──────────────────────────────────────────────────────────┐ │
│  │                     检索层                               │ │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐          │ │
│  │  │关键词搜索│ │向量检索 │ │ FTS5   │ │组合查询│          │ │
│  │  │  search │ │ semantic│ │全文索引 │ │  RRF   │          │ │
│  │  └────────┘ └────────┘ └────────┘ └────────┘          │ │
│  └──────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流概述

| 阶段 | 输入 | 处理 | 输出 |
|:-----|:-----|:-----|:-----|
| **抽取** | 对话文本 | LLM抽取 | Facts/Events/Relations JSON |
| **分级** | Facts | tier分类 | trivial/imporant/permanent |
| **持久化** | 分级结果 | 路由写入 | JSONL/SQLite/向量库/文件 |
| **检索** | 查询请求 | 多通道查询 | 组合结果+评分 |
| **注入** | 检索结果 | 上下文组装 | 系统提示片段 |

---

## 4. 数据模型设计

### 4.1 三类记忆单元

```python
# ============ 1. 事实 (Fact) ============
class Fact(BaseModel):
    """事实：稳定的用户画像、偏好、约定"""
    id: str                    # fact_xxx，全局唯一
    created_at: datetime
    source: str               # 文本来源描述
    
    # 核心字段
    key: str                  # 机器可读键，如 "user.home_province"
    value: str                # 原始值，如 "安徽"
    summary: str              # 一句话总结
    
    # 分级字段
    confidence: float          # 0~1，模型自信度
    tags: list[str]           # ["profile", "preference"]
    tier: str                 # "trivial" | "important" | "permanent"
    
    # 永驻路由
    identity_target: str      # "user" | "soul" | "memory"


# ============ 2. 事件 (Event) ============
class Event(BaseModel):
    """事件：带时间线的任务/操作记录"""
    id: str                    # event_xxx
    created_at: datetime
    time: str                  # 人类可读时间，如 "2026-04-03 10:30"
    location: str              # "本地电脑"、"公司"
    
    # 角色（v2.0扩展）
    actors: list[str]          # [主体列表，如"用户"、"如意72"]
    subject_actors: list[str]   # 执行动作的主体
    object_actors: list[str]   # 动作的承受者
    
    # 内容
    action: str                # 做了什么（1句）
    result: str                # 结果怎样（1句）
    
    # NLP语义
    triggers: list[str]        # 触发词，如["宣布","破产"]
    assertion: str             # "actual"|"negative"|"possible"|"not_occurred"
    
    # 三期扩展（v3.0）
    world_kind: str           # "real"|"fictional"|"hypothetical"|"unknown"
    temporal_kind: str        # "past"|"present"|"future_planned"|"future_uncertain"|"atemporal"
    planned_window: dict      # {"start":"","end":"","resolution":"fuzzy"}
    
    # 溯源
    source_session_id: str     # 来源会话
    source_message_ids: list   # 来源消息ID
    metadata: dict            # 附加字段


# ============ 3. 关系 (EventRelation) ============
class EventRelation(BaseModel):
    """关系：事件之间的因果/前后/相似等关系"""
    id: str                    # rel_xxx
    created_at: datetime
    event_a_id: str            # 事件A ID
    event_b_id: str            # 事件B ID
    
    # v2.0整型枚举
    relation_type: int         # 1-11，见下表
    explanation: str           # 简短说明
    relation_legacy: str       # v1兼容：原字符串


# ============ 关系类型枚举 ============
RELATION_TYPES = {
    0: "（无关系）- 不存储",
    1: "因果 - A导致B",
    2: "果因 - A为果B为因",
    3: "前后时序 - A早于B",
    4: "后前时序 - A晚于B",
    5: "条件 - A是B前提",
    6: "逆条件 - A为结果B为条件",
    7: "目的 - A为达成B而发生",
    8: "逆目的 - A为目标B为手段",
    9: "子事件 - A是B子事件",
    10: "父事件 - A是B父事件",
    11: "其它关系 - 需explanation"
}
```

### 4.2 存储布局

```
%USERPROFILE%\.ruyi72\memory\
├── facts.jsonl              # 事实存储
├── events.jsonl            # 事件存储
├── relations.jsonl          # 关系存储
├── memory.db               # SQLite数据库（v2.0+）
└── user_memory\           # 身份Markdown
    ├── USER.md            # 用户画像
    ├── SOUL.md            # Agent人格
    └── MEMORY.md          # 条款式记忆
```

---

## 5. 事实分级体系

### 5.1 三级设计原理

事实分级解决"信息过载"问题，不同级别采用不同存储和检索策略：

```
┌─────────────────────────────────────────────────────────────────┐
│                      事实分级体系                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌───────────────────────────────────────────────────────┐   │
│   │  Level 1: Trivial (一次性/低价值)                      │   │
│   │  - 噪声、一句话闲聊                                   │   │
│   │  - 策略：直接丢弃，不落库                             │   │
│   │  - Token成本：0                                       │   │
│   └───────────────────────────────────────────────────────┘   │
│                           │                                    │
│                           ▼                                    │
│   ┌───────────────────────────────────────────────────────┐   │
│   │  Level 2: Important (需语义召回)                      │   │
│   │  - 用户偏好、设置、约定                               │   │
│   │  - 策略：向量库索引 + SQLite元数据                   │   │
│   │  - Token成本：Embedding计算                           │   │
│   └───────────────────────────────────────────────────────┘   │
│                           │                                    │
│                           ▼                                    │
│   ┌───────────────────────────────────────────────────────┐   │
│   │  Level 3: Permanent (永驻身份)                        │   │
│   │  - 人格核心、用户画像、长期承诺                       │   │
│   │  - 策略：身份Markdown + 用户确认机制                  │   │
│   │  - Token成本：Prompt注入                              │   │
│   └───────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 5.2 分级决策表

| 特征 | Trivial | Important | Permanent |
|:-----|:--------|:----------|:-----------|
| **价值** | 一次性 | 需召回 | 长期影响 |
| **稳定性** | 低 | 中 | 高 |
| **示例** | "今天天气不错" | "用户偏好深色主题" | "用户叫张三" |
| **存储** | 丢弃 | 向量库 | Markdown |
| **检索** | 无 | 语义搜索 | 直接注入 |

### 5.3 Python分级实现

```python
from enum import Enum
from dataclasses import dataclass

class FactTier(Enum):
    TRIVIAL = "trivial"       # 不落库
    IMPORTANT = "important"    # 向量库
    PERMANENT = "permanent"   # 身份Markdown

@dataclass
class TierConfig:
    should_persist: bool       # 是否持久化
    storage: str              # 存储目标
    injection: str            # 注入方式

TIER_CONFIGS = {
    FactTier.TRIVIAL: TierConfig(
        should_persist=False,
        storage="drop",
        injection="none"
    ),
    FactTier.IMPORTANT: TierConfig(
        should_persist=True,
        storage="vector_db",
        injection="retrieval"
    ),
    FactTier.PERMANENT: TierConfig(
        should_persist=True,
        storage="identity_files",
        injection="system_prompt"
    )
}

class FactClassifier:
    """事实分级分类器"""
    
    def classify(self, fact: Fact) -> FactTier:
        """基于置信度和内容特征分级"""
        # 低置信度 → trivial
        if fact.confidence < 0.5:
            return FactTier.TRIVIAL
        
        # 关键标识词 → permanent
        permanent_keywords = ["用户", "我叫", "我的名字", "职业是"]
        if any(kw in fact.summary for kw in permanent_keywords):
            return FactTier.PERMANENT
        
        # 中等置信度 + 非关键词 → important
        return FactTier.IMPORTANT
```

---

## 6. 事件与关系管理

### 6.1 事件结构化设计

事件是记忆系统的时间维度，记录"发生过什么事"：

```python
class EventManager:
    """事件管理器"""
    
    def extract_events(self, text: str, llm) -> list[Event]:
        """从文本中抽取事件"""
        prompt = f"""从以下文本中抽取事件，输出JSON格式：

{text}

事件包含：
- time: 时间
- location: 地点
- subject_actors: 执行主体
- action: 做了什么
- result: 结果如何
- world_kind: real/fictional/hypothetical
- temporal_kind: past/present/future_planned/future_uncertain
"""
        response = llm.invoke(prompt)
        events = json.loads(response)
        return [Event(**e) for e in events]
    
    def link_relations(self, events: list[Event], llm) -> list[EventRelation]:
        """关联事件关系"""
        prompt = f"""分析以下事件之间的关系：

{json.dumps([{"id": e.id, "action": e.action} for e in events], ensure_ascii=False)}

关系类型：
1-因果 3-前后时序 5-条件 7-目的 9-子事件 11-其它
0=无关系（不输出）

输出JSON：
"""
        response = llm.invoke(prompt)
        return [EventRelation(**r) for r in json.loads(response)]
```

### 6.2 事件世界层与时间层

v3.0引入正交分类，区分事件性质：

| 分类维度 | 值 | 含义 | 示例 |
|:---------|:---|:-----|:-----|
| **world_kind** | `real` | 真实世界事件 | "我昨天跑了5公里" |
| **world_kind** | `fictional` | 虚构叙事 | "小说里主角登上了塔" |
| **world_kind** | `hypothetical` | 假设/思想实验 | "如果下雨就不出门" |
| **temporal_kind** | `past` | 已发生 | "上周三" |
| **temporal_kind** | `future_planned` | 计划要做的 | "明天去体检" |
| **temporal_kind** | `future_uncertain` | 可能发生 | "也许下个月换工作" |

### 6.3 事件与断言

断言描述话语中事件的**事实性状态**：

| assertion值 | 含义 | 示例 |
|:------------|:-----|:-----|
| `actual` | 肯定/已发生 | "他辞职了" |
| `negative` | 否定 | "他没有辞职" |
| `possible` | 可能 | "他可能辞职" |
| `not_occurred` | 预期但未发生 | "本该昨天完成" |

---

## 7. 存储与索引方案

### 7.1 存储演进路线

```
v1.0                v2.0                v3.0
─────               ─────               ─────
JSONL扫描           SQLite+FTS5         多模态索引
关键词匹配    →     全文检索       →     语义+结构混合
全表扫描             分层存储             智能路由
```

### 7.2 SQLite表模型

```sql
-- 事件表
CREATE TABLE memory_events (
    id TEXT PRIMARY KEY,
    created_at DATETIME,
    time TEXT,
    location TEXT,
    
    -- 角色
    actors TEXT,  -- JSON数组
    subject_actors TEXT,
    object_actors TEXT,
    
    -- 内容
    action TEXT NOT NULL,
    result TEXT,
    
    -- NLP语义
    triggers TEXT,           -- JSON数组
    assertion TEXT DEFAULT 'actual',
    
    -- v3.0扩展
    world_kind TEXT DEFAULT 'real',
    temporal_kind TEXT DEFAULT 'past',
    planned_window_json TEXT,
    
    -- 溯源
    source_session_id TEXT,
    source_message_ids TEXT,  -- JSON数组
    
    -- 其它
    metadata TEXT  -- JSON
);

-- 全文索引
CREATE VIRTUAL TABLE events_fts USING fts5(
    action, result, triggers,
    content='memory_events',
    content_rowid='rowid'
);

-- 关系表
CREATE TABLE memory_relations (
    id TEXT PRIMARY KEY,
    created_at DATETIME,
    event_a_id TEXT,
    event_b_id TEXT,
    relation_type INTEGER CHECK(relation_type BETWEEN 0 AND 11),
    explanation TEXT,
    relation_legacy TEXT,
    
    FOREIGN KEY (event_a_id) REFERENCES memory_events(id),
    FOREIGN KEY (event_b_id) REFERENCES memory_events(id)
);

-- 事实表（元数据）
CREATE TABLE memory_facts (
    id TEXT PRIMARY KEY,
    created_at DATETIME,
    key TEXT,
    value TEXT,
    summary TEXT,
    confidence REAL,
    tier TEXT,
    identity_target TEXT
);
```

### 7.3 向量存储

```python
class VectorMemory:
    """向量记忆存储"""
    
    def __init__(self, embedding_model="qwen3-embedding:8b"):
        self.embedding_model = embedding_model
        # 可选后端：FAISS, ChromaDB, Milvus, sqlite-vec
        self.index = None
    
    async def embed(self, text: str) -> list[float]:
        """获取文本嵌入"""
        response = await ollama.embeddings(
            model=self.embedding_model,
            prompt=text
        )
        return response["embedding"]
    
    async def add_fact(self, fact: Fact):
        """添加事实到向量库"""
        text = f"{fact.key}: {fact.summary}"
        embedding = await self.embed(text)
        
        self.index.add(
            ids=[fact.id],
            embeddings=[embedding],
            documents=[text],
            metadatas=[{
                "key": fact.key,
                "tier": fact.tier,
                "created_at": fact.created_at.isoformat()
            }]
        )
    
    async def search(self, query: str, top_k: int = 5, 
                    filter_tier: str = None) -> list[dict]:
        """语义检索"""
        query_embedding = await self.embed(query)
        
        results = self.index.search(
            query_embeddings=[query_embedding],
            n_results=top_k,
            where={"tier": filter_tier} if filter_tier else None
        )
        
        return [
            {"id": doc_id, "score": score, "content": doc}
            for doc_id, doc, score in zip(
                results["ids"][0],
                results["documents"][0],
                results["distances"][0]
            )
        ]
```

### 7.4 多通道检索合并

```python
class HybridRetriever:
    """混合检索器"""
    
    def __init__(self, vector_store, sqlite_db):
        self.vector = vector_store
        self.sqlite = sqlite_db
    
    async def search(self, query: str, filters: dict = None) -> list[dict]:
        """多通道检索 + RRF合并"""
        results = []
        
        # 通道1：向量语义检索
        vector_results = await self.vector.search(query, top_k=10)
        for r in vector_results:
            results.append({
                **r,
                "channel": "vector",
                "rerank_score": 1.0 / (0.01 + r["score"])
            })
        
        # 通道2：关键词/FTS检索
        fts_results = await self.sqlite.search_fts(query, filters)
        for r in fts_results:
            results.append({
                **r,
                "channel": "fts",
                "rerank_score": 1.0 / (0.01 + r["rank"])
            })
        
        # RRF合并 (Reciprocal Rank Fusion)
        return self._rrf_fusion(results, k=60)
    
    def _rrf_fusion(self, results: list, k: int = 60) -> list[dict]:
        """RRF融合算法"""
        scores = defaultdict(float)
        
        for r in results:
            rank = results.index(r) + 1
            scores[r["id"]] += 1.0 / (k + rank)
        
        # 按融合分数排序
        sorted_results = sorted(
            results, 
            key=lambda x: scores[x["id"]], 
            reverse=True
        )
        
        return sorted_results
```

---

## 8. 检索策略

### 8.1 检索通道

| 通道 | 能力 | 适用场景 |
|:-----|:-----|:---------|
| **关键词** | 精确匹配 | 已知字段搜索 |
| **FTS5** | 全文检索 | 短语、部分匹配 |
| **向量** | 语义相似 | 同义表述、概念匹配 |
| **结构化** | 字段过滤 | 时间范围、类型筛选 |

### 8.2 检索流程

```
用户查询
    │
    ▼
┌─────────────────┐
│  查询理解       │ ← LLM解析意图
│  Query Parsing   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  多通道并行检索 │
│  Parallel Search│
└────────┬────────┘
         │
    ┌────┴────┐
    │         │
    ▼         ▼
┌───────┐ ┌───────┐ ┌───────┐
│ 关键词 │ │ FTS5  │ │ 向量  │
│ search │ │ search│ │search │
└───┬───┘ └───┬───┘ └───┬───┘
    │         │         │
    └────┬────┴────┬────┘
         │         │
         ▼         ▼
┌─────────────────┐
│   RRF融合      │ ← Reciprocal Rank Fusion
│   Fusion       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  结果重排序     │
│   Rerank       │
└────────┬────────┘
         │
         ▼
      结果返回
```

### 8.3 场景化检索策略

```python
class ContextualRetriever:
    """场景化检索器"""
    
    async def retrieve_for_session(self, user_id: str, query: str) -> str:
        """会话冷启动检索"""
        results = await self.hybrid.search(query)
        
        # 过滤：排除虚构事件（默认）
        real_results = [
            r for r in results 
            if r.get("world_kind") != "fictional"
        ]
        
        # 计划事件单独展示
        future_events = [
            r for r in results
            if r.get("temporal_kind") in ["future_planned", "future_uncertain"]
        ]
        
        # 组装上下文
        context_parts = []
        
        if real_results:
            context_parts.append("## 相关记忆\n" + 
                "\n".join([f"- {r['content']}" for r in real_results[:5]]))
        
        if future_events:
            context_parts.append("## 用户计划\n" +
                "\n".join([f"- {r['content']}" for r in future_events[:3]]))
        
        return "\n\n".join(context_parts)
    
    async def retrieve_for_planning(self, user_id: str, task: str) -> str:
        """任务规划检索"""
        # 查询相关历史事件
        events = await self.hybrid.search(
            task, 
            filters={"temporal_kind": "past"}
        )
        
        # 查询相关计划
        plans = await self.hybrid.search(
            task,
            filters={"temporal_kind": "future_planned"}
        )
        
        return {
            "relevant_history": events[:3],
            "related_plans": plans[:2],
            "context_window": "7d"  # 7天内
        }
```

---

## 9. 抽取协议

### 9.1 LLM抽取Prompt

```python
EXTRACT_SYSTEM_PROMPT = """你是一个记忆抽取专家。从用户对话中提取结构化记忆。

## 输出格式
输出JSON格式，包含三部分：
{
    "facts": [...],      // 事实：稳定的用户信息、偏好、约定
    "events": [...],     // 事件：带时间线发生的事情
    "relations": [...]    // 关系：事件之间的关联
}

## Facts字段
- key: 机器可读键，如"user.home_province"
- value: 原始值
- summary: 一句话总结
- confidence: 0-1，自信度
- tier: "trivial"|"important"|"permanent"
- identity_target: "user"|"soul"|"memory"（permanent时填）

## Events字段
- action: 做了什么（必须）
- result: 结果如何
- time: 时间
- location: 地点
- subject_actors: 执行主体
- assertion: "actual"|"negative"|"possible"|"not_occurred"
- world_kind: "real"|"fictional"|"hypothetical"
- temporal_kind: "past"|"present"|"future_planned"|"future_uncertain"

## Relations字段
- event_a_id: 事件A的id
- event_b_id: 事件B的id
- relation_type: 1-11（见下表）
- explanation: 说明

## 关系类型
1=因果 2=果因 3=前后 4=后前 5=条件 6=逆条件
7=目的 8=逆目的 9=子事件 10=父事件 11=其它

注意：relation_type=0表示无关系，不要输出。
"""

def extract_from_conversation(messages: list, llm) -> dict:
    """从对话历史中抽取记忆"""
    # 构造对话文本
    conversation = "\n".join([
        f"{'用户' if m['role']=='user' else '助手'}：{m['content']}"
        for m in messages[-10:]  # 最近10轮
    ])
    
    response = llm.invoke(
        EXTRACT_SYSTEM_PROMPT + f"\n\n对话内容：\n{conversation}"
    )
    
    return json.loads(response.content)
```

### 9.2 抽取结果处理

```python
class MemoryExtractor:
    """记忆抽取器"""
    
    def __init__(self, store, vector_memory, identity_manager):
        self.store = store
        self.vector = vector_memory
        self.identity = identity_manager
    
    async def extract_and_store(self, text: str, session_id: str = None):
        """抽取并存储记忆"""
        # 1. LLM抽取
        result = await self.extract(text)
        
        # 2. 处理事实
        for fact in result.get("facts", []):
            await self._process_fact(Fact(**fact), session_id)
        
        # 3. 处理事件
        for event in result.get("events", []):
            event["source_session_id"] = session_id
            await self._process_event(Event(**event))
        
        # 4. 处理关系
        for relation in result.get("relations", []):
            if relation.get("relation_type", 0) > 0:
                await self._process_relation(EventRelation(**relation))
        
        return {
            "facts_count": len(result.get("facts", [])),
            "events_count": len(result.get("events", [])),
            "relations_count": len(result.get("relations", []))
        }
    
    async def _process_fact(self, fact: Fact, session_id: str):
        """处理事实（分级路由）"""
        if fact.tier == "trivial":
            return  # 丢弃
        
        if fact.tier == "important":
            # 向量库索引
            await self.vector.add_fact(fact)
            # SQLite元数据
            await self.store.save_fact(fact)
        
        elif fact.tier == "permanent":
            # 身份Markdown队列
            await self.identity.queue_for_merge(fact)
    
    async def _process_event(self, event: Event):
        """处理事件"""
        # SQLite存储
        await self.store.save_event(event)
        # 向量索引（可选）
        if event.world_kind != "fictional":
            await self.vector.add_event(event)
```

---

## 10. 集成与实现

### 10.1 集成架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      Agent系统集成                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    Agent主循环                           │   │
│  │  ┌────────┐    ┌────────┐    ┌────────┐              │   │
│  │  │ Plan   │ → │ Execute│ → │ Observe│              │   │
│  │  └────────┘    └────────┘    └────────┘              │   │
│  └─────────────────────────────────────────────────────────┘   │
│         │                  │                  │               │
│         │         ┌────────┴────────┐        │               │
│         │         │                 │        │               │
│         ▼         ▼                 ▼        ▼               │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐              │
│  │  记忆工具  │ │   抽取器   │ │   检索器   │              │
│  │  browse   │ │  extract   │ │  search   │              │
│  │  search   │ │            │ │  retrieve │              │
│  └────────────┘ └────────────┘ └────────────┘              │
│         │                  │                  │               │
│         └──────────────────┴──────────────────┘               │
│                            │                                    │
│                            ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                   记忆存储层                            │   │
│  │  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐       │   │
│  │  │ SQLite │ │向量库  │ │ JSONL  │ │Identity│       │   │
│  │  └────────┘ └────────┘ └────────┘ └────────┘       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 10.2 ReAct工具集成

```python
class MemoryTools:
    """记忆相关ReAct工具"""
    
    def __init__(self, store, retriever, identity_manager):
        self.store = store
        self.retriever = retriever
        self.identity = identity_manager
    
    @property
    def tools(self) -> list[dict]:
        return [
            {
                "name": "search_memory",
                "description": "搜索长期记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "搜索内容"},
                        "limit": {"type": "integer", "default": 5},
                        "event_world_kinds": {"type": "array", "default": ["real"]},
                        "event_temporal_kinds": {"type": "array"}
                    }
                }
            },
            {
                "name": "browse_memory",
                "description": "浏览近期记忆摘要",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "limit": {"type": "integer", "default": 10}
                    }
                }
            },
            {
                "name": "save_to_memory",
                "description": "保存重要信息到记忆",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "type": {"enum": ["fact", "event"], "default": "fact"},
                        "priority": {"enum": ["important", "permanent"]}
                    }
                }
            }
        ]
    
    async def search_memory(self, query: str, limit: int = 5, 
                          event_world_kinds: list = None,
                          event_temporal_kinds: list = None) -> str:
        """搜索记忆"""
        filters = {}
        if event_world_kinds:
            filters["world_kind"] = {"$in": event_world_kinds}
        if event_temporal_kinds:
            filters["temporal_kind"] = {"$in": event_temporal_kinds}
        
        results = await self.retriever.search(query, filters)
        
        return "\n".join([
            f"- {r['content']} (相关性: {r.get('score', 0):.2f})"
            for r in results[:limit]
        ])
    
    async def save_to_memory(self, content: str, 
                           memory_type: str = "fact",
                           priority: str = "important") -> str:
        """保存到记忆"""
        # 直接保存，跳过抽取
        if memory_type == "fact":
            fact = Fact(
                id=f"fact_{uuid.uuid4().hex[:8]}",
                key=f"user_note_{len(await self.store.get_all_facts())}",
                value=content,
                summary=content[:100],
                confidence=0.9,
                tier=priority
            )
            await self.store.save_fact(fact)
            if priority == "important":
                await self.vector.add_fact(fact)
        
        return f"已保存到{priority}记忆"
```

### 10.3 闲时自动抽取

```python
import asyncio
from threading import Thread

class MemoryAutoExtractor:
    """闲时自动抽取"""
    
    def __init__(self, extractor, session_store, config: dict):
        self.extractor = extractor
        self.session_store = session_store
        self.config = config
        self.state_file = "%USERPROFILE%\\.ruyi72\\memory_auto_extract_state.json"
        self.running = False
    
    def start_background(self):
        """启动后台守护线程"""
        self.running = True
        thread = Thread(target=self._background_loop, daemon=True)
        thread.start()
    
    def _background_loop(self):
        """后台循环"""
        while self.running:
            if self._is_idle():
                asyncio.run(self._extract_once())
            time.sleep(self.config.get("interval_sec", 300))
    
    def _is_idle(self) -> bool:
        """判断是否空闲（无LLM调用）"""
        # 实现：检查LLM调用计数、进程状态等
        return True
    
    async def _extract_once(self):
        """执行一次抽取"""
        state = self._load_state()
        
        # 增量获取新会话
        sessions = await self.session_store.get_new_sessions(
            after_id=state.get("last_session_id")
        )
        
        for session in sessions:
            messages = await self.session_store.get_messages(session.id)
            text = self._messages_to_text(messages)
            
            if len(text) > 100:  # 过滤过短
                await self.extractor.extract_and_store(text, session.id)
            
            state["last_session_id"] = session.id
        
        self._save_state(state)
    
    def _load_state(self) -> dict:
        if os.path.exists(self.state_file):
            return json.load(open(self.state_file))
        return {"last_session_id": None}
    
    def _save_state(self, state: dict):
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        json.dump(state, open(self.state_file, "w"))
```

---

## 11. 行业方案对比

### 11.1 主流框架对比

| 框架 | 存储方案 | 检索能力 | 特色 |
|:-----|:---------|:---------|:-----|
| **MemGPT** | 分层虚拟内存 | 软分页调度 | 模拟OS内存管理 |
| **Letta** | SQLite+向量 | 多通道检索 | 开源、企业级 |
| **Mem0** | 多层向量 | 语义记忆 | 专注记忆API |
| **Zep** | 时序数据库 | 历史检索 | 专注Agent记忆 |
| **ruyi72** | JSONL+SQLite+向量 | 三级分级 | 身份Markdown治理 |
| **LangChain** | 多种后端 | 灵活可配 | 生态丰富 |

### 11.2 技术路线分类

```
┌─────────────────────────────────────────────────────────────────┐
│                    记忆系统技术路线                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   路线A：分层抽象派                                             │
│   ├── MemGPT: 虚拟内存/软分页                                  │
│   ├── 实现：LLM感知"内存压力"，主动换页                         │
│   └── 优点：统一抽象，缺点：实现复杂                           │
│                                                                 │
│   路线B：分级存储派                                             │
│   ├── ruyi72: Trivial/Important/Permanent                      │
│   ├── Mem0: 语义/关系/短期                                    │
│   └── 优点：成本可控，缺点：分级策略需精细调优                  │
│                                                                 │
│   路线C：时序事件派                                             │
│   ├── Zep: 时间线记忆                                          │
│   ├── 实现：事件驱动，自动关联                                  │
│   └── 优点：时间维度强，缺点：实时性要求高                     │
│                                                                 │
│   路线D：知识图谱派                                             │
│   ├── GraphRAG: 实体关系图                                      │
│   ├── 实现：知识图谱+向量混合                                   │
│   └── 优点：推理能力强，缺点：抽取成本高                      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 11.3 MemGPT架构解析

```python
class MemGPTArchitecture:
    """
    MemGPT核心思想：将LLM上下文视为"虚拟内存"，通过MMU管理
    """
    
    def __init__(self, model, context_window: int = 128000):
        self.model = model
        self.context_window = context_window
        self.memory_messages = []      # 核心内存（类似RAM）
        self.memory_archive = []       # 归档内存（类似磁盘）
        self.memory_functions = []    # 功能内存（只读系统）
    
    def _check_memory_pressure(self) -> float:
        """检查内存压力"""
        used = len(self.memory_messages)
        return used / self.context_window
    
    def _should_archive(self) -> bool:
        """判断是否应归档"""
        pressure = self._check_memory_pressure()
        return pressure > 0.8
    
    def _archive_oldest(self):
        """归档最旧消息"""
        if self.memory_messages:
            oldest = self.memory_messages.pop(0)
            # LLM总结后归档
            summary = self.model.invoke(
                f"总结以下对话要点：\n{oldest}"
            )
            self.memory_archive.append({
                "original": oldest,
                "summary": summary
            })
    
    def _recall_relevant(self, query: str) -> str:
        """召回相关归档"""
        # 从归档中检索相关记忆
        relevant = self._semantic_search(
            self.memory_archive, 
            query,
            top_k=3
        )
        return "\n".join([r["summary"] for r in relevant])
    
    def chat(self, user_message: str) -> str:
        """聊天主循环"""
        # 1. 检查内存压力
        if self._should_archive():
            self._archive_oldest()
        
        # 2. 召回相关记忆
        context = self._recall_relevant(user_message)
        
        # 3. 构建消息
        system_msg = f"回顾记忆：\n{context}\n\n" + self.memory_functions
        messages = [
            {"role": "system", "content": system_msg},
            *self.memory_messages,
            {"role": "user", "content": user_message}
        ]
        
        # 4. 生成响应
        response = self.model.invoke(messages)
        
        # 5. 更新内存
        self.memory_messages.append(
            {"role": "user", "content": user_message}
        )
        self.memory_messages.append(
            {"role": "assistant", "content": response}
        )
        
        return response
```

---

## 12. 演进路线

### 12.1 里程碑规划

| 阶段 | 内容 | 验收标准 |
|:-----|:-----|:---------|
| **M1** | 抽取协议tier + trivial丢弃 | 非重要事实不再出现在facts.jsonl |
| **M2** | 重要事实入向量 + 检索可用 | 同义查询能命中重要事实 |
| **M3** | 永驻合并管道 + 用户确认 | 未确认前不覆盖身份文件 |
| **M4** | 事件/关系入SQLite + FTS5 | 事件可按关键词与时间窗查询 |
| **M5** | 对话历史迁移/双写 + FTS | 会话内全文检索可用 |
| **M6** | ReAct工具组合查询 | 单轮可调多通道检索 |
| **M7** | world_kind + temporal_kind | 新抽取可区分虚构与计划 |
| **M8** | 检索默认过滤 + 工具参数 | 用户不勾虚构时，摘要里不出现 |
| **M9** | 计划窗口归一化 + 兑现状态 | "下周做什么"可查；过期计划隐藏 |

### 12.2 迁移策略

```python
class MigrationManager:
    """数据迁移管理器"""
    
    async def migrate_v1_to_v2(self):
        """v1 JSONL → v2 SQLite"""
        
        # 1. 备份
        await self._backup_jsonl()
        
        # 2. 迁移事实
        async for fact in self._read_facts_jsonl():
            # 无tier → 标记为important
            if not hasattr(fact, 'tier'):
                fact.tier = "important"
            await self.store.save_fact(fact)
            await self.vector.add_fact(fact)
        
        # 3. 迁移事件
        async for event in self._read_events_jsonl():
            # 断言默认值
            if not hasattr(event, 'assertion'):
                event.assertion = "actual"
            # actors → subject_actors
            if hasattr(event, 'actors') and not hasattr(event, 'subject_actors'):
                event.subject_actors = event.actors
            await self.store.save_event(event)
        
        # 4. 迁移关系
        async for relation in self._read_relations_jsonl():
            # relation字符串 → relation_type
            if hasattr(relation, 'relation') and not hasattr(relation, 'relation_type'):
                relation.relation_type = self._map_relation_type(relation.relation)
            await self.store.save_relation(relation)
        
        # 5. 验证
        await self._verify_migration()
    
    def _map_relation_type(self, relation_str: str) -> int:
        """关系字符串映射"""
        mapping = {
            "因果": 1, "前置": 3, "条件": 5,
            "目的": 7, "子事件": 9, "其它": 11
        }
        return mapping.get(relation_str, 11)
```

### 12.3 开放决策清单

| 决策项 | 选项 | 推荐 |
|:-------|:-----|:-----|
| 向量索引后端 | FAISS/ChromaDB/sqlite-vec | sqlite-vec（轻量） |
| tier缺失默认 | trivial/important | important |
| 永驻写盘策略 | A-确认后写/B-自动追加 | A |
| messages.json | 迁移/双写/仅索引 | 双写过渡 |
| 虚构事件处理 | 不索引/索引不返回/返回需过滤 | 索引+过滤 |

---

## 13. 参考资料

### 学术论文

| 论文 | 来源 | 链接 |
|:-----|:-----|:-----|
| LLM Powered Autonomous Agents | Lilian Weng | https://lilianweng.github.io/posts/2023-06-23-agent/ |
| MemGPT | arXiv | https://arxiv.org/abs/2310.08560 |
| A-MEM | arXiv:2502.12110 | https://arxiv.org/abs/2502.12110 |
| DeepRAG | arXiv:2502.01142 | https://arxiv.org/abs/2502.01142 |
| Long Term Memory | arXiv:2410.15665 | https://arxiv.org/abs/2410.15665 |
| KG-R1 | arXiv:2509.26383 | https://arxiv.org/abs/2509.26383 |

### 开源项目

| 项目 | 描述 | 链接 |
|:-----|:-----|:-----|
| MemGPT | 分层虚拟内存Agent | https://github.com/MemGPT/MemGPT |
| Letta | 企业级Agent记忆平台 | https://github.com/letta-ai/letta |
| Mem0 | 记忆API服务 | https://github.com/mem0ai/mem0 |
| Zep | Agent记忆服务 | https://github.com/getzep/zep |
| LangChain | Agent开发框架 | https://github.com/langchain-ai/langchain |

### 产品系统

| 产品 | 描述 |
|:-----|:-----|
| Claude | Anthropic的AI助手 |
| ChatGPT Memory | OpenAI的记忆功能 |
| Copilot Memory | Microsoft的上下文记忆 |
| ruyi72 | 永驻+事件记忆系统 |

---

*文档版本：v1.0*
*更新时间：2026-04-12*
*作者：LySoY and His Agent Team*
