# 从如意72（ruyi72）到 UAP 独立项目：交接说明

**读者**：UAP 新仓库的架构师、后端/智能体开发、若与桌面壳对接的前端负责人。  
**性质**：经验与架构建议，**非**需求规格书；实现以 UAP 仓库与 UAP-2026-001 报告为准。

**仓库根（全文路径前缀）**  
`C:/project/golang/agent-ruyi72-desktop-pygui/`

**本仓库「框架 + 目录 + 架构」集中总览**（建议先读）：  
`C:/project/golang/agent-ruyi72-desktop-pygui/docs/uap/ruyi72-architecture-summary.md`

---

## 1. 两个项目如何对齐心智

| 维度 | 本仓库（ruyi72） | UAP（独立开发） |
|------|------------------|-----------------|
| 定位 | Windows 桌面 **PyWebView** 壳 + 本地/云端 LLM，偏 **个人/小团队** 会话与工具 | 报告中的 **L0–L5** 与六维协同，偏 **领域预测内核 + 认知编排** |
| 强边界 | 工作区 `safe_child`、会话落盘、ReAct 工具环 | 宜将 **动力学/熵/仿真** 与 **LLM 编排** **拆分**，便于测试、合规与扩缩容 |
| 文档编号 | 无 UAP 编号 | 与 `C:/project/golang/agent-ruyi72-desktop-pygui/docs/复杂系统未来势态量化预测统一智能体可行性研究与总体实施方案报告.md`（UAP-2026-001）对齐 |

**结论**：ruyi72 可作为 **「对话与工具编排壳」的参考实现**；UAP 的 **数据面、图数据库、专用预测服务** 宜在 **独立代码库/服务** 中演进，避免把桌面应用与重数据管线绑成单体。

---

## 2. 架构师建议优先拍板的五件事

1. **真源（source of truth）**  
   - 预测输入（时序、事件、拓扑）与 **版本、时间戳、采样率** 由谁权威保存；LLM 只消费 **已校验** 的结构化视图，避免「口头数字」当结论。

2. **内核与壳的接口**  
   - `predict_*` / `entropy_*` / `simulate_*` 的 **输入 schema、失败语义、超时、幂等** 先定死；编排层（LLM + 图）只通过 **稳定 API** 调用，便于替换 Koopman/PINN 实现。

3. **不确定性如何「诚实」对外**  
   - 报告强调置信区间、有效预测时长、VOID 态人工接管；产品上需 **固定展示结构**（JSON 或卡片），而不仅是自然语言段落。

4. **记忆与知识的边界**  
   - ruyi72 已有 **JSONL/SQLite/向量/FTS** 与记忆工具；UAP 若上 **Neo4j + Chroma** 等，需明确：**哪些进图、哪些进向量、哪些仅会话内**，避免三套检索语义重复。

5. **观测与审计**  
   - 工具调用链、模型版本、数据快照 ID 是否 **可回放**；领域场景往往有合规要求，早做日志与追踪比后补便宜。

---

## 3. 本仓库中值得「继承思想」的模式（不必照搬栈）

### 3.1 会话与持久化

- **会话目录**内 `meta.json` + `messages.json` 分离职责；扩展字段（如 `avatar_*`）显式版本化思路可参考 `SessionMeta` 设计（见 `C:/project/golang/agent-ruyi72-desktop-pygui/docs/module-design.md` §3）。
- **增强数据与主消息分离**：助手输出检查使用 `output_annotations.json`，避免把大段标注塞进每条 `content`，**利于迁移到 UAP 的「预测元数据」旁路存储**。

### 3.2 编排分支清晰

- `ConversationService` 按 **mode × session_variant** 分支（chat / react / persona / team / knowledge），**减少「一个 if 打天下」**；UAP 若引入 **AUTO_PILOT / ADVISORY / TAKE_CONTROL**，建议同样 **显式状态机或独立子模块**，与底层 ReAct 循环解耦。

### 3.3 配置

- **Pydantic + YAML**，本地覆盖文件合并；适合多环境，但 **敏感项**（API Key）勿写进仓库示例。

### 3.4 工具与工作区

- 工具默认 **受限路径**，危险能力（shell）与 **safe 子集**（定时任务安全 ReAct）分流；UAP 若接 **执行沙盒/E2B**，安全模型可类比「仅允许声明过的工具与资源」。

### 3.5 对话状态与恢复

