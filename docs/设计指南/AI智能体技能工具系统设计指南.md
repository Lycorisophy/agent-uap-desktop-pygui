# AI智能体技能工具系统设计指南

> 文档版本：1.0
> 更新时间：2026-04-12
> 整理人：LySoY and His Agent Team

## 一、概述

### 1.1 什么是AI智能体的技能工具系统

AI智能体的**技能工具系统（Skills/Tools System）** 是让大语言模型（LLM）与外部世界交互的核心能力架构。它将LLM从"只会回答问题"升级为"能够动手执行任务"的关键技术。

```
┌─────────────────────────────────────────────────────────────────┐
│                     AI 智能体技能工具系统                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐         │
│  │   用户输入   │───→│    LLM     │───→│  工具执行   │         │
│  └─────────────┘    └──────┬──────┘    └──────┬──────┘         │
│                            │                    │                 │
│                            │   工具调用协议      │                 │
│                            │   (MCP/FuncCall)   │                 │
│                            │                    ↓                 │
│                      ┌─────┴─────┐      ┌─────────────┐         │
│                      │  技能系统  │      │  外部世界   │         │
│                      │  (Tools)   │─────→│  (API/DB/FS)│         │
│                      └───────────┘      └─────────────┘         │
│                                                                 │
│  核心价值：让AI从"大脑"进化为"四肢健全的智能体"                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 技能 vs 工具 概念辨析

| 概念 | 定义 | 示例 |
|------|------|------|
| **Tool（工具）** | 单一可执行函数/API | `get_weather(location)` |
| **Skill（技能）** | 包含元数据+指令+资源的完整能力包 | 带使用说明的搜索技能 |
| **Plugin（插件）** | 可动态加载的功能扩展单元 | 第三方开发的天气插件 |
| **Action（行动）** | 智能体执行的具体操作步骤 | 点击按钮、发送消息 |

### 1.3 技能工具系统的核心价值

```
能力扩展 ─────→ 突破LLM知识边界，获取实时信息
             ↓
任务执行 ─────→ 不仅仅是回答，而是真正完成任务
             ↓
自动化 ───────→ 串联多工具实现复杂工作流
             ↓
自主性 ───────→ 从"AI建议"到"AI执行"的跨越
```

---

## 二、主流工具调用协议

### 2.1 MCP（Model Context Protocol）

#### 2.1.1 MCP概述

**MCP** 是Anthropic于2024年11月发布的开放协议，被誉为"AI工具生态的USB标准"，旨在解决AI模型与外部工具交互的碎片化问题。

```
┌─────────────────────────────────────────────────────────────────┐
│                        MCP 协议架构                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────────────────────────────────────┐          │
│   │              AI 应用层                           │          │
│   │   (Claude Code / OpenClaw / Cursor / VS Code)  │          │
│   └──────────────────────┬──────────────────────────┘          │
│                          │ MCP Protocol                        │
│   ┌──────────────────────┴──────────────────────────┐          │
│   │              MCP Host (主机)                      │          │
│   │   - 管理连接生命周期                              │          │
│   │   - 安全上下文隔离                                │          │
│   │   - 请求路由与响应聚合                            │          │
│   └──────────────────────┬──────────────────────────┘          │
│                          │                                     │
│   ┌──────────────────────┴──────────────────────────┐          │
│   │           MCP Servers (服务器矩阵)                 │          │
│   │                                                    │          │
│   │   ┌─────────┐  ┌─────────┐  ┌─────────┐          │          │
│   │   │  Files  │  │   Git   │  │ Slack   │   ...   │          │
│   │   │ System  │  │  Hub    │  │         │          │          │
│   │   └─────────┘  └─────────┘  └─────────┘          │          │
│   │                                                    │          │
│   └─────────────────────────────────────────────────────┘          │
│                                                                 │
│   MCP = USB之于硬件设备的标准协议                                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.1.2 MCP核心特性

| 特性 | 说明 | 优势 |
|------|------|------|
| **标准化接口** | 统一的数据格式和通信协议 | 一次开发，多处复用 |
| **双向通信** | 支持工具调用和数据回传 | 真正的交互式执行 |
| **上下文共享** | 多工具共享对话上下文 | 减少冗余传递 |
| **安全隔离** | 每个MCP Server独立沙箱 | 降低安全风险 |
| **热插拔** | 运行时动态加载/卸载 | 灵活扩展 |

#### 2.1.3 MCP协议结构

```json
// MCP 工具定义示例
{
  "name": "filesystem_read",
  "description": "读取本地文件内容",
  "inputSchema": {
    "type": "object",
    "properties": {
      "path": {
        "type": "string",
        "description": "文件路径"
      },
      "encoding": {
        "type": "string",
        "default": "utf-8"
      }
    },
    "required": ["path"]
  }
}
```

#### 2.1.4 MCP vs 传统Function Calling

| 维度 | MCP | 传统Function Calling |
|------|-----|---------------------|
| **标准化** | 跨平台统一协议 | 各厂商私有格式 |
| **扩展性** | 动态加载MCP Server | 需重新部署 |
| **数据流** | 双向、状态保持 | 单次请求-响应 |
| **上下文** | 共享上下文空间 | 每次独立调用 |
| **适用场景** | 复杂多工具协作 | 简单工具调用 |

### 2.2 OpenAI Function Calling

#### 2.2.1 协议概述

OpenAI于2023年6月率先推出Function Calling，成为行业事实标准。

```json
// OpenAI 工具定义
{
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "get_weather",
        "description": "获取指定城市的天气信息",
        "parameters": {
          "type": "object",
          "properties": {
            "location": {
              "type": "string",
              "description": "城市名称"
            },
            "unit": {
              "type": "string",
              "enum": ["celsius", "fahrenheit"]
            }
},
          "required": ["location"]
        }
      }
    }
  ]
}
```

