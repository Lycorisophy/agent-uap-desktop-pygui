"""
UAP 文档导入解析系统 - 数据模型

定义文档、解析内容、系统实体等核心数据结构。
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional, List
from dataclasses import dataclass, field


class DocumentType(str, Enum):
    """文档类型枚举"""
    MARKDOWN = "markdown"
    PDF = "pdf"
    WORD = "word"
    TEXT = "text"
    UNKNOWN = "unknown"


class EntityType(str, Enum):
    """系统实体类型枚举"""
    VARIABLE = "variable"           # 变量
    PARAMETER = "parameter"         # 参数
    CONSTANT = "constant"           # 常量
    RELATION = "relation"           # 关系
    EQUATION = "equation"           # 方程
    CONSTRAINT = "constraint"       # 约束条件
    ASSUMPTION = "assumption"       # 假设


@dataclass
class SystemEntity:
    """
    系统实体
    
    从文档中提取的系统组成元素。
    """
    entity_type: EntityType         # 实体类型
    name: str                       # 实体名称
    value: Optional[str] = None     # 值或表达式
    description: str = ""          # 描述
    source: str = ""               # 来源位置
    confidence: float = 0.5        # 置信度 0-1
    metadata: dict = field(default_factory=dict)  # 额外元数据
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "type": self.entity_type.value if hasattr(self.entity_type, 'value') else self.entity_type,
            "name": self.name,
            "value": self.value,
            "description": self.description,
            "source": self.source,
            "confidence": self.confidence,
            "metadata": self.metadata
        }


@dataclass
class Document:
    """
    文档数据类
    
    表示要导入的文档。
    """
    name: str                       # 文档名称
    content: str                    # 文档内容
    doc_type: DocumentType          # 文档类型
    file_path: str = ""             # 文件路径
    size: int = 0                   # 文件大小（字节）
    created_at: datetime = field(default_factory=datetime.now)
    metadata: dict = field(default_factory=dict)  # 文档元数据
    
    @property
    def is_markdown(self) -> bool:
        """是否为 Markdown 文档"""
        return self.doc_type == DocumentType.MARKDOWN
    
    @property
    def is_pdf(self) -> bool:
        """是否为 PDF 文档"""
        return self.doc_type == DocumentType.PDF
    
    @property
    def is_word(self) -> bool:
        """是否为 Word 文档"""
        return self.doc_type == DocumentType.WORD
    
    @classmethod
    def from_file(cls, file_path: str, content: str = None) -> "Document":
        """
        从文件创建文档
        
        Args:
            file_path: 文件路径
            content: 文件内容（可选，如果不提供则自动读取）
        """
        from pathlib import Path
        
        path = Path(file_path)
        name = path.stem
        
        # 根据扩展名判断类型
        ext = path.suffix.lower()
        if ext in [".md", ".markdown"]:
            doc_type = DocumentType.MARKDOWN
        elif ext == ".pdf":
            doc_type = DocumentType.PDF
        elif ext in [".docx", ".doc"]:
            doc_type = DocumentType.WORD
        elif ext in [".txt"]:
            doc_type = DocumentType.TEXT
        else:
            doc_type = DocumentType.UNKNOWN
        
        # 读取内容
        if content is None:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception:
                content = ""
        
        return cls(
            name=name,
            content=content,
            doc_type=doc_type,
            file_path=str(path),
            size=path.stat().st_size if path.exists() else 0
        )
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.name,
            "doc_type": self.doc_type.value if hasattr(self.doc_type, 'value') else self.doc_type,
            "file_path": self.file_path,
            "size": self.size,
            "created_at": self.created_at.isoformat(),
            "metadata": self.metadata
        }


@dataclass
class ParsedContent:
    """
    解析后的内容
    
    包含从文档中提取的文本内容、系统实体和结构化信息。
    """
    document: Document             # 原始文档
    full_text: str = ""            # 完整文本
    sections: List[dict] = field(default_factory=list)  # 文档章节
    entities: List[SystemEntity] = field(default_factory=list)  # 系统实体
    equations: List[str] = field(default_factory=list)  # 方程列表
    tables: List[dict] = field(default_factory=list)   # 表格数据
    figures: List[dict] = field(default_factory=list) # 图片/图表
    
    # 提取质量指标
    extraction_confidence: float = 0.0  # 整体提取置信度
    coverage: float = 0.0               # 内容覆盖率
    
    # 元数据
    parsed_at: datetime = field(default_factory=datetime.now)
    parser_version: str = "1.0"
    
    @property
    def has_entities(self) -> bool:
        """是否有提取的实体"""
        return len(self.entities) > 0
    
    @property
    def has_equations(self) -> bool:
        """是否有提取的方程"""
        return len(self.equations) > 0
    
    def get_entities_by_type(self, entity_type: EntityType) -> List[SystemEntity]:
        """按类型获取实体"""
        return [e for e in self.entities if e.entity_type == entity_type]
    
    def get_variables(self) -> List[SystemEntity]:
        """获取变量实体"""
        return self.get_entities_by_type(EntityType.VARIABLE)
    
    def get_parameters(self) -> List[SystemEntity]:
        """获取参数实体"""
        return self.get_entities_by_type(EntityType.PARAMETER)
    
    def get_relations(self) -> List[SystemEntity]:
        """获取关系实体"""
        return self.get_entities_by_type(EntityType.RELATION)
    
    def get_constraints(self) -> List[SystemEntity]:
        """获取约束实体"""
        return self.get_entities_by_type(EntityType.CONSTRAINT)
    
    def to_summary(self) -> str:
        """生成内容摘要"""
        summary_parts = []
        
        if self.sections:
            summary_parts.append(f"文档包含 {len(self.sections)} 个章节")
        
        if self.entities:
            by_type = {}
            for entity in self.entities:
                t = entity.entity_type.value if hasattr(entity.entity_type, 'value') else entity.entity_type
                by_type[t] = by_type.get(t, 0) + 1
            
            type_parts = [f"{t}: {n}个" for t, n in by_type.items()]
            summary_parts.append("提取实体: " + ", ".join(type_parts))
        
        if self.equations:
            summary_parts.append(f"提取方程: {len(self.equations)}个")
        
        if self.tables:
            summary_parts.append(f"提取表格: {len(self.tables)}个")
        
        return "\n".join(summary_parts) if summary_parts else "未提取到有效内容"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "document": self.document.to_dict(),
            "full_text": self.full_text,
            "sections": self.sections,
            "entities": [e.to_dict() for e in self.entities],
            "equations": self.equations,
            "tables": self.tables,
            "figures": self.figures,
            "extraction_confidence": self.extraction_confidence,
            "coverage": self.coverage,
            "parsed_at": self.parsed_at.isoformat(),
            "parser_version": self.parser_version
        }


@dataclass
class ImportResult:
    """
    文档导入结果
    
    表示文档导入操作的结果。
    """
    success: bool                  # 是否成功
    document: Optional[Document] = None  # 文档对象
    parsed_content: Optional[ParsedContent] = None  # 解析内容
    
    # 错误信息
    error: str = ""
    error_details: dict = field(default_factory=dict)
    
    # 导入统计
    import_duration_ms: int = 0    # 导入耗时
    content_length: int = 0        # 内容长度
    entities_extracted: int = 0    # 提取的实体数
    
    @property
    def message(self) -> str:
        """获取结果消息"""
        if self.success:
            return f"成功导入文档，提取了 {self.entities_extracted} 个实体"
        return f"导入失败: {self.error}"
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "success": self.success,
            "document": self.document.to_dict() if self.document else None,
            "parsed_content": self.parsed_content.to_dict() if self.parsed_content else None,
            "error": self.error,
            "error_details": self.error_details,
            "import_duration_ms": self.import_duration_ms,
            "content_length": self.content_length,
            "entities_extracted": self.entities_extracted,
            "message": self.message
        }
