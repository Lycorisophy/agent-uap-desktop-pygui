"""
UAP 文档导入解析系统 - 模块入口

支持 PDF、Word、Markdown 等格式的文档解析。
用于从文档中提取复杂系统相关信息。
"""

from uap.document.models import (
    Document,
    DocumentType,
    ParsedContent,
    SystemEntity,
    EntityType,
)
from uap.document.parser import (
    DocumentParser,
    MarkdownParser,
    PdfParser,
    WordParser,
    create_parser,
)
from uap.document.importer import DocumentImporter


__all__ = [
    # 数据模型
    "Document",
    "DocumentType",
    "ParsedContent",
    "SystemEntity",
    "EntityType",
    # 解析器
    "DocumentParser",
    "MarkdownParser",
    "PdfParser",
    "WordParser",
    "create_parser",
    # 导入服务
    "DocumentImporter",
]
