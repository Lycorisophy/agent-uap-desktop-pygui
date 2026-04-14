# 如意72（agent-ruyi72-desktop-pygui）架构与设计总览

> 供 UAP 或其它独立项目对照。**仓库根目录**下文记为：  
> **`C:/project/golang/agent-ruyi72-desktop-pygui/`**  
> （若你本地克隆路径不同，请整体替换该前缀。）

---

## 1. 项目定位

- **形态**：Windows 桌面应用，**PyWebView**（Edge WebView2）加载本地静态前端，Python 进程内嵌 **Api** 桥接前后端。
- **能力**：多会话、Chat / ReAct / 拟人 / 团队 / 知识库模式、工作区受限工具、技能 `load_skill`、跨会话记忆、内置定时任务、助手输出检查（Markdown 安全渲染 + 引用/存疑）、会话形象（像素/Live2D 可选）。
- **非目标**：不提供通用 HTTP 对外服务；不以本仓库单独承担「复杂系统动力学内核」——见 UAP 总报告与 `handoff-ruyi72-to-uap.md`。

---

## 2. 前后端框架与技术栈

| 层次 | 技术 | 说明 |
|------|------|------|
| 桌面壳 | PyWebView 5.x | 窗口、加载 `file://` 或等价本地页，暴露 `window.pywebview.api` |
| 前端 | 静态 **HTML/CSS/JS**（无打包框架） | 主入口 `C:/project/golang/agent-ruyi72-desktop-pygui/web/index.html`；逻辑集中在 `web/app.js`；样式 `web/style.css`；形象 `web/avatar.js` |
| 前端增强 | marked + DOMPurify（按需） | 助手气泡 Markdown 安全渲染（与 `output_review` 配置联动） |
| 后端语言 | Python 3.11/3.12 推荐 | 入口 `C:/project/golang/agent-ruyi72-desktop-pygui/app.py` |
| 配置 | PyYAML + Pydantic v2 | `C:/project/golang/agent-ruyi72-desktop-pygui/src/config.py`，示例 `C:/project/golang/agent-ruyi72-desktop-pygui/config/ruyi72.example.yaml` |
| LLM | Ollama 兼容 / OpenAI 兼容 Chat | `C:/project/golang/agent-ruyi72-desktop-pygui/src/llm/ollama.py`、`ollama_stream.py`、`chat_model.py` |
| ReAct | LangChain `create_agent` + LangGraph | `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/react_lc.py`（经 `react.py` 导出） |
| 持久化 | 会话目录 JSON + 可选 SQLite 记忆 | `C:/project/golang/agent-ruyi72-desktop-pygui/src/storage/session_store.py`、`memory_store.py`、`memory_sqlite.py` |

**前后端通信**：仅通过 **`Api` 类**（定义于 `C:/project/golang/agent-ruyi72-desktop-pygui/app.py`）的方法；前端 `await pywebview.api.xxx(...)`。拟人模式事件经 `evaluate_js` 注入 `window.__ruyiPersonaEvent`。

---

## 3. 顶层目录结构（仓库根）

```text
C:/project/golang/agent-ruyi72-desktop-pygui/
  app.py                 # 入口：窗口、Api、ConversationService、调度与记忆线程启动
  requirements.txt
  README.md
  config/
    ruyi72.example.yaml  # 配置示例
  docs/                  # 设计与索引（含 uap/ 交接、UAP 总报告等）
  web/                   # 前端静态资源
    index.html
    app.js
    style.css
    avatar.js
    live2d/              # Cubism 相关（见 session-avatar 专篇）
  skills/                # 可被 ReAct load_skill 加载的 SKILL.md（safe/act/warn_act）
  tests/                 # unittest
  src/
    config.py
    debug_log.py
    agent/                 # ReAct、拟人、团队、工具、压缩、记忆抽取与工具
    llm/                   # Ollama、流式、Chat 模型、提示词、身份 Markdown
    service/               # ConversationService、output_review、utf16
    storage/               # SessionStore、MemoryStore、SQLite 迁移等
    scheduler/             # 内置定时任务 worker、CRUD、执行器
    skills/                # 技能注册与加载（与仓库 skills/ 目录配合）
```

---

## 4. `src/` 分包职责摘要

