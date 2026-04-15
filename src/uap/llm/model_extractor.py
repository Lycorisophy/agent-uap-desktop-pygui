"""
系统模型提取器
使用LLM从对话或文档中提取复杂系统的数学模型
"""

import json
import re
import logging
from typing import Optional, Any
from dataclasses import dataclass

# 配置日志
_LOG = logging.getLogger("uap.model_extractor")
_LOG.setLevel(logging.DEBUG)

from uap.llm.ollama_client import OllamaClient, OllamaConfig
from uap.project.models import SystemModel, Variable, Relation, Constraint, ModelSource


# 系统模型提取的系统提示词
MODEL_EXTRACTION_SYSTEM_PROMPT = """你是一个复杂系统建模专家。你的任务是从用户的描述中提取系统的数学模型。

## 输出格式
请严格按照以下JSON格式输出，不要包含任何其他内容：

{
    "variables": [
        {
            "name": "变量名称",
            "type": "continuous|discrete|binary|categorical",
            "description": "变量描述",
            "unit": "单位（如果有）",
            "range": {"min": 数值, "max": 数值} // 可选
        }
    ],
    "relations": [
        {
            "from_var": "变量A",
            "to_var": "变量B",
            "type": "equation|differential|causal|correlation",
            "expression": "数学表达式（如果有）",
            "description": "关系描述"
        }
    ],
    "constraints": [
        {
            "type": "range|invariant|boundary",
            "expression": "约束表达式",
            "description": "约束描述"
        }
    ],
    "confidence": 0.0-1.0,
    "reasoning": "建模推理过程简述"
}

## 注意事项
1. variables至少包含一个变量
2. relations描述变量之间的关系，可以是因果、相关或数学方程
3. constraints是系统的约束条件，如取值范围、物理限制等
4. confidence表示模型提取的置信度（0-1）
5. 如果描述不足以建立有效模型，confidence应较低

## 变量类型说明
- continuous: 连续变量（如温度、浓度）
- discrete: 离散变量（如数量、计数）
- binary: 二值变量（如开关状态）
- categorical: 分类变量（如反应类型）

## 关系类型说明
- equation: 数学方程关系
- differential: 微分方程关系
- causal: 因果关系
- correlation: 相关关系
"""


@dataclass
class ExtractionResult:
    """模型提取结果"""
    success: bool
    model: Optional[SystemModel] = None
    error: Optional[str] = None
    reasoning: Optional[str] = None
    raw_response: Optional[str] = None