#### 2.2.2 调用流程

```
用户输入: "北京今天天气怎么样？"
         ↓
┌─────────────────────────────────────────────┐
│ LLM识别需要调用 get_weather                  │
│ 生成结构化调用:                              │
│ {                                            │
│   "name": "get_weather",                    │
│   "arguments": {"location": "北京"}          │
│ }                                            │
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│ 本地/服务端执行工具函数                       │
│ 返回: {"temperature": 22, "condition": "晴"}│
└─────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────┐
│ LLM整合结果生成最终回复                      │
│ "北京今天天气晴朗，气温22摄氏度..."          │
└─────────────────────────────────────────────┘
```

### 2.3 Anthropic Tool Use

#### 2.3.1 Claude Tool Use特性

Anthropic于2024年推出Tool Use，强调**动态发现和学习**能力。

| 特性 | 说明 |
|------|------|
| **动态工具发现** | Agent可发现并学习新工具 |
| **增强推理** | "think"工具支持复杂推理暂停 |
| **批量观察** | 一次性收集多个工具结果 |
| **结构化输出** | 支持复杂JSON Schema |

#### 2.3.2 Claude Tool Use代码示例

```python
from anthropic import Anthropic

client = Anthropic()

response = client.messages.create(
    model="claude-opus-4-5",
    max_tokens=1024,
    tools=[
        {
            "name": "计算机",
            "description": "控制用户的计算机",
            "input_schema": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["screenshot", "mouse_move", "type"]
                    },
                    "coordinate": {"type": "object"}
                }
            }
        }
    ],
    messages=[{"role": "user", "content": "帮我截个屏"}]
)
```

### 2.4 协议对比总结

| 协议 | 推出方 | 年份 | 核心特点 | 适用场景 |
|------|--------|------|----------|----------|
| **Function Calling** | OpenAI | 2023 | 简单可靠 | 单一工具调用 |
| **Tool Use** | Anthropic | 2024 | 动态发现 | Claude生态 |
| **MCP** | Anthropic/CNCF | 2024 | 标准化生态 | 多工具复杂协作 |
| **Tools API** | Google | 2024 | Gemini集成 | Google生态 |

---

## 三、主流智能体平台技能系统

### 3.1 OpenClaw Skills 技能系统

#### 3.1.1 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      OpenClaw Skills 系统                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────────────────────────────────────┐           │
│   │               Skills 加载器                      │           │
│   │   ┌─────────┐  ┌─────────┐  ┌─────────┐         │           │
│   │   │ 元数据   │  │ 核心指令 │  │ 资源文件 │         │           │
│   │   │Metadata │  │Prompt   │  │Assets   │         │           │
│   │   └─────────┘  └─────────┘  └─────────┘         │           │
│   └──────────────────────┬──────────────────────────┘           │
│                          │                                      │
│   ┌──────────────────────┴──────────────────────────┐           │
│   │              渐进式披露 (Progressive Reveal)     │           │
│   │                                                    │           │
│   │   Phase 1: 技能名 + 简短描述 → 触发匹配          │           │
│   │   Phase 2: 完整使用说明 → 深入执行               │           │
│   │   Phase 3: 资源/脚本 → 专业能力                  │           │
│   └─────────────────────────────────────────────────┘           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

##### 3.1.2 安全分级 (Security Level)

OpenClaw Skills支持基于元信息标签的安全分级机制，在skill.json中定义技能的操作类型和安全等级，服务端根据安全等级执行不同的权限控制策略。

**skill.json 安全分级配置示例：**

```json
{
  "name": "file_write",
  "version": "1.0.0",
  "description": "写入本地文件",
  "author": "OpenClaw Team",
  "tags": ["file", "write", "storage"],
  "triggers": ["写文件", "创建文件", "write file"],
  
  "security": {
    "operation_type": "write",
    "security_level": "high",
    "platforms": ["windows", "mac", "linux"]
  },
  
  "permissions": ["filesystem:write"],
  "required_envs": [],
  "capabilities": {
    "max_tokens": 2000,
    "timeout": 30
  }
}
```

**安全分级策略表：**

| 安全等级 | 操作类型 | 执行策略 | 适用场景 |
|----------|----------|----------|----------|
| **low** | read | 自动执行，无需确认 | 只读查询类操作 |
| **medium** | query | 自动执行，记录日志 | 数据查询、统计 |
| **high** | write | 用户确认后执行 | 文件写入、配置修改 |
| **critical** | delete/execute | 双重确认+超时验证 | 删除、危险执行操作 |

**服务端安全分级执行器：**

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class SecurityLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class OperationType(Enum):
    READ = "read"
    QUERY = "query"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"

@dataclass
class SecurityPolicy:
    level: SecurityLevel
    operation: OperationType
    platforms: list[str]

