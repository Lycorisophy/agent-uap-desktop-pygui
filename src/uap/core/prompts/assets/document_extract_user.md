从以下文档内容中提取复杂系统的建模信息。

## 文档内容
{document_excerpt}

## 已提取的信息
变量: {variable_names_repr}
方程: {equations_repr}

## 提取要求
1. 识别系统变量和参数
2. 识别变量之间的关系
3. 识别约束条件
4. 识别数学方程

请以 JSON 格式输出:
{{
  "variables": [{{"name": "变量名", "description": "描述", "unit": "单位"}}],
  "parameters": [{{"name": "参数名", "value": "值", "description": "描述"}}],
  "relations": [{{"from": "变量A", "to": "变量B", "type": "关系类型", "description": "描述"}}],
  "constraints": ["约束条件1", "约束条件2"],
  "equations": ["方程1", "方程2"]
}}