class ModelExtractor:
    """
    系统模型提取器
    
    使用LLM从用户对话或文档中自动提取复杂系统的数学模型，
    包括变量定义、变量关系、系统约束等。
    """
    
    def __init__(self, client: Optional[OllamaClient] = None):
        """
        初始化模型提取器
        
        Args:
            client: Ollama客户端实例，如果为None则创建默认客户端
        """
        self.client = client or OllamaClient()
    
    def extract_from_conversation(
        self,
        messages: list[dict],
        user_prompt: str,
        system_prompt: Optional[str] = None
    ) -> ExtractionResult:
        """
        从对话历史中提取系统模型
        
        Args:
            messages: 对话历史消息列表
            user_prompt: 用户当前描述
            system_prompt: 可选的自定义系统提示
            
        Returns:
            ExtractionResult: 提取结果
        """
        # 构建消息列表
        chat_messages = []
        
        # 添加系统提示
        chat_messages.append({
            "role": "system",
            "content": system_prompt or MODEL_EXTRACTION_SYSTEM_PROMPT
        })
        
        # 添加对话历史（最近10轮）
        for msg in messages[-10:]:
            chat_messages.append({
                "role": msg.get("role", "user"),
                "content": msg.get("content", "")
            })
        
        # 添加用户当前的系统描述
        chat_messages.append({
            "role": "user", 
            "content": f"请从以下描述中提取系统模型：\n\n{user_prompt}"
        })
        
        try:
            # 调用LLM
            _LOG.info("[Extractor] Calling LLM with %d messages", len(chat_messages))
            response = self.client.chat(chat_messages)
            _LOG.info("[Extractor] LLM response received, keys=%s", list(response.keys()) if isinstance(response, dict) else "not dict")
            
            # 解析响应 - Ollama原生格式: {"message": {"content": "..."}}
            content = None
            if isinstance(response, dict):
                if "message" in response:
                    content = response.get("message", {}).get("content", "")
                    _LOG.debug("[Extractor] Ollama format content extracted, len=%d", len(content) if content else 0)
            
            if not content:
                _LOG.warning("[Extractor] No content in response: %s", str(response)[:200])
                return ExtractionResult(
                    success=False,
                    error="无法从响应中提取内容",
                    raw_response=str(response)[:500]
                )
            
            result = self._parse_response(content)
            _LOG.info("[Extractor] Parsed result: success=%s, model=%s", result.success, result.model is not None)
            return result
            
        except Exception as e:
            _LOG.exception("[Extractor] LLM call failed: %s", str(e))
            return ExtractionResult(
                success=False,
                error=f"LLM调用失败: {str(e)}"
            )
    
    def extract_from_document(
        self,
        document_content: str,
        document_name: Optional[str] = None,
        system_prompt: Optional[str] = None
    ) -> ExtractionResult:
        """
        从文档内容中提取系统模型
        
        Args:
            document_content: 文档文本内容
            document_name: 文档名称（用于上下文）
            system_prompt: 可选的自定义系统提示
            
        Returns:
            ExtractionResult: 提取结果
        """
        # 构建提示
        context = ""
        if document_name:
            context = f"文档名称: {document_name}\n\n"
        context += f"文档内容:\n{document_content}"
        
        return self.extract_from_conversation(
            messages=[],
            user_prompt=context,
            system_prompt=system_prompt
        )
    
    def extract_from_text(
        self,
        text: str,
        system_prompt: Optional[str] = None
    ) -> ExtractionResult:
        """
        从纯文本中提取系统模型（简化接口）
        
        Args:
            text: 系统描述文本
            system_prompt: 可选的自定义系统提示
            
        Returns:
            ExtractionResult: 提取结果
        """
        return self.extract_from_conversation(
            messages=[],
            user_prompt=text,
            system_prompt=system_prompt
        )
    
    def _parse_response(self, content: str) -> ExtractionResult:
        """
        解析LLM响应，提取JSON模型数据
        
        Args:
            content: LLM响应文本
            
        Returns:
            ExtractionResult: 解析结果
        """
        _LOG.debug("[Extractor] Parsing response, content_len=%d", len(content))
        
        # 尝试提取JSON（支持markdown代码块）
        json_str = self._extract_json(content)
        
        if not json_str:
            _LOG.warning("[Extractor] Failed to extract JSON from response")
            return ExtractionResult(
                success=False,
                error="无法从响应中提取JSON格式数据",
                raw_response=content[:500]  # 保留前500字符用于调试
            )
        
        _LOG.debug("[Extractor] JSON extracted, json_len=%d", len(json_str))
        
        try:
            data = json.loads(json_str)
            _LOG.debug("[Extractor] JSON parsed, keys=%s", list(data.keys()))
            
            # 验证必需字段
            if "variables" not in data:
                return ExtractionResult(
                    success=False,
                    error="响应缺少variables字段",
                    raw_response=content[:500]
                )
            
            # 构建模型对象 - 处理字段名不匹配
            variables = []
            for v in data.get("variables", []):
                # 处理unit字段：LLM可能返回null或没有这个字段
                unit_val = v.get("unit")
                if unit_val is None:
                    unit_val = ""
                # 处理value_type字段映射
                var_type = v.get("type") or v.get("value_type", "float")
                if var_type == "continuous":
                    var_type = "float"
                elif var_type == "discrete":
                    var_type = "int"
                # 处理range字段映射到bounds
                range_data = v.get("range")
                bounds_min = bounds_max = None
                if isinstance(range_data, dict):
                    bounds_min = range_data.get("min")
                    bounds_max = range_data.get("max")
                
                variables.append(Variable(
                    name=v.get("name", "") or f"var_{len(variables)}",
                    value_type=var_type,
                    description=v.get("description", ""),
                    unit=str(unit_val) if unit_val else "",
                    bounds_min=bounds_min,
                    bounds_max=bounds_max
                ))
            
            relations = []
            for r in data.get("relations", []):
                # 处理relation_type字段
                rel_type = r.get("type") or r.get("relation_type", "causal")
                relations.append(Relation(
                    name=r.get("name", r.get("from_var", "") + "_to_" + r.get("to_var", "")),
                    description=r.get("description", ""),
                    relation_type=rel_type,
                    expression=r.get("expression"),
                    cause_vars=[r.get("from_var", "")] if r.get("from_var") else [],
                    effect_var=r.get("to_var", "") or r.get("effect_var", "")
                ))
            
            constraints = []
            for c in data.get("constraints", []):
                constraint_type = c.get("type") or c.get("constraint_type", "boundary")
                constraints.append(Constraint(
                    name=c.get("name", f"constraint_{len(constraints)}"),
                    description=c.get("description", ""),
                    constraint_type=constraint_type,
                    expression=c.get("expression", c.get("description", ""))
                ))
            
            model = SystemModel(
                variables=variables,
                relations=relations,
                constraints=constraints,
                source=ModelSource.LLM_EXTRACTED,
                confidence=data.get("confidence", 0.5)
            )
            
            return ExtractionResult(
                success=True,
                model=model,
                reasoning=data.get("reasoning"),
                raw_response=content[:500]
            )
            
        except json.JSONDecodeError as e:
            return ExtractionResult(
                success=False,
                error=f"JSON解析失败: {str(e)}",
                raw_response=content[:500]
            )
        except Exception as e:
            return ExtractionResult(
                success=False,
                error=f"模型构建失败: {str(e)}",
                raw_response=content[:500]
            )
    
    def _extract_json(self, text: str) -> Optional[str]:
        """
        从文本中提取JSON内容
        
        支持：
        1. Markdown代码块 ```json ... ```
        2. Markdown代码块 ``` ... ```
        3. 纯JSON文本
        
        Args:
            text: 输入文本
            
        Returns:
            str: 提取的JSON字符串，如果没有则返回None
        """
        # 尝试提取 ```json 代码块
        pattern = r'```json\s*([\s\S]*?)\s*```'
        match = re.search(pattern, text)
        if match:
            return match.group(1).strip()
        
        # 尝试提取 ``` 代码块
        pattern = r'```\s*([\s\S]*?)\s*```'
        match = re.search(pattern, text)
        if match:
            potential = match.group(1).strip()
            # 验证是否是有效JSON
            try:
                json.loads(potential)
                return potential
            except:
                pass
        
        # 尝试直接解析整段文本
        try:
            json.loads(text)
            return text
        except:
            pass
        
        # 尝试找到第一个{和最后一个}
        start = text.find('{')
        end = text.rfind('}')
        if start != -1 and end != -1 and end > start:
            potential = text[start:end+1]
            try:
                json.loads(potential)
                return potential
            except:
                pass
        
        return None
    
    def validate_model(self, model: SystemModel) -> tuple[bool, list[str]]:
        """
        验证模型的有效性
        
        Args:
            model: 待验证的系统模型
            
        Returns:
            tuple: (是否有效, 错误信息列表)
        """
        errors = []
        
        # 检查变量
        if not model.variables:
            errors.append("模型必须包含至少一个变量")
        
        var_names = {v.name for v in model.variables}
        
        # 检查关系引用的变量是否存在
        for rel in model.relations:
            if rel.from_var and rel.from_var not in var_names:
                errors.append(f"关系引用的变量 '{rel.from_var}' 不存在")
            if rel.to_var and rel.to_var not in var_names:
                errors.append(f"关系引用的变量 '{rel.to_var}' 不存在")
        
        # 检查约束表达式（简单验证）
        for con in model.constraints:
            if not con.expression and not con.description:
                errors.append("约束必须包含表达式或描述")
        
        return len(errors) == 0, errors


def create_default_extractor() -> ModelExtractor:
    """
    创建默认配置的模型提取器
    
    Returns:
        ModelExtractor: 默认提取器实例
    """
    from uap.config import load_config
    cfg = load_config()
    
    # 使用配置文件中的LLM设置
    ollama_config = OllamaConfig(
        base_url=cfg.llm.base_url,
        model=cfg.llm.model,
    )
    client = OllamaClient(ollama_config)
    return ModelExtractor(client)