class SecurityGate:
    """安全闸门 - 根据安全等级执行不同策略"""
    
    def __init__(self):
        self.audit_logger = AuditLogger()
    
    async def check_and_execute(
        self,
        skill: dict,
        args: dict,
        user_context: dict,
        platform: str
    ) -> ExecutionResult:
        """执行安全检查"""
        security = skill.get("security", {})
        level = SecurityLevel(security.get("security_level", "medium"))
        operation = OperationType(security.get("operation_type", "read"))
        allowed_platforms = security.get("platforms", [])
        
        # 平台检查
        if allowed_platforms and platform not in allowed_platforms:
            return ExecutionResult(
                allowed=False,
                error=f"Platform {platform} not supported"
            )
        
        # 权限检查
        if not self._check_permissions(skill, user_context):
            return ExecutionResult(
                allowed=False,
                error="Insufficient permissions"
            )
        
        # 安全等级策略
        if level == SecurityLevel.LOW:
            # low级别：直接执行
            return await self._direct_execute(skill, args)
        
        elif level == SecurityLevel.MEDIUM:
            # medium级别：执行并记录日志
            result = await self._direct_execute(skill, args)
            self.audit_logger.log(skill["name"], args, user_context, result)
            return result
        
        elif level == SecurityLevel.HIGH:
            # high级别：需要用户确认
            if not user_context.get("confirmed"):
                return ExecutionResult(
                    allowed=False,
                    requires_confirmation=True,
                    message=f"技能 '{skill['name']}' 需要确认执行"
                )
            return await self._direct_execute(skill, args)
        
        elif level == SecurityLevel.CRITICAL:
            # critical级别：双重确认
            confirmations = user_context.get("confirmations", [])
            if len(confirmations) < 2:
                return ExecutionResult(
                    allowed=False,
                    requires_confirmation=True,
                    message=f"危险操作 '{skill['name']}' 需要双重确认",
                    confirmation_steps=["用户首次确认", "超时倒计时确认"]
                )
            return await self._direct_execute(skill, args)
    
    def _check_permissions(self, skill: dict, user_context: dict) -> bool:
        """检查用户权限"""
        required_perms = skill.get("permissions", [])
        user_perms = user_context.get("permissions", [])
        return all(p in user_perms for p in required_perms)
```

**渐进式披露 + 安全分级 完整流程：**

```
┌─────────────────────────────────────────────────────────────────┐
│         技能发现 → 安全检查 → 用户确认 → 执行 → 审计日志           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Phase 1: 技能发现 (低信息量)                                    │
│  ─────────────────────────────────────────────────────────────  │
│  ┌────────────────────────────────────────────────────────────┐ │
│  │ skill.json (元数据)                                        │ │
│  │ - name: "file_write"                                       │ │
│  │ - description: "写入本地文件"                               │ │
│  │ - triggers: ["写文件", "创建文件"]                          │ │
│  └────────────────────────────────────────────────────────────┘ │
│                            ↓                                    │
│  Phase 2: 安全分级判断                                          │
│  ─────────────────────────────────────────────────────────────  │
│  security: {                                                     │
│    "operation_type": "write",     → operation_type 判断          │
│    "security_level": "high",      → 触发用户确认                 │
│    "platforms": ["windows"]       → 平台验证                    │
│  }                                                              │
│                            ↓                                    │
│  Phase 3: 执行策略│
│  ─────────────────────────────────────────────────────────────  │
│  Level=LOW/MEDIUM  → 自动执行 → 记录日志                          │
│  Level=HIGH        → 用户确认 → 执行                              │
│  Level=CRITICAL   → 双重确认 → 超时验证 → 执行                    │
│                            ↓                                    │
│  Phase 4: 审计归档                                               │
│  ─────────────────────────────────────────────────────────────  │
│  记录: 时间戳 | 技能名 | 操作类型 | 安全等级 | 执行结果 | 用户ID   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 3.1.3 技能目录结构

```
skills/
└── my_custom_skill/
    ├── skill.json          # 元数据配置
    ├── README.md           # 使用说明
    ├── prompt.md           # 核心指令
    └── resources/          # 资源文件
        ├── script.py       # 辅助脚本
        └── template.md     # 模板文件
```

#### 3.1.4 skill.json 配置示例

```json
{
  "name": "web_search",
  "version": "1.0.0",
  "description": "网络搜索技能",
  "author": "OpenClaw Team",
  "tags": ["search", "web", "information"],
  "triggers": ["搜索", "查找", "search", "find"],
  "required_envs": ["SEARCH_API_KEY"],
  "permissions": ["network"],
  "capabilities": {
    "max_tokens": 2000,
    "timeout": 30
  }
}
```

#### 3.1.5 OpenClaw技能生态

| 类别 | 示例技能 | 功能 |
|------|----------|------|
| **效率工具** | 日程管理、邮件处理 | 自动化办公 |
| **技术开发** | Git操作、代码审查 | 开发辅助 |
| **智能家居** | 设备控制、场景联动 | IoT集成 |
| **信息检索** | 搜索、爬虫、数据分析 | 知识获取 |
| **多媒体** | 图像生成、视频处理 | 内容创作 |

### 3.2 DeerFlow 技能系统

#### 3.2.1 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                      DeerFlow 技能系统                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌─────────────────────────────────────────────────┐           │
│   │              14层中间件管道                        │           │
│   │                                                    │           │
│   │   Request → Logging → Auth → RateLimit → ...     │           │
│   │            → Validation → Transform → Skills     │           │
│   │            → Execute → Transform → Response      │           │
│   └──────────────────────┬──────────────────────────┘           │
│                          │                                      │
│   ┌──────────────────────┴──────────────────────────┐           │
│   │              技能注册表 (Skill Registry)         │           │
│   │                                                    │           │
│   │   @skill("search")                               │           │
│   │   @skill("code_executor")                        │           │
│   │   @skill("file_reader")                          │           │
│   └─────────────────────────────────────────────────┘           │
│                                                                 │
│   特色: Python装饰器风格的技能注册                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 3.2.2 技能定义示例

```python
from deerflow import skill, SkillsManager

@skill(
    name="web_search",
    description="执行网络搜索",
    params=["query", "limit"]
)
async def web_search(query: str, limit: int = 10):
    """网络搜索实现"""
    results = await search_engine.search(query, limit)
    return format_results(results)

# 注册技能
SkillsManager.register(web_search)
```

#### 3.2.3 技能分类

| 类型 | 描述 | 示例 |
|------|------|------|
| **内置技能** | 框架自带核心功能 | 搜索、计算、文件读写 |
| **自定义技能** | 用户开发的扩展 | 业务API集成 |
| **MCP技能** | 协议兼容技能 | Google Drive、Slack |

