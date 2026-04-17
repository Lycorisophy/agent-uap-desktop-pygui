# 建模能力交付计划（必做 / 选做）

本文档约定：**当前设计** = 桌面端对话式建模（ReAct 为主，含 Auto/Plan）、预置原子技能、`SystemModel` 与 `model.json` 落盘、基础 UI/API。  
目标：把**未完成的必做**按依赖排序执行；**选做**单独排期，不阻塞主线验收。

---

## 阶段完成情况（必做 0.x～2.x）

| 阶段 | 状态 | 说明 |
|------|------|------|
| **0.1** | 已完成 | Plan 单测已补 `intent_scene_block`；`PlanAgent` 运行时注入一致。 |
| **0.2** | 已完成 | 下列 pytest 组合已本地跑通（2026-04-17）。 |
| **1.1** | 已完成 | 见 [MODELING_SMOKE_CHECKLIST.md](MODELING_SMOKE_CHECKLIST.md) 第一节。 |
| **1.2** | 已完成 | 见下文「五、建模 API 响应字段语义」；代码注释见 `mixins_projects` / `app.js`。 |
| **1.3** | 已完成 | 见仓库根目录 [README.md](../README.md)「LLM 与建模相关配置」与 [config/uap.example.yaml](../config/uap.example.yaml)。 |
| **2.1** | 已完成 | 见 [MODELING_SMOKE_CHECKLIST.md](MODELING_SMOKE_CHECKLIST.md) 第二节。 |
| **2.2** | 已完成 | 见 [MODELING_SECURITY_NOTES.md](MODELING_SECURITY_NOTES.md)。 |

**推荐回归命令（CI / 本地）：**

```bash
pytest tests/test_react_langgraph.py tests/test_dst_manager_stage.py tests/test_modeling_substantive.py tests/test_plan_agent.py tests/test_ask_user_card.py tests/test_skill_preconditions.py tests/test_atomic_implemented_registry.py tests/test_entity_graph.py -q
```

---

## 一、必做项（建议执行顺序）

### 阶段 0 — 立刻（阻塞质量信号）

| 顺序 | 事项 | 说明 | 产出 |
|------|------|------|------|
| **0.1** | 修复 Plan 提示词与单测契约 | `plan_generation_user.md` 含 `{intent_scene_block}`；单测 `render(...)` 已补该参数。运行时由 `PlanAgent` 的 `_intent_scene_block` 注入，与模板一致。 | `pytest tests/test_plan_agent.py` 通过 |
| **0.2** | 全量或最小回归跑通 | 本地/CI：`pytest tests/test_react_langgraph.py tests/test_dst_manager_stage.py tests/test_modeling_substantive.py`；视情况加上 `test_plan_agent`、卡片相关测试。 | 无新增红测 |

### 阶段 1 — 紧接着（主线可验收）

| 顺序 | 事项 | 说明 | 产出 |
|------|------|------|------|
| **1.1** | 固定一条端到端冒烟脚本或检查清单 | 见 [MODELING_SMOKE_CHECKLIST.md](MODELING_SMOKE_CHECKLIST.md) 第一节；含流式核对。 | 同上 |
| **1.2** | 错误与降级路径对齐 | 见下文「五、建模 API 响应字段语义」；`mixins_projects` / `app.js` 已补轻量注释。 | 同上 |
| **1.3** | 配置与帮助一致 | README + `config/uap.example.yaml`（含 `modeling_agent_mode` 示例）。 | 用户可自助排障 |

### 阶段 2 — 必做收尾（发布前）

| 顺序 | 事项 | 说明 | 产出 |
|------|------|------|------|
| **2.1** | Plan 模式与 Auto→Plan 冒烟 | 见 [MODELING_SMOKE_CHECKLIST.md](MODELING_SMOKE_CHECKLIST.md) 第二节。 | 已知限制见该节 |
| **2.2** | 安全与数据 | 见 [MODELING_SECURITY_NOTES.md](MODELING_SECURITY_NOTES.md)。 | 自检表见该文档 |

---

## 二、选做项（不阻塞「对话式建模」主线；建议优先级）

### 优先级 A（产品增强，仍与建模强相关）

| 顺序 | 事项 | 说明 |
|------|------|------|
| **A.1** | 业务成功与协议成功再拆一层 | **已实现**：响应字段 `business_success` = `success` ∧ `modeling_substantive`；见第五节。 |
| **A.2** | 领域数据模板 | **已实现**：见 [MODELING_DOMAIN_DATA.md](MODELING_DOMAIN_DATA.md)（目录建议、示例 CSV、`data_load_csv`）。 |
| **A.3** | OpenAI 兼容 `embedding` | **已标注**：`OpenAICompatibleChatClient.create_embedding` 仍返回空向量；`config/uap.example.yaml` 的 `embedding` 节说明与独立嵌入服务的关系。 |

### 优先级 B（架构扩展）

| 顺序 | 事项 | 说明 |
|------|------|------|
| **B.1** | 会话轨迹 → 技能固化 | **已实现（可选）**：`agent.modeling_skill_solidification_enabled` 为 true 且 `business_success` 时，`SkillGenerator`→`SkillStore`；会话 `project_id` 必须与当前项目一致。 |
| **B.2** | DST 跨会话按 `project_id` 聚合 | **已实现**：`DstManager._merge_dst_into_project_aggregate`；`ProjectStore.dst_aggregate.json`；`_modeling_context_dict` 注入 `project_dst_aggregate_hint`。 |
| **B.3** | `graph_enabled` 实体关系图存储 | **已实现（轻量）**：`memory.graph_enabled` 为真时 `ProjectStore.entity_graph.json`；`uap.project.entity_graph.build_entity_graph_payload`；建模上下文 `entity_graph_hint`。 |
| **B.4** | 技能复杂前置条件 | **已实现**：`SkillManager._check_preconditions` 支持 `ctx:` / `context:` / 点路径；保留含「需要」的兼容分支。 |

