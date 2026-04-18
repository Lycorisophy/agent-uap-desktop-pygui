## 项目信息
- 项目ID: {project_id}
- 项目名称: {project_name}
- 系统类型: {system_type}
- 领域: {domain}

## 执行轨迹
{action_trajectory}

## 用户原始问题
{user_query}

## 最终输出
{final_output}

请根据以上信息，生成一个专业的技能文档。输出 JSON 格式:

```json
{{
  "name": "技能名称",
  "description": "一句话描述",
  "category": "modeling/prediction/analysis/visualization",
  "trigger_conditions": ["触发条件1", "触发条件2"],
  "preconditions": ["前置条件1"],
  "steps": [
    {{
      "step_number": 1,
      "title": "步骤标题",
      "description": "步骤详细描述",
      "action_type": "tool_call/thought",
      "tool_name": "工具名或null",
      "prompt_template": "Prompt模板或null",
      "expected_output": "预期输出描述"
    }}
  ],
  "parameters": [
    {{
      "name": "参数名",
      "description": "参数描述",
      "type": "string/number/boolean",
      "required": true/false,
      "default": "默认值或null"
    }}
  ]
}}
```