### 3.3 Claude Code 工具系统

#### 3.3.1 工具类型

```
┌─────────────────────────────────────────────────────────────────┐
│                    Claude Code 内置工具                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │  Bash/Terminal│  │   File Ops   │  │  Glob/Search │          │
│  │  执行命令     │  │ 读写文件     │  │  模式匹配    │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │    Grep       │  │    Edit      │  │   Read       │          │
│  │  内容搜索     │  │  增量修改    │  │   完整读取   │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐                             │
│  │   WebFetch   │  │   NotifSend  │                             │
│  │  网页抓取    │  │  发送通知    │                             │
│  └──────────────┘  └──────────────┘                             │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 3.3.2 最佳实践：CLAUDE.md配置

```markdown
# CLAUDE.md - Claude Code 项目配置

## 项目概述
这是一个React电商后台管理系统。

## 技术栈
- React 18 + TypeScript
- Ant Design 5
- Redux Toolkit
- React Router 6

## 代码规范
- 组件使用函数式组件 + Hooks
- 优先使用TypeScript类型而非any
- API调用统一封装在services/目录

## 项目结构
src/
├── components/   # UI组件
├── pages/        # 页面组件
├── services/     # API服务
├── store/        # Redux状态
└── utils/        # 工具函数

## 常用命令
- npm run dev: 启动开发服务器
- npm run build: 生产构建
- npm test: 运行测试

## 注意事项
- 修改store前先看reducer结构
- API错误统一在services层处理
```

#### 3.3.3 工具使用原则

| 原则 | 说明 | 实践 |
|------|------|------|
| **原子性** | 单一工具做一件事 | 读写分离 |
| **幂等性** | 多次执行结果一致 | 使用绝对路径 |
| **可观测** | 操作结果可验证 | 读取验证 |
| **最小权限** | 只申请必需权限 | 沙箱执行 |

### 3.4 主流平台技能系统对比

| 平台 | 技能格式 | 注册方式 | 扩展性 | 特色 |
|------|----------|----------|--------|------|
| **OpenClaw** | skill.json + MD | 目录扫描 | 高 | 渐进式披露 |
| **DeerFlow** | Python装饰器 | @skill装饰器 | 中 | 14层中间件 |
| **Claude Code** | 内置工具集 | 不支持自定义 | 低 | 与文件系统深度集成 |
| **LangChain** | Python类 | add_tools() | 高 | 生态丰富 |
| **CrewAI** | @tool装饰器 | 装饰器注册 | 中 | 角色绑定 |

---

## 四、企业级工具调用综合方案

### 4.1 方案概述

本方案来自参考文档，融合**容错纠错层**与**异步流式执行**，适合生产环境部署。

```
┌─────────────────────────────────────────────────────────────────┐
│              企业级Agent工具调用架构（L0-R层）                    │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  LLM 流式输出 (chunk by chunk)                                  │
│         ↓                                                       │
│  【L0】流式接收 & 增量解析（tool_calls 片段）                      │
│         ↓                                                       │
│  【L1】实时纠错层（轻量模糊匹配）                                  │
│         ↓                                                       │
│  【L2】参数完整性判断（必填字段收集）                              │
│         ↓ 满足触发条件                                           │
│  【L3】异步执行器（非阻塞，结果缓存）                              │
│         ↓ 失败且可重试                                           │
│  【R】执行重试与错误分类                                          │
│         ↓                                                       │
│  【L4】最终回复与结果合并                                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 核心模块详解

#### 4.2.1 L0: 流式接收与增量解析

```python
import json
from typing import Dict, Optional

class StreamingToolParser:
    """流式工具调用解析器"""
    
    def __init__(self):
        self.buffers: Dict[int, Dict] = {}  # index -> {name, args_str}
    
    def process_chunk(self, delta) -> Optional[Dict]:
        """处理流式增量"""
        if not delta.tool_calls:
            return None
        
        results = []
        for tc in delta.tool_calls:
            idx = tc.index
            
            # 初始化缓冲区
            if idx not in self.buffers:
                self.buffers[idx] = {"name": "", "args_str": ""}
            
            # 更新函数名
            if tc.function.name:
                self.buffers[idx]["name"] = tc.function.name
            
            # 累积参数
            if tc.function.arguments:
                self.buffers[idx]["args_str"] += tc.function.arguments
                
                # 尝试解析JSON
                try:
                    args = json.loads(self.buffers[idx]["args_str"])
                    results.append({
                        "index": idx,
"name": self.buffers[idx]["name"],
                        "arguments": args
                    })
                except json.JSONDecodeError:
                    pass  # 不完整，继续累积
        
        return results if results else None
```

#### 4.2.2 L1: 实时纠错层

```python
from rapidfuzz import fuzz, process

class ToolCorrectionLayer:
    """工具名和参数纠错"""
    
    def __init__(self, valid_tools: list):
        self.valid_names = [t["function"]["name"] for t in valid_tools]
        self.alias_map = self._build_alias_map()
    
    def correct_tool_name(self, name: str, threshold: int = 80) -> str:
        """模糊匹配工具名"""
        if name in self.valid_names:
            return name
        
        match, score, _ = process.extractOne(
            name, self.valid_names, scorer=fuzz.ratio
        )
        return match if score >= threshold else None
    
    def correct_arguments(self, tool_name: str, args: dict) -> dict:
        """参数名纠错和类型转换"""
        schema = self._get_tool_schema(tool_name)
        corrected = {}
        
        for key, value in args.items():
            # 尝试别名映射
            correct_key = self.alias_map.get(tool_name, {}).get(key, key)
            
            # 类型宽松转换
            if correct_key in schema["properties"]:
                expected_type = schema["properties"][correct_key]["type"]
                corrected[correct_key] = self._type_coerce(value, expected_type)
            else:
                corrected[key] = value  # 保留原键
        
        return corrected
    
    def _type_coerce(self, value, expected_type: str):
        """类型宽松转换"""
        if expected_type == "integer" and isinstance(value, str):
            return int(value)
        if expected_type == "number" and isinstance(value, str):
            return float(value)
        return value
```

