# 建模功能冒烟检查清单

与 [MODELING_DELIVERY_PLAN.md](MODELING_DELIVERY_PLAN.md) 阶段 1.1、2.1 对应。  
**前置**：已创建/选中项目；已按 [README.md](../README.md)「LLM 与建模相关配置」填写可用大模型；网络可达（若用云端 API）。

---

## 第一节：ReAct / 同步或流式（默认）

### 1. 前置

- 应用已启动，建模页可打开。
- 设置或 `uap.local.yaml` 中 `llm` 已配置（`provider`、`base_url`、`model`；非 Ollama 时 `api_key`）。

### 2. 操作步骤

1. 在建模页选择目标项目。
2. 模式选择 **`react`**（或与默认一致）。
3. 发送一条短句，例如：「我想做一个简单的预测模型」。

### 3. 预期核对

| 检查项 | 如何确认 |
|--------|----------|
| 请求成功 | 若走同步 API：返回体 `ok === true`。若走流式：轮询至 `done === true` 后 `result.ok === true`。 |
| 助手消息 | 聊天区出现助手气泡；`message` 为可读中文（非裸错误栈）。 |
| `success` | 为布尔：表示本轮 ReAct/Plan **协议上**是否正常结束（如末步 `FINAL_ANSWER`），**不等于**业务上模型已完备。 |
| `modeling_substantive` | 与侧栏进程徽章一致：有变量/关系/约束快照时为 `true`（绿色「已完成」）；否则为 `false`（灰色「已结束」）。 |
| `pending_user_input` | 若末步为追问，应为 `true`，侧栏为「待您回复」；并有追问卡片时可交互。 |
| `steps` | 非空数组（正常推理时）；每步含 `action`、`thought` 等字段（见持久化消息中的摘要）。 |
| `model.json` | 在项目数据目录下存在（见 `ProjectStore`）；若本轮有结构化实质，打开 JSON 可见 `variables` / `relations` / `constraints` 之一非空。 |

### 4. 流式路径（可选）

1. 前端支持 `start_modeling_chat_stream` / `poll_modeling_chat_stream` 时，重复上述发送。
2. 轮询过程中应看到 token 累积或最终气泡。
3. **`done` 为真**时，`result` 字段与同步 `modeling_chat` 成功返回结构一致（含 `success`、`modeling_substantive`、`pending_ask_user_card` 等）。

---

## 第二节：Plan / Auto→Plan

### 1. 操作

1. 模式选择 **`plan`**，或 **`auto`**（若任务被分类为适合 Plan，实际 `mode_used` 可能为 `plan`）。
2. 发送与业务相关的目标句（需 **可用 LLM** 返回合法计划 JSON）。

### 2. 预期

| 检查项 | 说明 |
|--------|------|
| 响应 `ok` | 计划生成失败时可能 `ok: true` 但 `success: false`，助手消息应含可读失败原因（非仅内部码）。 |
| `plan` / `steps` | Plan 路径返回中应有计划相关字段（与同步 API 文档一致）；前端进程区能展示步骤或错误提示。 |
| `replan_count` | 若发生重规划，数值合理；界面或日志无死循环。 |

### 3. 已知限制

- 依赖 **LLM 严格遵循**计划 JSON 格式；模型不遵循时可能解析失败，需换模型或简化任务描述。
- 受 **`plan_max_time_seconds`** 墙钟限制，长计划可能超时中断。
- 自动化覆盖见 `tests/test_plan_agent.py`（提示词渲染与最小图）；完整链路以本清单 **人工** 为准。

---

## 自动化回归（与阶段 0.2 一致）

```bash
pytest tests/test_react_langgraph.py tests/test_dst_manager_stage.py tests/test_modeling_substantive.py tests/test_plan_agent.py tests/test_ask_user_card.py -q
```
