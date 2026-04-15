"""
ModelExtractor —— **提示词工程**驱动的「结构化抽取」管线
================================================================

与 ReAct 路径的关系：
- ReAct 通过 **多轮工具**渐进写模型；本模块提供 **单次 JSON 契约**式抽取，
  适合对话摘要后批量落盘或文档导入后的冷启动。

**上下文工程**：调用方负责拼接 ``messages``（对话历史/文档片段）；本模块用
``uap.prompts`` 资产 ``model_extraction_system.md`` 固定 **system 侧 JSON schema 说明**，
降低格式漂移。

**记忆与知识**：抽取结果通常写入 ``SystemModel`` 并由 ``project_store`` 持久化；
  不向量化逻辑放在此文件之外。

修改该资产时，必须同步 ``_parse_response`` / ``_extract_json`` 与 ``uap.project.models`` 字段，
避免 **提示词与类型定义漂移**。
================================================================
"""

import json
import re
import logging
from typing import Optional, Any
from dataclasses import dataclass

# 配置日志
_LOG = logging.getLogger("uap.model_extractor")
_LOG.setLevel(logging.DEBUG)

from uap.project.models import SystemModel, Variable, Relation, Constraint, ModelSource
from uap.prompts import PromptId, load_raw, render


def get_model_extraction_system_prompt() -> str:
    """system 侧 JSON 契约（资产：``model_extraction_system.md``）。"""
    return load_raw(PromptId.MODEL_EXTRACTION_SYSTEM)


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
    
    def __init__(self, client: Optional[Any] = None):
        """
        初始化模型提取器

        Args:
            client: 聊天客户端（须实现 ``chat(messages) -> dict``）；None 时按全局配置创建。
        """
        if client is None:
            from uap.config import load_config
            from uap.infrastructure.llm.factory import create_llm_chat_client

            client = create_llm_chat_client(load_config().llm)
        self.client = client
    
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
            "content": system_prompt or get_model_extraction_system_prompt()
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
            "content": render(PromptId.MODEL_EXTRACTION_USER_PREFIX, user_prompt=user_prompt),
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
    from uap.infrastructure.llm.factory import create_llm_chat_client

    cfg = load_config()
    client = create_llm_chat_client(cfg.llm)
    return ModelExtractor(client)