#### 4.2.3 L2: 参数完整性判断

```python
class ParameterValidator:
    """参数完整性验证"""
    
    def __init__(self, tools_schema: dict):
        self.schema = {t["function"]["name"]: t["function"]["parameters"] 
                       for t in tools_schema}
    
    def is_complete(self, tool_name: str, args: dict) -> bool:
        """检查必填参数是否齐全"""
        if tool_name not in self.schema:
            return False
        
        required = self.schema[tool_name].get("required", [])
        return all(param in args for param in required)
    
    def validate(self, tool_name: str, args: dict) -> tuple[bool, list]:
        """完整验证，返回(是否有效, 错误列表)"""
        errors = []
        
        if tool_name not in self.schema:
            return False, [f"Unknown tool: {tool_name}"]
        
        schema = self.schema[tool_name]
        
        # 检查必填
        for required in schema.get("required", []):
            if required not in args:
                errors.append(f"Missing required: {required}")
        
        # 类型检查
        for key, value in args.items():
            if key in schema["properties"]:
                expected = schema["properties"][key]["type"]
                if not self._check_type(value, expected):
                    errors.append(f"Invalid type for {key}: expected {expected}")
        
        return len(errors) == 0, errors
```

#### 4.2.4 L3: 异步执行器

```python
import asyncio
from typing import Any, Dict, Optional
from dataclasses import dataclass

@dataclass
class ToolResult:
    ok: bool
    result: Any = None
    error: str = None
    tool_call_id: str = None

class AsyncToolExecutor:
    """异步工具执行器"""
    
    def __init__(self, max_concurrent: int = 5):
        self.max_concurrent = max_concurrent
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.cache: Dict[str, ToolResult] = {}
        self.executed: set = set()
    
    async def execute(
        self, 
        tool_name: str, 
        args: dict, 
        tool_call_id: str,
        tools_registry: dict
    ) -> ToolResult:
        """执行工具调用"""
        # 防重复执行
        if tool_call_id in self.executed:
            return self.cache.get(tool_call_id)
        
        async with self.semaphore:
            try:
                tool_func = tools_registry.get(tool_name)
                if not tool_func:
                    return ToolResult(ok=False, error=f"Tool not found: {tool_name}")
                
                result = await tool_func(**args)
                self.cache[tool_call_id] = ToolResult(ok=True, result=result)
                self.executed.add(tool_call_id)
                return self.cache[tool_call_id]
                
            except Exception as e:
                return ToolResult(ok=False, error=str(e))
    
    async def execute_with_retry(
        self,
        tool_name: str,
        args: dict,
        tool_call_id: str,
        tools_registry: dict,
        max_retries: int = 3
    ) -> ToolResult:
        """带重试的执行"""
        for attempt in range(max_retries):
            result = await self.execute(tool_name, args, tool_call_id, tools_registry)
            
            if result.ok:
                return result
            
            # 判断是否可重试
            if not self._is_retryable(result.error):
                break
            
            # 指数退避
            await asyncio.sleep(2 ** attempt)
        
        return result
    
    def _is_retryable(self, error: str) -> bool:
        """判断错误是否可重试"""
        retryable_patterns = ["timeout", "connection", "500", "502", "503"]
        return any(p in error.lower() for p in retryable_patterns)
```

### 4.3 完整工作流示例

```python
import asyncio
from openai import AsyncOpenAI

class ToolCallingAgent:
    """完整工具调用Agent"""
    
    def __init__(self, api_key: str, tools: list, tools_registry: dict):
        self.client = AsyncOpenAI(api_key=api_key)
        self.tools = tools
        self.tools_registry = tools_registry
        self.parser = StreamingToolParser(ToolCorrectionLayer(tools))
        self.validator = ParameterValidator(tools)
        self.executor = AsyncToolExecutor()
    
    async def chat(self, messages: list, stream: bool = True):
        """主对话循环"""
        stream = await self.client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=self.tools,
            stream=stream
        )
        
        tool_buffers = {}
        pending_tasks = []
        
        async for chunk in stream:
            if not chunk.choices:
                continue
            
            delta = chunk.choices[0].delta
            
            # 处理文本输出
            if delta.content:
                yield {"type": "content", "content": delta.content}
            
            # 处理工具调用
            if delta.tool_calls:
                parsed = self.parser.process_chunk(delta)
                if parsed:
                    for item in parsed:
                        idx = item["index"]
                        if idx not in tool_buffers:
                            tool_buffers[idx] = {"triggered": False}
                        
                        tool_buffers[idx].update(item)
                        
                        # 检查是否满足执行条件
                        if (not tool_buffers[idx]["triggered"] and
                            self.validator.is_complete(item["name"], item["arguments"])):
                            
                            tool_buffers[idx]["triggered"] = True
                            task = asyncio.create_task(
                                self.executor.execute_with_retry(
                                    item["name"],
                                    item["arguments"],
                                    f"call_{idx}",
                                    self.tools_registry
                                )
                            )
                            pending_tasks.append(task)
        
        # 等待所有工具执行完成
        if pending_tasks:
            results = await asyncio.gather(*pending_tasks)
            for result in results:
                if result.ok:
                    yield {"type": "tool_result", "result": result.result}
                else:
                    yield {"type": "tool_error", "error": result.error}
```

### 4.4 企业级增强特性

