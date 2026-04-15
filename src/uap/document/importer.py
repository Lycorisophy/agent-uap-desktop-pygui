"""
UAP 文档导入解析系统 - 文档导入服务

提供文档导入、解析和系统模型提取的完整流程。
"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Callable

from uap.document.models import (
    Document,
    DocumentType,
    ParsedContent,
    SystemEntity,
    ImportResult,
)
from uap.document.parser import (
    DocumentParser,
    MarkdownParser,
    PdfParser,
    WordParser,
    create_parser,
    create_parser_for_file,
)
from uap.prompts import PromptId, load_raw, render


class DocumentImporter:
    """
    文档导入服务
    
    提供文档导入、解析、验证的完整流程。
    支持多种文档格式的自动检测和解析。
    """
    
    # 支持的文件类型
    SUPPORTED_EXTENSIONS = {
        ".md", ".markdown",    # Markdown
        ".pdf",               # PDF
        ".docx", ".doc",     # Word
        ".txt",               # 纯文本
    }
    
    def __init__(self, llm_client = None):
        """
        初始化文档导入服务
        
        Args:
            llm_client: LLM 客户端（用于增强解析）
        """
        self.llm = llm_client
    
    def import_file(
        self,
        file_path: str,
        auto_parse: bool = True
    ) -> ImportResult:
        """
        导入文件
        
        Args:
            file_path: 文件路径
            auto_parse: 是否自动解析
            
        Returns:
            导入结果
        """
        start_time = time.time()
        
        try:
            # 验证文件
            path = Path(file_path)
            if not path.exists():
                return ImportResult(
                    success=False,
                    error=f"文件不存在: {file_path}"
                )
            
            # 检查扩展名
            if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
                return ImportResult(
                    success=False,
                    error=f"不支持的文件类型: {path.suffix}"
                )
            
            # 创建文档对象
            document = Document.from_file(file_path)
            
            # 自动解析
            parsed_content = None
            if auto_parse:
                parsed_content = self.parse_document(document)
            
            # 构建结果
            result = ImportResult(
                success=True,
                document=document,
                parsed_content=parsed_content,
                import_duration_ms=int((time.time() - start_time) * 1000),
                content_length=len(document.content),
                entities_extracted=len(parsed_content.entities) if parsed_content else 0
            )
            
            return result
            
        except ImportError as e:
            return ImportResult(
                success=False,
                error=f"缺少依赖: {str(e)}",
                error_details={"type": "ImportError"},
                import_duration_ms=int((time.time() - start_time) * 1000)
            )
        except Exception as e:
            return ImportResult(
                success=False,
                error=f"导入失败: {str(e)}",
                error_details={"type": type(e).__name__},
                import_duration_ms=int((time.time() - start_time) * 1000)
            )
    
    def import_content(
        self,
        content: str,
        name: str,
        doc_type: DocumentType = DocumentType.MARKDOWN,
        auto_parse: bool = True
    ) -> ImportResult:
        """
        从内容导入文档
        
        Args:
            content: 文档内容
            name: 文档名称
            doc_type: 文档类型
            auto_parse: 是否自动解析
            
        Returns:
            导入结果
        """
        start_time = time.time()
        
        try:
            # 创建文档对象
            document = Document(
                name=name,
                content=content,
                doc_type=doc_type
            )
            
            # 自动解析
            parsed_content = None
            if auto_parse:
                parsed_content = self.parse_document(document)
            
            # 构建结果
            result = ImportResult(
                success=True,
                document=document,
                parsed_content=parsed_content,
                import_duration_ms=int((time.time() - start_time) * 1000),
                content_length=len(content),
                entities_extracted=len(parsed_content.entities) if parsed_content else 0
            )
            
            return result
            
        except Exception as e:
            return ImportResult(
                success=False,
                error=f"导入失败: {str(e)}",
                import_duration_ms=int((time.time() - start_time) * 1000)
            )
    
    def parse_document(self, document: Document) -> ParsedContent:
        """
        解析文档
        
        Args:
            document: 文档对象
            
        Returns:
            解析后的内容
            
        Raises:
            ImportError: 缺少解析依赖
            ValueError: 文档类型不支持
        """
        # 选择解析器
        parser = self._get_parser(document)
        
        # 解析
        parsed = parser.parse(document)
        
        # 如果有 LLM，进行增强提取
        if self.llm and parsed:
            parsed = self._enhance_with_llm(document, parsed)
        
        return parsed
    
    def _get_parser(self, document: Document) -> DocumentParser:
        """获取合适的解析器"""
        if document.doc_type == DocumentType.MARKDOWN:
            return MarkdownParser()
        elif document.doc_type == DocumentType.PDF:
            return PdfParser()
        elif document.doc_type == DocumentType.WORD:
            return WordParser()
        else:
            return MarkdownParser()
    
    def _enhance_with_llm(
        self,
        document: Document,
        parsed: ParsedContent
    ) -> ParsedContent:
        """使用 LLM 增强解析"""
        if not self.llm:
            return parsed
        
        try:
            variable_names_repr = str(
                [e.name for e in parsed.entities if e.entity_type.value == "variable"]
            )
            equations_repr = str(parsed.equations[:3])
            prompt = render(
                PromptId.DOCUMENT_EXTRACT_USER,
                document_excerpt=parsed.full_text[:5000],
                variable_names_repr=variable_names_repr,
                equations_repr=equations_repr,
            )

            response = self.llm.chat(
                [
                    {"role": "system", "content": load_raw(PromptId.DOCUMENT_EXTRACT_SYSTEM)},
                    {"role": "user", "content": prompt},
                ]
            )
            
            # 解析 LLM 响应
            import re
            import json
            
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                
                # 添加 LLM 提取的变量
                for var in data.get("variables", []):
                    entity = SystemEntity(
                        entity_type=SystemEntity.entity_type.__class__.VARIABLE,
                        name=var["name"],
                        description=var.get("description", ""),
                        metadata={"unit": var.get("unit")},
                        confidence=0.9
                    )
                    # 避免重复
                    if not any(e.name == entity.name for e in parsed.entities):
                        parsed.entities.append(entity)
                
                # 添加 LLM 提取的参数
                for param in data.get("parameters", []):
                    entity = SystemEntity(
                        entity_type=SystemEntity.entity_type.__class__.PARAMETER,
                        name=param["name"],
                        value=param.get("value"),
                        description=param.get("description", ""),
                        confidence=0.9
                    )
                    if not any(e.name == entity.name for e in parsed.entities):
                        parsed.entities.append(entity)
                
                # 添加 LLM 提取的关系
                for rel in data.get("relations", []):
                    entity = SystemEntity(
                        entity_type=SystemEntity.entity_type.__class__.RELATION,
                        name=f"{rel['from']} -> {rel['to']}",
                        value=rel.get("type"),
                        description=rel.get("description", ""),
                        confidence=0.9
                    )
                    parsed.entities.append(entity)
                
                # 添加 LLM 提取的约束
                for constraint in data.get("constraints", []):
                    entity = SystemEntity(
                        entity_type=SystemEntity.entity_type.__class__.CONSTRAINT,
                        name=constraint[:50],
                        description=constraint,
                        confidence=0.9
                    )
                    parsed.entities.append(entity)
                
                # 添加 LLM 提取的方程
                for eq in data.get("equations", []):
                    if eq not in parsed.equations:
                        parsed.equations.append(eq)
                
                # 更新置信度
                parsed.extraction_confidence = min(parsed.extraction_confidence + 0.2, 1.0)
        
        except Exception as e:
            print(f"LLM enhancement failed: {e}")
        
        return parsed
    
    def batch_import(
        self,
        file_paths: List[str],
        progress_callback: Callable[[int, int, str], None] = None
    ) -> List[ImportResult]:
        """
        批量导入文档
        
        Args:
            file_paths: 文件路径列表
            progress_callback: 进度回调 (current, total, filename)
            
        Returns:
            导入结果列表
        """
        results = []
        
        for i, file_path in enumerate(file_paths):
            if progress_callback:
                progress_callback(i + 1, len(file_paths), Path(file_path).name)
            
            result = self.import_file(file_path)
            results.append(result)
        
        return results
    
    def validate_file(self, file_path: str) -> tuple[bool, str]:
        """
        验证文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            (is_valid, error_message)
        """
        path = Path(file_path)
        
        if not path.exists():
            return False, "文件不存在"
        
        if path.suffix.lower() not in self.SUPPORTED_EXTENSIONS:
            return False, f"不支持的文件类型: {path.suffix}"
        
        if path.stat().st_size == 0:
            return False, "文件为空"
        
        # 检查文件大小 (最大 50MB)
        if path.stat().st_size > 50 * 1024 * 1024:
            return False, "文件过大 (最大 50MB)"
        
        return True, ""
    
    def get_supported_formats(self) -> dict:
        """获取支持的格式信息"""
        return {
            "extensions": list(self.SUPPORTED_EXTENSIONS),
            "types": [
                {
                    "type": "markdown",
                    "extensions": [".md", ".markdown"],
                    "description": "Markdown 文档"
                },
                {
                    "type": "pdf",
                    "extensions": [".pdf"],
                    "description": "PDF 文档"
                },
                {
                    "type": "word",
                    "extensions": [".docx", ".doc"],
                    "description": "Word 文档"
                },
                {
                    "type": "text",
                    "extensions": [".txt"],
                    "description": "纯文本"
                }
            ]
        }


def create_importer(llm_client = None) -> DocumentImporter:
    """
    创建文档导入器
    
    Args:
        llm_client: LLM 客户端
        
    Returns:
        DocumentImporter 实例
    """
    return DocumentImporter(llm_client)