---

## 三、执行顺序总览（先做什么 → 然后做什么）

```text
必做
  0.1 修复 Plan 渲染单测（intent_scene_block）
       ↓
  0.2 回归测试通过
       ↓
  1.1 端到端冒烟（ReAct + 落盘 + UI）
       ↓
  1.2 错误/字段语义与前端一致
       ↓
  1.3 配置与文档对齐
       ↓
  2.1 Plan / Auto→Plan 冒烟
       ↓
  2.2 安全与数据自检

选做（与必做并行排期即可，勿挡 0→1）
  A.1 → A.2 → A.3
  B.1 → B.2 → B.3 → B.4（可按资源调整顺序）
```

---

## 四、附录：Plan 单测修复提示（0.1）

`render` 调用至少包含模板所需键，例如：

```python
render(
    PromptId.PLAN_GENERATION_USER,
    task="预测销量",
    system_model="（无）",
    skills_desc="- a: test",
    intent_scene_block="（本轮未跑意图分类，略）\n",
)
```

实际工程里 `intent_scene_block` 应由与 ReAct 一致的意图/场景拼接函数生成，测试可用最小占位字符串。

---

## 五、建模 API 响应字段语义（`modeling_chat` / 流式 `result`）

同步 `modeling_chat` 成功体与流式结束时的 `result` 字段对齐（见 `ProjectsApiMixin._modeling_chat_core_body`）。

| 字段 | 类型（概念） | 含义 |
|------|----------------|------|
| `ok` | bool | **`true`**：`react_modeling` 正常返回且已持久化助手消息；**`false`**：项目不存在、异常或 `react_modeling` 返回 `ok: false`（此时 `message` 多为错误说明）。 |
| `message` | string | 面向用户的完整助手文本（含可选的步骤摘要、DST 行）；流式结束后与同步一致。 |
| `success` | bool | **协议成功**：ReAct/Plan 本轮是否以约定正常结束（如末步 `FINAL_ANSWER`）。**不表示**「业务上模型已完备」。 |
| `modeling_substantive` | bool | **是否有结构化快照**：本轮 `SystemModel` 是否含非空变量、关系或约束之一；前端进程徽章「已完成」依赖此字段（及从 `model` 推断的兜底）。 |
| `business_success` | bool | **业务上「协议成功且本轮有实质快照」**：等价于 `success && modeling_substantive`；集成方可单字段判断「本轮既有正常结束又有变量/关系/约束沉淀」。 |
| `solidified_skill` | object? | 仅当配置开启技能固化且生成成功时存在：`{ skill_id, path }`。 |
| `pending_user_input` | bool | **是否等待用户下一条消息**（例如末步 `ask_user`）；此时 `success` 多为 `false`。 |
| `pending_ask_user_card` | object? | 追问 IM 卡片载荷；无追问时为缺省/空。 |
| `steps` | array | ReAct 步或 Plan 映射步；供进程时间线展示。 |
| `plan` | array? | Plan 模式下的计划步骤；ReAct 时可能为空。 |
| `model` | object? | `SystemModel` 序列化；可与 `modeling_substantive` 交叉核对。 |
| `dst_state` | object | DST 快照（阶段、变量键名列表等）。 |
| `mode_used` / `mode_requested` | string | 实际使用模式与请求模式（`auto` 时可能不同）。 |

### 建模可用原子技能（已实现并注册）

ReAct/Plan 建模路径仅注册带执行器的子集（见 `uap.skill.atomic_implemented`），避免模型调用未实现工具。其余条目仍在 `get_atomic_skills_library()` 元数据库中，供文档与扩展。

| `skill_id` | 说明 |
|------------|------|
| `data_load_csv` | 读项目工作区内 CSV，返回列名与行预览（有 `project_workspace` 时校验路径）。 |
| `data_load_json` | 读本地 JSON 文件，返回结构摘要。 |
| `preprocess_missing` | 对二维数值矩阵按 `method` 做缺失填补（mean/forward/backward/linear/spline≈linear）。 |
| `preprocess_normalize` | `minmax` / `zscore` 列标准化。 |
| `preprocess_resample` | 按 `frequency`（如数字目标长度或 `n:120`）对序列线性重采样。 |
| `feature_derivative` | 列方向 `np.diff`。 |
| `model_monte_carlo` | 简化随机游走：`model.initial_state`、`model.n_steps`、`num_samples` 等。 |

另：建模注入工具（`extract_model`、`file_access`、`ask_user` 等）不在上表，与原子库并列注册。

---

## 六、相关文档

| 文档 | 用途 |
|------|------|
| [MODELING_SMOKE_CHECKLIST.md](MODELING_SMOKE_CHECKLIST.md) | ReAct / Plan 人工冒烟与自动化命令 |
| [MODELING_SECURITY_NOTES.md](MODELING_SECURITY_NOTES.md) | 流式、卡片、日志、工作区自检项 |
| [MODELING_DOMAIN_DATA.md](MODELING_DOMAIN_DATA.md) | 领域数据目录与 CSV 示例（与 `data_load_csv` 衔接） |

**实体图文件**：`projects_root/{project_id}/entity_graph.json`（与 `model.json` 同目录）。由 `SystemModel` 投影，不连接外部图数据库；关闭 `memory.graph_enabled` 时不写入。

---

*文档版本：与仓库「对话式建模」主线对齐；阶段完成情况见文首表格。*