| 特性 | 说明 | 实现建议 |
|------|------|----------|
| **动态降级** | 工具调用延迟高时关闭提前执行 | 超时检测 |
| **结果缓存** | 短时间重复调用返回缓存 | Redis/内存 |
| **安全闸门** | 写操作需用户确认 | 交互式确认 |
| **可观测性** | 埋点纠错率、执行时长 | OpenTelemetry |
| **熔断机制** | 连续失败短暂禁用工具 | 滑动窗口计数 |
| **配置热更新** | 纠错规则动态生效 | 配置中心 |

### 4.5 性能对比

| 指标 | 传统方案 | 本方案 |
|------|----------|--------|
| 端到端延迟（工具1s） | ~3s | ~2s |
| 工具调用成功率 | ~85% | ≥98% |
| Token开销 | 标准 | +5ms/chunk |

---

## 五、ReAct vs ReWOO 工具调用模式

### 5.1 ReAct 模式

#### 5.1.1 原理

**ReAct** = Reason + Act，通过"思考-行动-观察"循环让Agent与环境交互。

```
┌─────────────────────────────────────────────────────────────────┐
│                        ReAct 执行循环                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│       ┌─────────────┐                                           │
│       │   思考      │  Thought: 我需要知道北京天气                │
│       │   (Reason)  │                                           │
│       └──────┬──────┘                                           │
│              ↓                                                  │
│       ┌─────────────┐                                           │
│       │   行动      │  Action: get_weather(location="北京")      │
│       │   (Act)     │                                           │
│       └──────┬──────┘                                           │
│              ↓                                                  │
│       ┌─────────────┐                                           │
│       │   观察      │  Observation: {"temp": 22, "sunny": true} │
│       │ (Observe)   │                                           │
│       └──────┬──────┘                                           │
│              ↓                                                  │
│       ┌─────────────┐                                           │
│       │   思考      │  Thought: 根据观察，北京天气晴朗22度...      │
│       │   (Reason)  │                                           │
│       └──────┬──────┘                                           │
│              ↓                                                  │
│         结束？ ──否─→ 返回"行动"继续循环                          │
│              │                                                  │
│             是                                                   │
│              ↓                                                  │
│       ┌─────────────┐                                           │
│       │   回答      │  Final Answer: 北京今天晴朗，气温22度       │
│       └─────────────┘                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 5.1.2 代码实现

```python
class ReActAgent:
    def __init__(self, llm, tools):
        self.llm = llm
        self.tools = tools
        self.tools_map = {t.name: t for t in tools}
    
    async def run(self, query: str, max_iterations: int = 5):
        messages = [{"role": "user", "content": query}]
        
        for _ in range(max_iterations):
            # LLM决定行动
            response = await self.llm.chat(
                messages=messages,
                tools=self.get_tools_schema()
            )
            
            if not response.tool_calls:
                # 无工具调用，直接返回
                return response.content
            
            # 执行工具
            for call in response.tool_calls:
                tool_name = call.function.name
                args = json.loads(call.function.arguments)
                
                if tool_name in self.tools_map:
                    result = await self.tools_map[tool_name](**args)
                    
                    # 添加观察结果
                    messages.append({
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [call]
                    })
                    messages.append({
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result)
                    })
        
        return "达到最大迭代次数"
```

#### 5.1.3 优缺点

| 优点 | 缺点 |
|------|------|
| 简单直观，易实现 | 每次迭代都要传完整上下文 |
| 可处理复杂多步任务 | Token消耗大 |
| 错误自修正能力强 | 延迟高（串行执行） |

### 5.2 ReWOO 模式

#### 5.2.1 原理

**ReWOO** = Reason Without Observation，将推理与执行解耦，减少Token消耗。

```
┌─────────────────────────────────────────────────────────────────┐
│                       ReWOO 三阶段执行                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  【阶段1】Planner - 规划器                                        │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ 输入: 用户任务                                              │ │
│  │ 输出: 完整计划 (Task List)                                 │ │
│  │                                                             │ │
│  │ Task List:                                                 │ │
│  │ #E1 = Search[query="北京天气"]                             │ │
│  │ #E2 = Calculator[#E1.temp * 9/5 + 32]  # 转华氏度         │ │
│  │ #E3 = Format[#E1, #E2, "天气报告"]                         │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                            ↓                                     │
│  【阶段2】Worker - 执行器                                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ 并行/串行执行 Task List 中的所有任务                       │ │
│  │                                                             │ │
│  │ E1_result = search("北京天气") → {"temp": 22, "sunny": true}│
│  │ E2_result = calc(22 * 9/5 + 32) → 71.6                     │ │
│  │ E3_result = format(...) → "北京天气报告..."                 │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                            ↓                                     │
│  【阶段3】Solver - 合并器                                         │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │ 输入: 原始任务 + Plan + 所有观察结果                         │ │
│  │ 输出: 最终答案                                              │ │
│  │                                                             │ │
│  │ "根据搜索结果，北京今天晴朗，气温22°C (71.6°F)..."          │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### 5.2.2 代码实现

