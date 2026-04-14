### 项目名称：SkillCraft —— 基于 DST 与人在环的 Agent 技能自生成模块

### 1. 架构概览
让 Agent 自主从经验中学习、并自动沉淀为知识资产的能力。
该模块作为 Agent 核心调度器的一个 **中间件 (Middleware)** 或 **AOP 切面** 运行。

- **对话状态追踪 (DST)**：在内存中维护一个 `SkillSession` 对象，实时记录 Agent 的思考-行动-观察循环。
- **触发器 (Trigger)**：在任务结束或用户主动打断时，评估会话价值。
- **渲染器 (Renderer)**：将技术性的 JSON 操作链，翻译成用户可读的 **Markdown 技能卡**。
- **确认接口 (Confirmation API)**：通过 WebSocket/SSE 向前端推送卡片，接收确认指令。

### 2. 核心数据结构设计

这是开发的**底座**，定义清楚数据结构才能保证 DST 追踪不出错。

#### 2.1 DST 状态槽位 (SkillSession)

```python
class SkillSession:
    session_id: str           # 本次对话唯一ID
    start_time: datetime      # 任务开始时间
    user_query: str           # 用户原始提问
    intent: str               # 最终识别的意图分类
    actions: List[ActionNode] # 核心：操作轨迹列表
    final_output: str         # 最终展示给用户的回复
    status: str               # "active", "completed", "aborted"
    corrections: int          # 用户纠正次数（说"不对，用百度搜"算一次）
    tool_call_count: int      # 工具调用次数
```

#### 2.2 操作节点 (ActionNode)

这是生成技能步骤的**原子单位**。

```json
{
  "step_id": 3,
  "type": "tool_call",        // 枚举：thought / tool_call / observation / user_correction
  "tool_name": "web_search",
  "input_params": {
    "query": "2026年 AI 趋势",
    "source": "arxiv"
  },
  "output_summary": "返回了5篇论文摘要...", // 截断处理，防溢出
  "duration_ms": 1240,
  "is_error": false,
  "error_recovery": null     // 如果出错后重试，记录重试策略
}
```

### 3. 触发机制设计（何时弹出卡片？）

我们不希望 Agent 查个天气就弹窗，也不希望做完超复杂任务不弹窗。设定如下**量化阈值**：

| 触发条件 | 逻辑判断代码伪实现 | 设计意图 |
| :--- | :--- | :--- |
| **复杂度达标** | `len(session.actions) >= 5` | 5步以上通常具备复用价值。 |
| **含金量达标** | `session.corrections > 0` | 用户纠正过，说明有独特偏好，必须记录。 |
| **成本意识** | `total_time > 60s or total_tokens > 5000` | 耗时耗钱的任务，值得固化下来下次省成本。 |
| **主动触发** | 用户输入 `/save` 或点击界面"保存流程"按钮 | 用户觉得好才是真的好。 |

**逻辑流程图：**
```text
Agent 发出 [DONE] 信号结束流式输出
    ↓
检查触发器条件 (Threshold Check)
    ↓
[ 通过 ] → 调用 SkillCardGenerator → 推送 WebSocket 消息到前端
[ 不通过 ] → 静默丢弃 DST 记录，释放内存
```

### 4. 卡片消息协议与前端交互设计

这是 **Human-in-the-Loop** 的关键界面。

#### 4.1 后端推送数据结构 (WebSocket Payload)

```json
{
  "type": "SKILL_CRAFT_PROPOSAL",
  "data": {
    "draft_id": "sess_20260413_001",
    "preview": {
      "title": "📄 学术文献检索与综述生成",
      "description": "自动搜索 Arxiv 最新论文，总结摘要，并以表格形式输出对比结果。",
      "steps_markdown": "1. 解析用户主题词...\n2. 并行搜索 Arxiv API...",
      "estimated_save_time": "< 1s"
    },
    "actions": [
      { "label": "✅ 保存为技能", "value": "save" },
      { "label": "✏️ 编辑后保存", "value": "edit" },
      { "label": "🗑️ 忽略", "value": "ignore" }
    ]
  }
}
```