- `dialogue_state.json` + 相位枚举，崩溃重启后 **陈旧相位降级**，**不假装流式重连仍在**；UAP 长任务/管道中断时，同样需要 **可解释的用户可见状态**。

### 3.6 文档习惯

- **模块总览**（`module-design`）+ **专篇**（记忆、定时任务、输出检查等）+ **根 README 功能列表** 分工明确；UAP 建议从第一天起固定 **「总览 + 领域专篇 + API 契约」**，避免知识只活在聊天里。

---

## 4. 建议在新项目里「刻意不同」的取舍

- **不要在应用包的 `__init__.py` 里聚合所有重型子模块**（例如一 import 就拉起 `ConversationService`），否则易出现 **循环导入**；本仓库曾通过 **延迟 import** 缓解（例：`react_lc` 内延迟加载 `output_review_sync`）。UAP  larger codebase 更宜用 **显式依赖注入** 或 **薄 `__init__`**。
- **LangChain / LangGraph** 与 **自研流式工具解析管线** 的边界，见 `C:/project/golang/agent-ruyi72-desktop-pygui/docs/企业级Agent工具调用综合方案.md` §八：当前 ruyi72 **未**实现该文 L0–R 全套；UAP 若做 **企业级编排**，需在仓库层面 **单独模块** 设计，勿与桌面 UI 揉在同一进程假设里。
- **UTF-16 偏移**：若 Web 前端与 Python 共用「文内 span」，偏移约定必须与浏览器 `String` 一致（本仓库 `utf16_text` + `output_review`）；UAP 若做 **可视化不确定性带**，尽早统一 **字符串模型**。
- **联网搜索**：Tavily/Brave 等需 **密钥与配额**；不宜默认绑定在无法配置密钥的公共演示里。

---

## 5. 工程经验与坑（简表）

| 现象 | 建议 |
|------|------|
| Python 包循环导入 | 延迟 import、拆包、`__init__` 保持轻量 |
| Windows 本机 LLM | 注意 `127.0.0.1` 与系统代理；本仓库对 localhost 默认弱化代理行为，远程网关需单独排障 |
| 长文档技能 / 工具返回 | ReAct 扁平化消息时注意 **体积**；检索类工具可约定 **JSON citations** 或 **正文 URL 兜底**（见 `C:/project/golang/agent-ruyi72-desktop-pygui/docs/助手输出检查设计.md`） |
| 单测 | 根 `C:/project/golang/agent-ruyi72-desktop-pygui/README.md` 提供 `python -m unittest discover -s tests -v`；UAP 建议 CI 尽早接上 |

---

## 6. 若仍与 ruyi72 集成（可选）

- **契约优先**：HTTP/OpenAPI 或 MCP，**版本化**。
- **会话语义不必强一致**：桌面会话 ID 与 UAP 侧 **run_id / case_id** 映射即可。
- **不把 UAP 重依赖反向写进本仓库主依赖**；用 **可选 extras** 或 **独立客户端库**。

---

## 7. 本仓库路径速查（完整路径，只读参考）

| 主题 | 完整路径 |
|------|----------|
| 架构与设计总览（前后端、目录、`src`、原则） | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/uap/ruyi72-architecture-summary.md` |
| 模块总览 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/module-design.md` |
| UAP 总体方案（同系列） | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/复杂系统未来势态量化预测统一智能体可行性研究与总体实施方案报告.md` |
| 企业级工具流 vs 现状 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/企业级Agent工具调用综合方案.md` |
| 助手输出检查与 UTF-16 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/助手输出检查设计.md` |
| 对话状态 | `C:/project/golang/agent-ruyi72-desktop-pygui/docs/对话状态追踪设计.md` |
| ReAct 入口（实现参考） | `C:/project/golang/agent-ruyi72-desktop-pygui/src/agent/react_lc.py` |
| 会话存储 | `C:/project/golang/agent-ruyi72-desktop-pygui/src/storage/session_store.py` |
| 编排核心 | `C:/project/golang/agent-ruyi72-desktop-pygui/src/service/conversation.py` |
| 应用入口与 Api | `C:/project/golang/agent-ruyi72-desktop-pygui/app.py` |
| 前端静态页 | `C:/project/golang/agent-ruyi72-desktop-pygui/web/index.html` |

---

## 8. 修订说明

UAP 仓库落地后，若 **接口、数据模型或合规要求** 变更，请 **在 UAP 仓库维护主文档**；本文仅反映 **自 ruyi72 迁出时的认知**，不保证与 UAP 后续版本逐条同步。
