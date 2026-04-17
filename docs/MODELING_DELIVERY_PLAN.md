# 建模能力交付计划（必做 / 选做）

本文档约定：**当前设计** = 桌面端对话式建模（ReAct 为主，含 Auto/Plan）、预置原子技能、`SystemModel` 与 `model.json` 落盘、基础 UI/API。  
目标：把**未完成的必做**按依赖排序执行；**选做**单独排期，不阻塞主线验收。

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
| **1.1** | 固定一条端到端冒烟脚本或检查清单 | 人工或半自动：选项目 → 发一条建模消息 → 确认 `ok`、助手消息、`steps`、`model.json`（若有实质则含变量/关系）、进程徽章与 `modeling_substantive` 一致。 | 文档化步骤（可附在本文件附录或 `docs/` 下短页） |
| **1.2** | 错误与降级路径对齐 | 统一：`ok: false`（请求/异常）、`ok: true` + `success: false`（如追问待续）、`ok: true` + `success: true` + `modeling_substantive` 三种组合下，前端 Toast/气泡/侧栏不出现互相矛盾文案；必要时在 `mixins_projects` 或前端注释中写明字段语义。 | 简短「字段语义」段落（可写在 API docstring 或本文附录） |
| **1.3** | 配置与帮助一致 | `uap.local.yaml` / 设置页：LLM、ReAct 步数、超时、MiniMax base_url/model 等与代码默认及错误提示一致；README 或设置内链指向「必填空」。 | 用户可自助排障 |

### 阶段 2 — 必做收尾（发布前）

| 顺序 | 事项 | 说明 | 产出 |
|------|------|------|------|
| **2.1** | Plan 模式与 Auto→Plan 冒烟 | 在 0.1 修复后，用真实或 mock LLM 跑一轮 Plan，确认计划 JSON 解析、失败提示、`replan_count` 等与 UI 一致。 | 记录已知限制（若有） |
| **2.2** | 安全与数据 | 确认项目工作区路径、卡片超时、流式 `stream_id` 生命周期无泄漏；敏感信息不进日志。 | 自检表打勾 |

---

## 二、选做项（不阻塞「对话式建模」主线；建议优先级）

### 优先级 A（产品增强，仍与建模强相关）

| 顺序 | 事项 | 说明 |
|------|------|------|
| **A.1** | 业务成功与协议成功再拆一层 | 若产品需要：例如增加 `business_success` 或「必须 `extract_model` 成功」才展示某类完成态。 |
| **A.2** | 领域数据模板 | 天气/销量等：文档化推荐目录结构、示例 CSV、与 `data_load_csv` 的衔接；可选小向导文案。 |
| **A.3** | OpenAI 兼容 `embedding` | 当 RAG/预测链路真依赖 `OpenAICompatibleChatClient.create_embedding` 时再实现；否则在配置中标注「未实现」。 |

### 优先级 B（架构扩展）

| 顺序 | 事项 | 说明 |
|------|------|------|
| **B.1** | 会话轨迹 → 技能固化 | 打通 `SkillGenerator` / `SkillManager` 与建模会话的入口与权限模型。 |
| **B.2** | DST 跨会话按 `project_id` 聚合 | 对应 `DstManager` 中预留的 `_project_states`。 |
| **B.3** | `graph_enabled` 实体关系图存储 | 与配置说明一致后再做。 |
| **B.4** | 技能复杂前置条件 | `skill/manager.py` 中 TODO 的前置条件检查。 |

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

*文档版本：与仓库「对话式建模」主线对齐；随迭代更新阶段完成情况。*