#### 4.2 前端 UI 渲染建议

采用 **非模态、可关闭的卡片通知**，位置通常在右下角。

> **UI 描述：**
> 卡片标题：发现可复用流程
> 正文区域展示简化的步骤列表（最多显示前3步，折叠后续）。
> 三个按钮：保存 / 编辑 / 忽略。
> *（附：点击"编辑"后展开 Monaco Editor 或简易 Markdown 编辑器）。*

### 5. 技能生成器核心算法

这是将 `ActionNode` 列表转化为 `SKILL.md` 文件的 Prompt 工程逻辑。

**开发语言：** Python (Pydantic 模型验证)

**函数定义：**
```python
def generate_skill_content(session: SkillSession, edit_feedback: str = None) -> str:
    """
    输入 DST 追踪到的动作序列，输出标准 Hermes 格式的 SKILL.md 字符串。
    """
    # 1. 过滤噪音：移除纯 Observation 节点，只保留 Thought 和 Action
    clean_steps = [a for a in session.actions if a.type in ["thought", "tool_call"]]

    # 2. 构建 Prompt (此处需调用 LLM 进行润色，而不是简单拼接)
    prompt = f"""
    你是一个技术文档专家。请根据以下 Agent 执行日志，生成一份专业的技能文档。

    ## 要求
    - 名称：根据操作提炼一个动词短语（如：生成竞品分析报告）。
    - 触发条件：一句话描述什么时候用。
    - 步骤：使用祈使句，清晰指示每一步做什么，保留关键参数占位符 `{{{{query}}}}`。
    - 输出格式：Markdown。

    ## 原始执行轨迹
    {clean_steps}
    """
    
    # 3. 调用 LLM 生成结构化文档
    skill_md = llm.invoke(prompt)
    return skill_md
```

### 6. 参数脱敏与隐私保护（关键安全设计）

在生成预览卡片前，必须执行 **字段混淆**，否则会泄露 API Key。

**规则引擎配置：**
```python
SENSITIVE_KEYWORDS = ["password", "token", "api_key", "secret", "authorization", "cookie"]

def redact_params(action_node: ActionNode) -> ActionNode:
    for key in list(action_node.input_params.keys()):
        if any(sensitive in key.lower() for sensitive in SENSITIVE_KEYWORDS):
            action_node.input_params[key] = "<YOUR_SECRET_HERE>"
    return action_node
```

### 7. 持久化与技能加载

用户点击确认后，后端执行文件写入操作。

- **路径规则**：`~/.agent/skills/user_generated/{skill_slug}/SKILL.md`
- **元数据记录**：同级目录生成 `metadata.json`，记录生成时间、来源会话 ID、用户修改记录，便于后续 **反馈学习**。

### 8. 开发排期建议（总计约 3-5 人日）

| 阶段 | 任务 | 预估工时 |
| :--- | :--- | :--- |
| **Day 1** | 定义 `SkillSession` 和 `ActionNode` 数据模型，在 Agent 循环中埋点记录。 | 0.5d |
| **Day 2** | 实现触发器逻辑与内存存储。 | 0.5d |
| **Day 3** | 编写 Prompt 模板，调试 LLM 生成效果（这是核心体验）。 | 1.0d |
| **Day 4** | 前端卡片组件开发与 WebSocket 联调。 | 1.0d |
| **Day 5** | 文件 IO 写入与敏感词过滤测试。 | 0.5d |

### 9. 进阶功能预留接口

文档最后建议预留两个回调函数，方便后续迭代：

1.  **`on_skill_used(skill_name)`**：统计技能使用频率，未来可以做技能排行榜。
2.  **`on_skill_edited(old_version, new_version)`**：收集人类编辑数据，作为 DPO 训练数据储备。

这份文档涵盖了从数据定义到前后端交互的全链路细节，可以直接交给开发团队启动编码了。如果对具体的 Prompt 模板需要更多示例，我们可以进一步细化。