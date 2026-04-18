# AI智能体上下文压缩系统设计方案参考指南

## 一、概述

本设计方案面向需要长期运行、处理大量历史对话与工具调用结果的智能体系统。核心目标是在上下文窗口受限的大模型环境下，通过**管道化压缩**和**持久化存储与索引**相结合的机制，实现上下文长度的动态管理，同时保证关键历史信息的可追溯性与可恢复性。

设计原则：
- **逐层降级、渐进压缩**：先替换最不重要的信息，再压缩次重要的信息，最大限度保留关键上下文的原始形态。
- **可恢复的压缩**：所有被压缩或截断的原始内容均持久化至数据库，压缩标记中包含唯一索引，智能体可自主判断是否需要回溯查询原始详情。
- **双阈值驱动**：设置触发阈值与目标阈值，形成滞回区间，避免压缩振荡。
- **分层摘要**：按内容重要性（助手思考 < 工具交互 < 核心对话）依次进行摘要，平衡压缩率与信息保真度。

## 二、核心数据结构设计参考

### 2.1 统一消息结构

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any, List

class MessageRole(Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    THINKING = "thinking"          # 助手内部思考过程

class CompressionType(Enum):
    NONE = "none"
    TOOL_RESULT_REPLACED = "tool_result_replaced"
    ANCIENT_MEMORY_REPLACED = "ancient_memory_replaced"
    THINKING_SUMMARIZED = "thinking_summarized"
    CONVERSATION_SUMMARIZED = "conversation_summarized"
    TRUNCATED_WITH_STORAGE = "truncated_with_storage"   # 截断且已存入数据库

@dataclass
class Message:
    id: str
    role: MessageRole
    content: str
    timestamp: datetime
    turn_number: int
    original_content: Optional[str] = None
    compression_type: CompressionType = CompressionType.NONE
    compression_metadata: Dict[str, Any] = field(default_factory=dict)
    token_count: int = 0
    tool_name: Optional[str] = None
    tool_parameters: Optional[Dict] = None
    db_record_id: Optional[str] = None      # 关联数据库记录的ID

    def get_effective_content(self) -> str:
        return self.content

    def get_age_days(self, current_time: datetime) -> int:
        return (current_time - self.timestamp).days

    def get_age_turns(self, current_turn: int) -> int:
        return current_turn - self.turn_number
```

### 2.2 持久化存储表结构设计

为支持原始内容的存储与索引检索，设计如下数据库表（以关系型数据库为例，也可使用向量数据库存储内容以支持语义检索）。

```sql
-- 原始消息存储表
CREATE TABLE context_archive (
    id               VARCHAR(64) PRIMARY KEY,          -- UUID
    conversation_id  VARCHAR(64) NOT NULL,             -- 所属会话ID
    message_id       VARCHAR(64) NOT NULL,             -- 关联的原始消息ID
    role             VARCHAR(20) NOT NULL,
    content          TEXT NOT NULL,                    -- 完整原始内容
    token_count      INT NOT NULL,
    timestamp        TIMESTAMP NOT NULL,
    turn_number      INT NOT NULL,
    metadata         JSON,                             -- 扩展元数据（工具名、参数等）
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 压缩记录表（用于审计与调试）
CREATE TABLE compression_log (
    id               VARCHAR(64) PRIMARY KEY,
    conversation_id  VARCHAR(64) NOT NULL,
    cycle_index      INT NOT NULL,
    strategy         VARCHAR(50) NOT NULL,
    messages_before  INT NOT NULL,                     -- 压缩前消息数
    messages_after   INT NOT NULL,                     -- 压缩后消息数
    tokens_before    INT NOT NULL,
    tokens_after     INT NOT NULL,
    details          JSON,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 索引
CREATE INDEX idx_archive_conversation ON context_archive(conversation_id, timestamp);
CREATE INDEX idx_archive_message_id ON context_archive(message_id);
```

### 2.3 压缩标记格式

当消息被压缩并存入数据库后，其 `content` 字段将被替换为包含数据库索引的标记，格式如下：

```
[已压缩|db_id:{database_uuid}|摘要:{简短摘要}|长度:{原token数}tokens]
```

示例：
- 超长工具结果替换：
  `[已压缩|db_id:550e8400-e29b-41d4-a716-446655440000|技能:search|参数:query="Python GIL"|长度:2150tokens]`
- 远古记忆替换：
  `[已压缩|db_id:550e8400-e29b-41d4-a716-446655440001|时间:2025-03-01|用户提问:"Python多线程性能问题"|长度:430tokens]`
- 助手思考摘要：
  `[已摘要|db_id:550e8400-e29b-41d4-a716-446655440002|思考摘要:"决定使用asyncio替代多线程，因GIL限制"|原长度:820tokens]`

这种标记格式既为模型提供了必要的压缩摘要信息，又为智能体后续通过工具调用读取完整内容提供了唯一索引。

## 三、持久化存储与智能体检索机制

### 3.1 存储接口设计

```python
from abc import ABC, abstractmethod
import uuid
from typing import List, Optional

class ContextArchiveRepository(ABC):
    """上下文归档仓储接口"""
    
    @abstractmethod
    async def save(self, conversation_id: str, message: Message) -> str:
        """
        保存消息原始内容至数据库，返回数据库记录ID。
        """
        pass
    
    @abstractmethod
    async def get_by_id(self, db_id: str) -> Optional[str]:
        """
        通过数据库ID检索原始内容。
        """
        pass
    
    @abstractmethod
    async def search_by_conversation(
        self, 
        conversation_id: str, 
        keyword: Optional[str] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 10
    ) -> List[Dict]:
        """
        按条件检索历史内容。
        """
        pass

class SQLContextArchiveRepository(ContextArchiveRepository):
    """基于SQL的实现示例"""
    
    async def save(self, conversation_id: str, message: Message) -> str:
        db_id = str(uuid.uuid4())
        await self.db.execute(
            """
            INSERT INTO context_archive 
            (id, conversation_id, message_id, role, content, token_count, 
             timestamp, turn_number, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (db_id, conversation_id, message.id, message.role.value,
             message.original_content or message.content, 
             message.token_count, message.timestamp, message.turn_number,
             json.dumps(message.compression_metadata))
        )
        return db_id
    
    async def get_by_id(self, db_id: str) -> Optional[str]:
        row = await self.db.fetch_one(
            "SELECT content FROM context_archive WHERE id = %s",
            (db_id,)
        )
        return row['content'] if row else None
```

### 3.2 压缩时自动归档与标记生成

在管道压缩的每一步，只要涉及内容的替换或截断，均需调用归档存储，并生成带有数据库ID的替换标记。

```python
class ArchiveManager:
    """归档管理器：统一处理存储与标记生成"""
    
    def __init__(self, repository: ContextArchiveRepository):
        self.repository = repository
    
    async def archive_and_replace(
        self,
        conversation_id: str,
        message: Message,
        compression_type: CompressionType,
        summary_template: str,
        summary_params: Dict[str, Any]
    ) -> Message:
        """
        将消息原始内容归档，生成替换标记，返回新消息对象。
        """
        # 保存原始内容（如果尚未保存）
        if not message.db_record_id:
            db_id = await self.repository.save(conversation_id, message)
            message.db_record_id = db_id
        
        # 生成替换内容
        summary_text = summary_template.format(**summary_params)
        replacement = f"[已压缩|db_id:{message.db_record_id}|{summary_text}|原长度:{message.token_count}tokens]"
        
        # 创建新消息对象（保留原始内容引用）
        archived_msg = Message(
            id=message.id,
            role=message.role,
            content=replacement,
            timestamp=message.timestamp,
            turn_number=message.turn_number,
            original_content=message.content,
            compression_type=compression_type,
            compression_metadata={
                "db_id": message.db_record_id,
                "original_tokens": message.token_count,
                "summary": summary_text
            },
            tool_name=message.tool_name,
            tool_parameters=message.tool_parameters,
            db_record_id=message.db_record_id
        )
        return archived_msg
```

### 3.3 智能体主动检索机制

智能体可以通过内置工具主动查询已归档的原始内容。当模型在对话中需要引用被压缩的历史细节时，可调用如下工具。

```python
class ContextRetrievalTool:
    """上下文检索工具，供智能体调用"""
    
    name = "retrieve_archived_context"
    description = """
    根据数据库ID或关键词检索之前被压缩或截断的完整历史内容。
    参数：
    - db_id: 压缩标记中的数据库ID（优先使用）
    - keyword: 关键词搜索
    - time_range: 时间范围
    """
    
    async def execute(self, db_id: str = None, keyword: str = None) -> str:
        if db_id:
            content = await archive_repo.get_by_id(db_id)
            if content:
                return f"已检索到归档内容：\n{content}"
            else:
                return "未找到对应的归档记录。"
        elif keyword:
            results = await archive_repo.search_by_conversation(
                current_conversation_id, keyword=keyword, limit=5
            )
            return self._format_results(results)
        else:
            return "请提供db_id或关键词。"
```

这种设计赋予智能体**自主记忆回溯能力**：当发现压缩标记中的摘要信息不足以支撑当前推理时，可主动调用工具获取完整上下文，如同人类查阅笔记或档案。这与MemGPT的“分页式记忆检索”理念相通，但通过数据库索引实现了更直接的存取。

## 四、上下文压缩管道详细设计

### 4.1 管道整体架构

压缩管道在智能体完成回复后、发送下一轮大模型请求前执行，分为三个阶段：

1. **预处理管道**：超长工具/技能结果替换
2. **循环压缩管道**：双阈值驱动的迭代压缩
3. **持久化归档集成**：每一步压缩均自动存储原始内容

```python
class ContextCompressionPipeline:
    def __init__(
        self,
        config: CompressionConfig,
        archive_manager: ArchiveManager,
        conversation_id: str
    ):
        self.config = config
        self.archive_manager = archive_manager
        self.conversation_id = conversation_id
        self.cyclic_compressor = CyclicCompressor(config, archive_manager, conversation_id)
        self.token_estimator = TokenEstimator()

    async def compress(
        self,
        messages: List[Message],
        current_time: datetime,
        current_turn: int
    ) -> List[Message]:
        # 步骤1：预处理超长工具结果
        messages = await self._preprocess_tool_results(messages)
        
        # 步骤2：检查是否触发循环压缩
        current_tokens = self.token_estimator.estimate(messages)
        if current_tokens <= self.config.trigger_threshold:
            return messages
        
        # 步骤3：执行循环压缩
        messages = await self.cyclic_compressor.compress(
            messages, current_time, current_turn
        )
        return messages
```

### 4.2 预处理管道：超长工具/技能结果替换

**触发条件**：单条工具调用结果超过 `TOOL_RESULT_TOKEN_THRESHOLD`（建议2000 tokens）。

**处理逻辑**：将结果归档并替换为包含数据库ID和工具元信息的标记。

```python
TOOL_RESULT_TOKEN_THRESHOLD = 2000

async def _preprocess_tool_results(self, messages: List[Message]) -> List[Message]:
    processed = []
    for msg in messages:
        if (msg.role == MessageRole.TOOL and 
            msg.token_count > TOOL_RESULT_TOKEN_THRESHOLD):
            
            # 归档原始内容，生成替换标记
            archived_msg = await self.archive_manager.archive_and_replace(
                self.conversation_id,
                msg,
                CompressionType.TOOL_RESULT_REPLACED,
                "技能:{tool}|参数:{params}",
                {
                    "tool": msg.tool_name,
                    "params": self._format_params(msg.tool_parameters)
                }
            )
            processed.append(archived_msg)
        else:
            processed.append(msg)
    return processed
```

### 4.3 循环压缩管道核心逻辑

```python
class CyclicCompressor:
    def __init__(self, config, archive_manager, conversation_id):
        self.config = config
        self.archive_manager = archive_manager
        self.conversation_id = conversation_id
        self.token_estimator = TokenEstimator()
        self.cycle_count = 0

    async def compress(
        self,
        messages: List[Message],
        current_time: datetime,
        current_turn: int
    ) -> List[Message]:
        current_messages = messages
        current_tokens = self.token_estimator.estimate(current_messages)

        while (current_tokens > self.config.trigger_threshold and
               self.cycle_count < self.config.max_cycles):
            
            # 远古记忆替换
            ancient_threshold = self._calculate_ancient_threshold(self.cycle_count)
            current_messages = await self._replace_ancient_memory(
                current_messages, current_time, current_turn, ancient_threshold
            )
            
            current_tokens = self.token_estimator.estimate(current_messages)
            if current_tokens <= self.config.target_threshold:
                break

            # 摘要管道
            summary_level = self._get_summary_level(self.cycle_count)
            current_messages = await self._summarize_by_level(current_messages, summary_level)
            
            current_tokens = self.token_estimator.estimate(current_messages)
            self.cycle_count += 1

        # 记录压缩日志
        await self._log_compression(messages, current_messages)
        return current_messages
```

### 4.4 策略一：远古记忆替换（集成归档）

```python
async def _replace_ancient_memory(
    self,
    messages: List[Message],
    current_time: datetime,
    current_turn: int,
    threshold: tuple
) -> List[Message]:
    days_threshold, turns_threshold = threshold
    replaced = []
    
    for msg in messages:
        age_days = msg.get_age_days(current_time)
        age_turns = msg.get_age_turns(current_turn)
        
        if (age_days > days_threshold and
            age_turns > turns_threshold and
            msg.compression_type == CompressionType.NONE and
            msg.role in [MessageRole.USER, MessageRole.ASSISTANT]):
            
            # 归档并生成替换标记
            archived_msg = await self.archive_manager.archive_and_replace(
                self.conversation_id,
                msg,
                CompressionType.ANCIENT_MEMORY_REPLACED,
                "时间:{time}|用户提问摘要:{summary}",
                {
                    "time": msg.timestamp.strftime("%Y-%m-%d"),
                    "summary": self._generate_brief_summary(msg.content, max_len=30)
                }
            )
            replaced.append(archived_msg)
        else:
            replaced.append(msg)
    
    return replaced
```

**动态阈值递降表**：

| 循环轮次 | 时间阈值 | 轮次阈值 |
|---------|---------|---------|
| 1 | >30天 且 >30轮 | >30天 且 >30轮 |
| 2 | >28天 且 >28轮 | >28天 且 >28轮 |
| 3 | >25天 且 >25轮 | >25天 且 >25轮 |
| 4 | >20天 且 >20轮 | >20天 且 >20轮 |
| 5+ | >15天 且 >15轮 | >15天 且 >15轮 |

### 4.5 策略二：摘要管道（集成归档）

助手思考摘要是摘要管道的第一步，后续可根据循环轮次扩展至工具交互和对话内容。

```python
THINKING_SUMMARY_PROMPT = """
将以下助手的思考过程压缩为简洁摘要，保留关键决策和结论。

思考内容：
{content}

输出格式（不超过150字）：
[思考摘要]: 关键决策是...，结论是...
"""

async def _summarize_thinking(self, messages: List[Message], cycle_index: int) -> List[Message]:
    # 确定摘要范围（如最近29-28轮的思考）
    recent_turns = 30 - cycle_index
    start_turn = max(0, recent_turns - 2)
    end_turn = recent_turns
    
    thinking_msgs = [
        m for m in messages
        if m.role == MessageRole.THINKING
        and start_turn <= m.turn_number <= end_turn
        and m.compression_type == CompressionType.NONE
    ]
    
    if not thinking_msgs:
        return messages
    
    # 合并待摘要内容
    combined = "\n".join([m.content for m in thinking_msgs])
    original_tokens = sum(m.token_count for m in thinking_msgs)
    
    # 调用LLM生成摘要
    summary = await self.llm_summarize(THINKING_SUMMARY_PROMPT.format(content=combined))
    
    # 将原始思考内容归档，创建一条代表摘要的新消息
    # 这里需要将多个思考消息合并为一条摘要消息，原始内容分别存储
    
    # 简化实现：创建一个聚合归档记录
    db_id = await self._archive_aggregated_content(thinking_msgs, summary)
    
    # 创建摘要消息，替换原有的多条思考消息
    summary_msg = Message(
        id=str(uuid.uuid4()),
        role=MessageRole.THINKING,
        content=f"[已摘要|db_id:{db_id}|思考摘要:{summary}|原长度:{original_tokens}tokens]",
        timestamp=thinking_msgs[-1].timestamp,
        turn_number=thinking_msgs[-1].turn_number,
        original_content=combined,
        compression_type=CompressionType.THINKING_SUMMARIZED,
        compression_metadata={"db_id": db_id, "original_tokens": original_tokens},
        token_count=self.token_estimator.estimate_text(summary)
    )
    
    # 替换消息列表
    return self._replace_messages(messages, thinking_msgs, summary_msg)
```

## 五、完整配置与参数建议

### 5.1 阈值配置（以128K上下文窗口为例）

| 参数 | 建议值 | 说明 |
|-----|-------|------|
| `trigger_threshold` | 100,000 tokens | 约78%窗口容量时触发压缩 |
| `target_threshold` | 80,000 tokens | 压缩目标为62%窗口容量，留出缓冲 |
| `tool_result_threshold` | 2,000 tokens | 单条工具结果超过此值即替换 |
| `max_cycles` | 5 | 最大循环次数，防止死循环 |
| `base_ancient_days` | 30 | 远古记忆基础天数阈值 |
| `base_ancient_turns` | 30 | 远古记忆基础轮次阈值 |

### 5.2 数据库连接配置

建议使用连接池，并启用异步驱动（如 `asyncpg`、`aiomysql`），避免归档操作阻塞主流程。

## 六、工程实现要点

### 6.1 异步压缩与后台任务

压缩操作（尤其是LLM摘要和数据库写入）应异步执行，不阻塞智能体回复生成。可采用消息队列或后台任务处理器：

```python
async def handle_conversation_turn(request):
    # 1. 生成智能体回复
    response = await agent.generate_response(messages)
    
    # 2. 异步提交压缩任务（不等待完成）
    asyncio.create_task(
        compression_pipeline.compress(messages, current_time, current_turn)
    )
    
    # 3. 立即返回响应
    return response
```

### 6.2 压缩日志与可观测性

每次压缩记录详细日志，便于调优：

```python
async def _log_compression(self, before: List[Message], after: List[Message]):
    log_entry = {
        "conversation_id": self.conversation_id,
        "cycle_index": self.cycle_count,
        "tokens_before": self.token_estimator.estimate(before),
        "tokens_after": self.token_estimator.estimate(after),
        "messages_before": len(before),
        "messages_after": len(after),
        "compression_ratio": len(after) / len(before) if before else 1.0
    }
    await self.log_repository.save(log_entry)
```

### 6.3 智能体检索工具的集成

将 `ContextRetrievalTool` 注册到智能体的工具列表中，并确保工具执行时能访问当前的 `conversation_id` 和归档仓储实例。

```python
tools = [
    ContextRetrievalTool(archive_repo, conversation_id),
    # ... 其他工具
]
```

### 6.4 安全与隐私考虑

- 敏感信息脱敏：在归档前可对内容进行敏感词过滤或脱敏处理。
- 数据保留策略：设置归档数据的自动过期时间（如90天），符合数据合规要求。
- 访问控制：检索工具应验证调用者权限，防止跨会话数据泄露。

## 七、总结

本设计方案提供了一套完整的智能体上下文压缩与持久化检索参考实现。通过**管道化压缩流程**、**双阈值触发机制**、**分层摘要策略**以及**数据库归档与索引**，实现了以下核心价值：

- **高效压缩**：在保障关键信息不丢失的前提下，将上下文长度控制在模型窗口的安全范围内。
- **可恢复性**：所有被压缩内容均存储于数据库，智能体可通过工具主动检索，解决了传统截断或摘要的不可逆信息损失问题。
- **工程可行性**：提供了数据结构、数据库表、核心代码逻辑及配置建议，可直接指导开发落地。

该设计已在概念上融合了ACON、MemGPT、Deep Agents SDK等业界先进实践，并创新性地加入了**自主索引检索**机制，使智能体具备类似人类“查阅笔记”的记忆增强能力，适用于需要长期多轮对话、复杂工具调用、知识密集型任务的AI智能体系统。