```python
class ReWOOWorker:
    """ReWOO Worker - 执行器"""
    
    async def execute_plan(self, plan: str, tools_registry: dict):
        """执行规划中的所有工具调用"""
        results = {}
        
        # 解析计划（简化版）
        tasks = self._parse_plan(plan)
        
        for task in tasks:
            var_name = task["var"]       # e.g., E1
            tool_name = task["tool"]     # e.g., Search
            args = task["args"]          # {"query": "..."}
            
            # 解析参数中的变量引用
            resolved_args = self._resolve_args(args, results)
            
            # 执行工具
            result = await tools_registry[tool_name](**resolved_args)
            results[var_name] = result
        
        return results
    
    def _parse_plan(self, plan: str) -> list:
        """解析计划文本"""
        # 简化：正则提取 #E1 = Tool[args] 格式
        import re
        pattern = r'(#\w+)\s*=\s*(\w+)\[(.*?)\]'
        matches = re.findall(pattern, plan)
        
        tasks = []
        for var, tool, args_str in matches:
            # 简单参数解析
            args = self._parse_args(args_str)
            tasks.append({"var": var, "tool": tool, "args": args})
        
        return tasks

class ReWOOSolver:
    """ReWOO Solver - 合并器"""
    
    async def solve(self, original_task: str, plan: str, observations: dict):
        """生成最终答案"""
        prompt = f"""任务: {original_task}

执行计划:
{plan}

观察结果:
{json.dumps(observations, ensure_ascii=False, indent=2)}

请基于以上信息，给出最终答案。
"""
        
        return await self.llm.chat(prompt)
```

#### 5.2.3 ReAct vs ReWOO 对比

| 维度 | ReAct | ReWOO |
|------|-------|-------|
| **Token消耗** | 高（每步传递完整上下文） | 低（推理与执行分离） |
| **执行方式** | 串行 | 可并行 |
| **错误恢复** | 自动修正 | 需重新规划 |
| **适用场景** | 简单多步任务 | 复杂复合任务 |
| **实现复杂度** | 低 | 中 |

### 5.3 模式选择建议

```
任务复杂度低 (1-2步)
└─ 选择: Function Calling (无循环)

任务复杂度中 (多步无依赖)
├─ 选择: ReWOO (并行执行)
└─ 原因: Token效率高

任务复杂度高 (多步有依赖)
├─ 选择: ReAct (自动修正)
└─ 原因: 错误自修正能力

实时性要求高
├─ 选择: ReWOO + 异步执行
└─ 原因: 可并行+非阻塞

可靠性要求高
├─ 选择: ReAct + 重试机制
└─ 原因: 自动纠错
```

---

## 六、工具安全与审计

### 6.1 工具风险分类

| 风险类型 | 描述 | 示例 |
|----------|------|------|
| **过度权限** | Agent持有不必要的权限 | 只读任务却拥有写权限 |
| **权限不足** | Agent缺少必要权限导致失败 | 需读文件却无权限 |
| **提示注入** | 恶意工具输出注入指令 | 工具返回含恶意指令 |
| **数据泄露** | Agent暴露敏感信息 | 日志包含API密钥 |
| **资源耗尽** | 工具调用无限制消耗资源 | 无限循环调用 |

### 6.2 安全防护框架 (AgenTRIM)

```
┌─────────────────────────────────────────────────────────────────┐
│                    AgenTRIM 安全框架                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    权限分析层                                ││
│  │   - 最小权限原则检查                                          ││
│  │   - 权限必要性评估                                            ││
│  │   - 权限滥用检测                                              ││
│  └─────────────────────────────────────────────────────────────┘│
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    运行时监控层                                ││
│  │   - 工具调用频率限制                                          ││
│  │   - 敏感操作审计                                              ││
│  │   - 异常行为检测                                              ││
│  └─────────────────────────────────────────────────────────────┘│
│                              ↓                                   │
│  ┌─────────────────────────────────────────────────────────────┐│
│  │                    安全响应层                                ││
│  │   - 权限动态调整                                              ││
│  │   - 危险操作阻断                                              ││
│  │   - 用户确认机制                                              ││
│  └─────────────────────────────────────────────────────────────┘│
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 6.3 工具安全检查清单

| 检查项 | 要求 | 实现 |
|--------|------|------|
| **权限隔离** | 读/写/执行权限分离 | RBAC模型 |
| **输入验证** | 所有工具参数验证 | JSON Schema |
| **输出过滤** | 工具输出扫描 | 内容安全检测 |
| **调用审计** | 记录所有调用 | 结构化日志 |
| **速率限制** | 防止滥用 | Token Bucket |
| **超时控制** | 避免无限等待 | 硬超时+软超时 |
| **熔断机制** | 故障隔离 | 滑动窗口计数 |

### 6.4 审计日志设计

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class ToolCallStatus(Enum):
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    TIMEOUT = "timeout"

@dataclass
class ToolAuditLog:
    """工具调用审计日志"""
    timestamp: datetime
    tool_name: str
    user_id: str
    session_id: str
    arguments: dict  # 脱敏后
    status: ToolCallStatus
    duration_ms: int
    error_code: str = None
    warning: list = None
    
    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "tool_name": self.tool_name,
            "user_id": self.user_id[:8] + "***",  # 脱敏
            "session_id": self.session_id,
            "arguments": self._sanitize_args(),
            "status": self.status.value,
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "warnings": self.warning
        }
    
    def _sanitize_args(self) -> dict:
        """脱敏敏感参数"""
        sensitive_keys = ["api_key", "password", "token", "secret"]
        sanitized = {}
        for k, v in self.arguments.items():
            if any(s in k.lower() for s in sensitive_keys):
                sanitized[k] = "***REDACTED***"
            else:
                sanitized[k] = v
        return sanitized
```

### 6.5 安全配置示例

```json
{
  "tool_security": {
    "global": {
      "max_calls_per_session": 100,
      "max_concurrent_calls": 5,
      "timeout_ms": 30000,
      "enable_audit": true
    },
    "tools": {
      "file_write": {
        "require_confirmation": true,
        "allowed_paths": ["/workspace/**"],
        "blocked_extensions": [".exe", ".sh"]
      },
      "network_request": {
        "require_confirmation": true,
        "allowed_domains": ["api.example.com"],
        "max_response_size_kb": 1024
      },
      "database_query": {
        "require_confirmation": true,
        "read_only": true,
        "blocked_operations": ["DROP", "DELETE"]
      }
    }
  }
}
```

---