| 路径 | 职责 |
|------|------|
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/config.py` | `RuyiConfig`：llm、storage、persona、memory、team、context_compression、output_review、builtin_scheduler 等 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/service/conversation.py` | 会话编排核心：发消息、模式分支、ReAct 线程、团队、拟人、卡片、对话相位 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/service/dialogue_phase.py` | 对话相位类型与快照 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/service/output_review.py` | 助手输出检查：标注持久化、异步存疑队列、Api 用合并逻辑 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/service/output_review_sync.py` | URL/章节解析、工具 citations 合并、白名单工具 URL 兜底 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/service/utf16_text.py` | UTF-16 与 Python 字符索引换算（与前端一致） |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/storage/session_store.py` | 会话 meta/messages、dialogue_state、checkpoint、scheduled_tasks 等落盘 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/storage/memory_store.py` | 全局记忆 JSONL 等 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/storage/memory_sqlite.py` | SQLite/FTS、消息索引等 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/react_lc.py` | ReAct：工具装配、`run_react`、tool_citations 收集 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/react.py` | 薄封装导出 `run_react` |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/tools.py` | 工作区 read/list/write/shell，`safe_child` |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/memory_tools.py` | browse/search 记忆、search_history 等 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/persona_runtime.py` | 拟人流式与事件 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/team_turn.py` | 团队多槽链式调用 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/context_compression.py` | 上文检查点与 `messages_for_llm` 裁剪 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/chat_stream_runtime.py` | 安全模式 Chat 流式 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/action_card.py` | 交互确认卡片解析 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/llm/prompts.py` | 系统块、ReAct system 片段等 |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/llm/knowledge_prompts.py` | 知识库会话附加 system |
| `C:/project/golang/agent-ruyi72-desktop-pygui/src/scheduler/` | 定时任务模型、持久化、worker、executor、crud |

**注意**：`C:/project/golang/agent-ruyi72-desktop-pygui/src/service/__init__.py` 当前导出 `ConversationService`，会间接 import 全链；子模块中必要时用 **延迟 import** 避免与 `react_lc` 等形成环。

---

## 5. 架构关系（逻辑）

- **app.py**：构造 `SessionStore`、`ConversationService`、`Api`，`webview.start()`。
- **Api → ConversationService →（SessionStore | LLM | run_react | PersonaRuntime | run_team_turn）**。
- **ReAct**：`create_agent` + 工具；工具内可 `load_skill`、记忆检索；结束后消息扁平化写入会话。
- **记忆**：全局 `MemoryStore` + 可选 SQLite；ReAct 工具只读；闲时抽取见 `memory_auto_extract`。
- **内置调度**：独立线程扫描任务，可触发带 `scheduler_context` 的 ReAct 安全子集。

更细的模块图与边界见：  
`C:/project/golang/agent-ruyi72-desktop-pygui/docs/module-design.md`（首节 mermaid 总览）。

---

## 6. 设计原则（可迁移到 UAP 的「经验」）

1. **单一入口**：UI 只认 `Api`，便于审计与 mock。
2. **会话真源**：`messages.json` 与 `meta.json`；增强型旁路（如 `output_annotations.json`）与主对话分离。
3. **发给 LLM 的视图**：`messages_for_llm` 仅 role+content，可叠加 checkpoint 摘要；**不把** `tool_citations` 等注入模型上下文。
4. **工具安全**：工作区根固定，路径 `safe_child` 校验；高危工具与「安全 ReAct」子集分离。
5. **状态可恢复**：`dialogue_state.json` + 重启降级，避免假「仍在生成」。
6. **配置与密钥**：YAML 分层；密钥不进仓库示例；localhost 代理策略在 `ollama` 侧有考虑。
7. **文档分层**：`module-design` 总览 + 各专篇 + 根 README 功能列表；复杂能力单独成文。

---

## 7. 设计文档完整路径索引（本仓库）

以下均为 **绝对路径**（以本机仓库为例，前缀可替换）。

| 说明 | 完整路径 |
|------|----------|
| 模块设计总览 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/module-design.md` |
| 文档总索引 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/README.md` |
| UAP 可行性总报告 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/复杂系统未来势态量化预测统一智能体可行性研究与总体实施方案报告.md` |
| UAP 交接（经验与优先事项） | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/uap/handoff-ruyi72-to-uap.md` |
| UAP 目录说明 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/uap/README.md` |
| 本文（架构总览） | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/uap/ruyi72-architecture-summary.md` |
| 对话状态追踪 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/对话状态追踪设计.md` |
| 助手输出检查 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/助手输出检查设计.md` |
| 会话形象 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/session-avatar-design.md` |
| 团队模式 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/agent-team-mode.md` |
| 定时任务 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/scheduled-tasks-design.md` |
| 企业级工具流（与现状对照） | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/企业级Agent工具调用综合方案.md` |
| 记忆 v1 / v2 / v3 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/AI智能体ruyi72 记忆系统（永驻+事件）设计（v1.0）.md` 等 |
| Agent 开发 SOP | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/agent-assisted-development-sop.md` |
| 根 README | `C:/project/golang/agent-ruyi72-desktop-pygui/README.md` |
| 配置示例 | `C:/project/golang/agent-ruyi72-desktop-pygui/config/ruyi72.example.yaml` |

---

## 8. 修订说明

随本仓库演进，**实现以源码为准**；架构师若发现与代码不一致，以 `C:/project/golang/agent-ruyi72-desktop-pygui/docs/module-design.md` 与源码为优先。
