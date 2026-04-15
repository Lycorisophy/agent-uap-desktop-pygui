"""
UAP 向量检索系统 - 向量存储模块

基于 sqlite-vss 的本地向量相似性搜索实现。
sqlite-vss 是 SQLite 的向量相似性搜索扩展，支持：
- 高维向量存储
- 余弦相似度搜索
- 最近邻搜索
- 近似最近邻搜索
"""

import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Tuple, Any
from dataclasses import dataclass, field

import numpy as np


@dataclass
class VectorRecord:
    """
    向量记录数据类
    
    表示存储在向量数据库中的一条记录。
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    collection: str = ""           # 所属集合
    content: str = ""              # 原始文本内容
    vector: List[float] = field(default_factory=list)  # 向量
    metadata: dict = field(default_factory=dict)  # 元数据
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "id": self.id,
            "collection": self.collection,
            "content": self.content,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "VectorRecord":
        """从字典创建"""
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            collection=data.get("collection", ""),
            content=data.get("content", ""),
            metadata=data.get("metadata", {}),
            created_at=datetime.fromisoformat(data["created_at"]) 
                if "created_at" in data and data["created_at"] else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) 
                if "updated_at" in data and data["updated_at"] else datetime.now()
        )


class VectorStore:
    """
    向量存储管理器
    
    基于 sqlite-vss 实现本地向量相似性搜索。
    
    特性：
    - 多集合支持：不同项目/类型的数据分不同集合
    - 元数据过滤：支持在向量搜索时过滤元数据
    - 批量操作：支持批量插入和搜索
    - 自动补全：向量维度自动补齐到标准维度
    
    使用 sqlite-vss 需要先安装：
    pip install sqlite-vss
    """
    
    # 默认向量维度 (nomic-embed-text 输出 768 维)
    DEFAULT_DIMENSION = 768
    
    def __init__(
        self,
        db_path: str,
        embedding_service: "EmbeddingService" = None,
        dimension: int = DEFAULT_DIMENSION
    ):
        """
        初始化向量存储
        
        Args:
            db_path: 数据库文件路径
            embedding_service: 嵌入服务（用于自动生成向量）
            dimension: 向量维度
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.dimension = dimension
        self.embedding_service = embedding_service
        
        self._conn: Optional[sqlite3.Connection] = None
        self._vss_available = False
        
        # 初始化数据库
        self._initialize_db()
    
    def _initialize_db(self) -> None:
        """初始化数据库和表结构"""
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        
        # 尝试加载 sqlite-vss 扩展
        try:
            import sqlite_vss
            self._conn.enable_load_extension(True)
            self._conn.load_extension("vss")
            self._vss_available = True
        except ImportError:
            print("sqlite-vss not installed, using fallback mode")
            self._vss_available = False
        except Exception as e:
            print(f"Failed to load vss extension: {e}")
            self._vss_available = False
        
        # 创建基础表
        self._create_tables()
    
    def _create_tables(self) -> None:
        """创建数据库表"""
        cursor = self._conn.cursor()
        
        # 向量记录表（存储原始数据）
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS vector_records (
                id TEXT PRIMARY KEY,
                collection TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        # 创建索引
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_collection 
            ON vector_records(collection)
        """)
        
        if self._vss_available:
            # sqlite-vss 虚拟表
            cursor.execute(f"""
                CREATE VIRTUAL TABLE IF NOT EXISTS vss_vectors 
                USING vss0(dimension={self.dimension})
            """)
            
            # 内容表（存储向量）
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vss_content (
                    id TEXT PRIMARY KEY,
                    vector BLOB NOT NULL,
                    FOREIGN KEY (id) REFERENCES vector_records(id)
                )
            """)
        else:
            # 使用 numpy 存储的降级方案
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS np_vectors (
                    id TEXT PRIMARY KEY,
                    vector TEXT NOT NULL,
                    FOREIGN KEY (id) REFERENCES vector_records(id)
                )
            """)
        
        self._conn.commit()
    
    @property
    def is_vss_available(self) -> bool:
        """检查 vss 扩展是否可用"""
        return self._vss_available
    
    # ==================== 插入操作 ====================
    
    def insert(
        self,
        collection: str,
        content: str,
        vector: List[float] = None,
        metadata: dict = None,
        id: str = None
    ) -> str:
        """
        插入向量记录
        
        Args:
            collection: 集合名称
            content: 文本内容
            vector: 向量（如果为 None，使用 embedding_service 自动生成）
            metadata: 元数据
            id: 记录ID（可选，自动生成）
            
        Returns:
            记录ID
        """
        # 生成 ID
        record_id = id or str(uuid.uuid4())
        
        # 生成向量
        if vector is None:
            if self.embedding_service is None:
                raise ValueError("embedding_service is required if vector is None")
            vector = self.embedding_service.embed(content)
        
        # 补齐维度
        vector = self._pad_vector(vector)
        
        # 创建记录
        record = VectorRecord(
            id=record_id,
            collection=collection,
            content=content,
            vector=vector,
            metadata=metadata or {},
            created_at=datetime.now(),
            updated_at=datetime.now()
        )
        
        self._insert_record(record)
        
        return record_id
    
    def insert_batch(
        self,
        records: List[VectorRecord]
    ) -> List[str]:
        """
        批量插入向量记录
        
        Args:
            records: 记录列表
            
        Returns:
            记录ID列表
        """
        ids = []
        for record in records:
            record.vector = self._pad_vector(record.vector)
            self._insert_record(record)
            ids.append(record.id)
        
        return ids
    
    def _insert_record(self, record: VectorRecord) -> None:
        """插入单条记录"""
        cursor = self._conn.cursor()
        
        # 插入基础记录
        cursor.execute("""
            INSERT OR REPLACE INTO vector_records 
            (id, collection, content, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            record.id,
            record.collection,
            record.content,
            json.dumps(record.metadata, ensure_ascii=False),
            record.created_at.isoformat(),
            record.updated_at.isoformat()
        ))
        
        # 插入向量
        if self._vss_available:
            vector_bytes = np.array(record.vector, dtype=np.float32).tobytes()
            cursor.execute("""
                INSERT OR REPLACE INTO vss_content (id, vector)
                VALUES (?, ?)
            """, (record.id, vector_bytes))
            
            # 插入 vss 向量表
            cursor.execute("""
                INSERT INTO vss_vectors (rowid, id, vector)
                SELECT rowid, id, vector FROM vss_content
                WHERE id = ?
            """, (record.id,))
        else:
            vector_json = json.dumps(record.vector)
            cursor.execute("""
                INSERT OR REPLACE INTO np_vectors (id, vector)
                VALUES (?, ?)
            """, (record.id, vector_json))
        
        self._conn.commit()
    
    def _pad_vector(self, vector: List[float]) -> List[float]:
        """补齐向量到标准维度"""
        if len(vector) >= self.dimension:
            return vector[:self.dimension]
        
        # 补零
        padded = list(vector) + [0.0] * (self.dimension - len(vector))
        return padded
    
    # ==================== 搜索操作 ====================
    
    def search(
        self,
        collection: str,
        query: str = None,
        query_vector: List[float] = None,
        limit: int = 5,
        filter_metadata: dict = None
    ) -> List[Tuple[VectorRecord, float]]:
        """
        向量相似性搜索
        
        Args:
            collection: 集合名称
            query: 查询文本（使用 embedding_service 生成向量）
            query_vector: 查询向量（优先使用）
            limit: 返回数量限制
            filter_metadata: 元数据过滤条件
            
        Returns:
            (记录, 相似度分数) 列表
        """
        # 生成查询向量
        if query_vector is None:
            if self.embedding_service is None:
                raise ValueError("embedding_service is required if query_vector is None")
            query_vector = self.embedding_service.embed(query)
        
        query_vector = self._pad_vector(list(query_vector))
        
        if self._vss_available:
            return self._vss_search(
                collection, query_vector, limit, filter_metadata
            )
        else:
            return self._numpy_search(
                collection, query_vector, limit, filter_metadata
            )
    
    def _vss_search(
        self,
        collection: str,
        query_vector: List[float],
        limit: int,
        filter_metadata: dict
    ) -> List[Tuple[VectorRecord, float]]:
        """使用 sqlite-vss 搜索"""
        cursor = self._conn.cursor()
        
        # 构建查询
        # sqlite-vss 使用余弦相似度
        placeholders = ", ".join(["?" for _ in query_vector])
        
        sql = f"""
            SELECT 
                r.id,
                r.collection,
                r.content,
                r.metadata,
                r.created_at,
                r.updated_at,
                vss_distance(vector, [{placeholders}]) as distance
            FROM vss_vectors v
            JOIN vector_records r ON v.id = r.id
            WHERE r.collection = ?
        """
        
        params = list(query_vector) + [collection]
        
        # 添加元数据过滤
        if filter_metadata:
            for key, value in filter_metadata.items():
                sql += f" AND r.metadata LIKE ?"
                params.append(f'%"{key}": "{value}"%')
        
        sql += f"""
            ORDER BY distance ASC
            LIMIT ?
        """
        params.append(limit)
        
        cursor.execute(sql, params)
        
        results = []
        for row in cursor.fetchall():
            record = VectorRecord(
                id=row["id"],
                collection=row["collection"],
                content=row["content"],
                metadata=json.loads(row["metadata"] or "{}"),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            )
            # vss_distance 返回欧氏距离，转换为相似度
            distance = row["distance"]
            similarity = 1.0 / (1.0 + distance)  # 转换公式
            results.append((record, similarity))
        
        return results
    
    def _numpy_search(
        self,
        collection: str,
        query_vector: List[float],
        limit: int,
        filter_metadata: dict
    ) -> List[Tuple[VectorRecord, float]]:
        """使用 numpy 降级搜索（适用于 sqlite-vss 不可用时）"""
        cursor = self._conn.cursor()
        
        # 获取集合中的所有记录
        sql = """
            SELECT r.*, n.vector
            FROM vector_records r
            JOIN np_vectors n ON r.id = n.id
            WHERE r.collection = ?
        """
        params = [collection]
        
        if filter_metadata:
            for key, value in filter_metadata.items():
                sql += f" AND r.metadata LIKE ?"
                params.append(f'%"{key}": "{value}"%')
        
        cursor.execute(sql, params)
        
        query_arr = np.array(query_vector)
        results = []
        
        for row in cursor.fetchall():
            stored_vector = np.array(json.loads(row["vector"]))
            
            # 计算余弦相似度
            similarity = self._cosine_similarity(query_arr, stored_vector)
            
            record = VectorRecord(
                id=row["id"],
                collection=row["collection"],
                content=row["content"],
                metadata=json.loads(row["metadata"] or "{}"),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            )
            
            results.append((record, float(similarity)))
        
        # 排序并限制数量
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:limit]
    
    @staticmethod
    def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        """计算余弦相似度"""
        norm_a = np.linalg.norm(a)
        norm_b = np.linalg.norm(b)
        
        if norm_a == 0 or norm_b == 0:
            return 0.0
        
        return float(np.dot(a, b) / (norm_a * norm_b))
    
    # ==================== 查询操作 ====================
    
    def get(self, record_id: str) -> Optional[VectorRecord]:
        """获取指定记录"""
        cursor = self._conn.cursor()
        
        cursor.execute("""
            SELECT * FROM vector_records WHERE id = ?
        """, (record_id,))
        
        row = cursor.fetchone()
        if not row:
            return None
        
        return VectorRecord(
            id=row["id"],
            collection=row["collection"],
            content=row["content"],
            metadata=json.loads(row["metadata"] or "{}"),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"])
        )
    
    def list(
        self,
        collection: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[VectorRecord]:
        """列出集合中的记录"""
        cursor = self._conn.cursor()
        
        cursor.execute("""
            SELECT * FROM vector_records 
            WHERE collection = ?
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """, (collection, limit, offset))
        
        records = []
        for row in cursor.fetchall():
            records.append(VectorRecord(
                id=row["id"],
                collection=row["collection"],
                content=row["content"],
                metadata=json.loads(row["metadata"] or "{}"),
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"])
            ))
        
        return records
    
    def count(self, collection: str) -> int:
        """获取集合中的记录数量"""
        cursor = self._conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) as count FROM vector_records WHERE collection = ?
        """, (collection,))
        
        return cursor.fetchone()["count"]
    
    # ==================== 更新操作 ====================
    
    def update(
        self,
        record_id: str,
        content: str = None,
        vector: List[float] = None,
        metadata: dict = None
    ) -> bool:
        """
        更新记录
        
        Args:
            record_id: 记录ID
            content: 新内容（可选）
            vector: 新向量（可选）
            metadata: 新元数据（可选）
            
        Returns:
            是否更新成功
        """
        # 获取现有记录
        record = self.get(record_id)
        if not record:
            return False
        
        # 更新字段
        if content is not None:
            record.content = content
        
        if vector is not None:
            record.vector = self._pad_vector(vector)
        
        if metadata is not None:
            record.metadata = metadata
        
        record.updated_at = datetime.now()
        
        # 重新插入
        self._insert_record(record)
        
        return True
    
    # ==================== 删除操作 ====================
    
    def delete(self, record_id: str) -> bool:
        """
        删除记录
        
        Args:
            record_id: 记录ID
            
        Returns:
            是否删除成功
        """
        cursor = self._conn.cursor()
        
        # 删除向量
        if self._vss_available:
            cursor.execute("DELETE FROM vss_content WHERE id = ?", (record_id,))
            cursor.execute("DELETE FROM vss_vectors WHERE id = ?", (record_id,))
        else:
            cursor.execute("DELETE FROM np_vectors WHERE id = ?", (record_id,))
        
        # 删除记录
        cursor.execute("DELETE FROM vector_records WHERE id = ?", (record_id,))
        
        self._conn.commit()
        
        return cursor.rowcount > 0
    
    def delete_collection(self, collection: str) -> int:
        """
        删除整个集合
        
        Args:
            collection: 集合名称
            
        Returns:
            删除的记录数量
        """
        # 先获取所有记录
        records = self.list(collection)
        
        # 删除所有向量
        for record in records:
            self.delete(record.id)
        
        return len(records)
    
    # ==================== 工具方法 ====================
    
    def exists_collection(self, collection: str) -> bool:
        """检查集合是否存在"""
        return self.count(collection) > 0
    
    def get_collections(self) -> List[str]:
        """获取所有集合名称"""
        cursor = self._conn.cursor()
        
        cursor.execute("""
            SELECT DISTINCT collection FROM vector_records
        """)
        
        return [row["collection"] for row in cursor.fetchall()]
    
    def rebuild_index(self) -> None:
        """
        重建 vss 索引
        
        当插入大量数据后调用以提升搜索性能。
        仅在 sqlite-vss 可用时有效。
        """
        if not self._vss_available:
            return
        
        cursor = self._conn.cursor()
        
        # 删除旧索引
        cursor.execute("DROP TABLE IF EXISTS vss_vectors")
        
        # 重建索引
        cursor.execute(f"""
            CREATE VIRTUAL TABLE vss_vectors USING vss0(dimension={self.dimension})
        """)
        
        # 重新插入所有向量
        cursor.execute("SELECT id, vector FROM np_vectors")
        
        for row in cursor.fetchall():
            cursor.execute("""
                INSERT INTO vss_vectors (rowid, id, vector)
                VALUES (
                    (SELECT rowid FROM vector_records WHERE id = ?),
                    ?, ?
                )
            """, (row["id"], row["id"], row["vector"]))
        
        self._conn.commit()
    
    def close(self) -> None:
        """关闭数据库连接"""
        if self._conn:
            self._conn.close()
            self._conn = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
