## 技能内容
{skill_content}

## 评估标准
1. 完整性: 是否包含所有必要字段
2. 可执行性: 步骤是否清晰可执行
3. 适用性: 是否适合复杂系统建模/预测场景
4. 改进建议: 如何优化

请输出 JSON 格式:
```json
{{
  "is_valid": true/false,
  "completeness_score": 0.0-1.0,
  "executability_score": 0.0-1.0,
  "relevance_score": 0.0-1.0,
  "issues": ["问题1", "问题2"],
  "suggestions": ["建议1"]
}}
```