## 七、工具Schema设计规范

### 7.1 Schema设计原则

| 原则 | 说明 | 示例 |
|------|------|------|
| **清晰性** | 名称和描述明确 | `get_user_by_id` 而非 `get` |
| **完整性** | 参数定义完备 | 必填/可选/默认值 |
| **一致性** | 风格统一 | camelCase命名 |
| **可发现** | 描述便于LLM理解 | 详细说明参数含义 |
| **类型安全** | 类型定义准确 | string/integer/enum |

### 7.2 Schema模板

```json
{
  "type": "function",
  "function": {
    "name": "action_verb_object",
    "description": "一句话说明工具做什么，为什么需要它，结果的格式",
    "parameters": {
      "type": "object",
      "properties": {
        "param_name": {
          "type": "string",
          "description": "参数含义、格式要求、示例值",
          "default": "默认值"
        }
      },
      "required": ["param_name"],
      "additionalProperties": false
    }
  }
}
```

### 7.3 优秀Schema示例

```json
{
  "type": "function",
  "function": {
    "name": "search_code_files",
    "description": "在指定目录中搜索包含关键词的代码文件。使用此工具可以快速定位代码位置，理解代码结构。返回匹配的文件列表和行号。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "搜索关键词，支持正则表达式。区分大小写。",
          "example": "class UserService"
        },
        "path": {
          "type": "string", 
          "description": "搜索的根目录路径，默认为当前工作目录。必须是绝对路径或相对于工作目录的路径。",
          "example": "/project/src"
        },
        "file_pattern": {
          "type": "string",
          "description": "文件匹配模式，支持glob语法。",
          "default": "*.py",
          "example": "*.{py,js,ts}"
        },
        "max_results": {
          "type": "integer",
          "description": "最大返回结果数，避免过多输出。",
          "default": 20,
          "minimum": 1,
          "maximum": 100
        }
      },
      "required": ["query"],
      "additionalProperties": false
    }
  }
}
```

### 7.4 Schema反模式

```json
{
  "type": "function",
  "function": {
    "name": "do",
    "description": "执行操作",
    "parameters": {
      "type": "object",
      "properties": {
        "x": {"type": "string", "description": "参数x"},
        "y": {"type": "string", "description": "参数y"}
      },
      "required": []
    }
  }
}
```

| 反模式 | 问题 | 改进 |
|--------|------|------|
| 模糊名称 | LLM难以选择 | 明确动词+名词 |
| 缺少描述 | 无法理解用途 | 详细说明+示例 |
| 无类型约束 | 传入错误类型 | 明确JSON Schema类型 |
| 全部可选 | 不知何时使用 | 标注必填参数 |

---

## 八、最佳实践与总结

### 8.1 工具设计最佳实践

```
┌─────────────────────────────────────────────────────────────────┐
│                    工具设计最佳实践                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. 【原子性】每个工具做一件事                                    │
│     ✓ search_web()                                              │
│     ✗ search_and_summarize()  // 拆分为两个工具                  │
│                                                                 │
│  2. 【幂等性】多次执行结果一致                                   │
│     ✓ get_user(id)  // 读操作，幂等                             │
│     ✓ delete_file(path)  // 幂等（文件不存在视为成功）           │
│     ✗ append_log(msg)  // 非幂等，每次追加不同ID                │
│                                                                 │
│  3. 【可逆性】高风险操作支持回滚                                 │
│     ✓ edit_file(path, content, backup=true)                    │
│     ✗ edit_file(path, content)  // 无备份                       │
│                                                                 │
│  4. 【可观测】操作结果可验证                                     │
│     ✓ write_file() → return {path, size, checksum}              │
│     ✗ write_file() → return "OK"                               │
│                                                                 │
│  5. 【容错性】优雅处理异常                                       │
│     ✓ try: result; except: return {error: "..."}               │
│     ✗ raise Exception  // 直接抛异常                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2 技能系统选型建议

| 场景 | 推荐方案 | 理由 |
|------|----------|------|
| **快速原型** | Function Calling | 实现简单 |
| **企业级应用** | MCP + 企业级方案 | 标准化+容错 |
| **多工具协作** | MCP | 生态丰富 |
| **低Token消耗** | ReWOO | 推理执行分离 |
| **复杂决策** | ReAct | 自动修正 |
| **本地部署** | OpenClaw | 本地优先 |
| **代码开发** | Claude Code | 深度IDE集成 |

### 8.3 技术演进趋势

```
2023: Function Calling 诞生
       - OpenAI首创
       - 行业跟进

2024: MCP协议 发布
       - 标准化趋势
       - 生态建设

2025: 智能化工具调用
       - 动态工具发现
       - 自动Schema生成
       - 安全框架完善

未来: 自主工具学习
       - Agent自动编写工具
       - 工具自动优化
       - 跨平台工具市场
```

### 8.4 参考资料

| 资料 | 来源 | 链接 |
|------|------|------|
| MCP协议官方文档 | Anthropic | https://modelcontextprotocol.io |
| a16z: MCP深度分析 | a16z | https://a16z.com/a-deep-dive-into-mcp |
| 企业级Agent工具调用方案 | ruyi72 | 参考本目录《企业级Agent工具调用综合方案》 |
| Claude Code最佳实践 | Anthropic | https://anthropic.com/engineering/claude-code-best-practices |
| ReAct论文 | arXiv | https://arxiv.org/abs/2210.03629 |
| ReWOO论文 | arXiv | https://arxiv.org/abs/2305.08746 |
| OpenClaw Skills系统 | GitHub | https://github.com/sigma-data/OpenClaw |
| AgenTRIM安全框架 | arXiv | https://arxiv.org/abs/2601.12449 |

---

*文档版本：1.0*
*更新时间：2026-04-12*
