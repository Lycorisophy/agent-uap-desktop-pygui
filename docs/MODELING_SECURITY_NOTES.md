# 建模相关安全与数据自检

与 [MODELING_DELIVERY_PLAN.md](MODELING_DELIVERY_PLAN.md) 阶段 2.2 对应。发布或发版前按项勾选。

---

## 1. 流式 `stream_id` 生命周期

| 项 | 说明 |
|----|------|
| 会话释放 | `ModelingStreamHub.poll` 在 `done` 为真时从内存 `dict` 中 **`del self._sessions[stream_id]`**（见 `src/uap/infrastructure/modeling_stream_hub.py`），避免流 ID 无限堆积。 |
| 异常路径 | `hub.fail(stream_id, ...)` 同样将 `done` 置真，终态 poll 后释放。 |
| 未知 ID | `unknown_stream_id` 返回 `done: true`，前端应停止轮询。 |

---

## 2. 追问卡片（ASK_USER）

| 项 | 说明 |
|----|------|
| TTL | 超时秒数来自配置 **`agent.ask_user_card_timeout_seconds`**（与 `config/uap.example.yaml` 一致）。 |
| 超时行为 | 产品约定：超时视为拒绝，**仅写会话、不调 LLM**；冒烟时确认无重复触发建模。 |
| 项目边界 | 卡片与 `project_id` 绑定；拒绝/提交仅影响当前项目会话。 |

---

## 3. 日志与敏感信息（检查项，非代码强制）

| 项 | 建议 |
|----|------|
| API Key | 确认 `_LOG` / 前端控制台 **不打印完整** `api_key`；若发现泄漏，单独开 issue 脱敏。 |
| 用户消息 | 日志如需带用户句，宜 **截断长度**；全量仅用于本地调试开关。 |
| 项目路径 | `folder_path` / `workspace` 日志可接受；避免将内含令牌的环境变量一并 dump。 |

---

## 4. 项目工作区

| 项 | 说明 |
|----|------|
| 路径解析 | 技能 `file_access` / `win11_*` 应限制在项目根下；修改路径解析逻辑时需回归本清单第一节。 |
