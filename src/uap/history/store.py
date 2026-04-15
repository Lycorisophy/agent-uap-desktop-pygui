"""
预测历史存储
管理预测记录的持久化
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
import json
from pathlib import Path


class PredictionStatus(Enum):
    """预测状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class PredictionRecord:
    """预测记录"""
    id: str
    project_id: str
    timestamp: str
    status: PredictionStatus
    
    # 配置
    horizon: int           # 预测时长(秒)
    method: str             # 预测方法
    
    # 结果
    result: Optional[Dict] = None
    anomalies: List[Dict] = field(default_factory=list)
    
    # 元数据
    duration: Optional[float] = None  # 执行时长(秒)
    error: Optional[str] = None
    
    # 对比
    actual_values: Optional[Dict] = None  # 实际值(后期回填)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'project_id': self.project_id,
            'timestamp': self.timestamp,
            'status': self.status.value,
            'horizon': self.horizon,
            'method': self.method,
            'result': self.result,
            'anomalies': self.anomalies,
            'duration': self.duration,
            'error': self.error,
            'has_actual': self.actual_values is not None
        }


class HistoryStore:
    """
    预测历史存储
    
    存储、检索预测历史记录
    """
    
    def __init__(self, storage_path: str):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.index_file = self.storage_path / "index.json"
        self._load_index()
    
    def _load_index(self) -> None:
        """加载索引"""
        if self.index_file.exists():
            with open(self.index_file, 'r', encoding='utf-8') as f:
                self.index: Dict[str, List[str]] = json.load(f)
        else:
            self.index = {}
    
    def _save_index(self) -> None:
        """保存索引"""
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(self.index, f, ensure_ascii=False, indent=2)
    
    def add_record(self, record: PredictionRecord) -> None:
        """添加预测记录"""
        # 保存记录文件
        record_file = self.storage_path / f"{record.id}.json"
        with open(record_file, 'w', encoding='utf-8') as f:
            json.dump(record.to_dict(), f, ensure_ascii=False, indent=2)
        
        # 更新索引
        if record.project_id not in self.index:
            self.index[record.project_id] = []
        self.index[record.project_id].append(record.id)
        self._save_index()
    
    def get_record(self, record_id: str) -> Optional[PredictionRecord]:
        """获取单条记录"""
        record_file = self.storage_path / f"{record_id}.json"
        if not record_file.exists():
            return None
        
        with open(record_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        return self._dict_to_record(data)
    
    def get_project_history(
        self,
        project_id: str,
        limit: int = 100,
        offset: int = 0
    ) -> List[PredictionRecord]:
        """获取项目的预测历史"""
        record_ids = self.index.get(project_id, [])
        record_ids = list(reversed(record_ids))  # 最新在前
        
        records = []
        for record_id in record_ids[offset:offset + limit]:
            record = self.get_record(record_id)
            if record:
                records.append(record)
        
        return records
    
    def compare_with_actual(
        self,
        record_id: str,
        actual_values: Dict
    ) -> Optional[Dict]:
        """对比预测与实际值"""
        record = self.get_record(record_id)
        if not record or not record.result:
            return None
        
        # 更新记录
        record.actual_values = actual_values
        self.add_record(record)
        
        # 计算误差
        predicted = record.result.get('values', [])
        actual = actual_values.get('values', [])
        
        if len(predicted) != len(actual):
            return {'error': 'Length mismatch'}
        
        # 计算各种误差指标
        mae = sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted)
        mse = sum((p - a) ** 2 for p, a in zip(predicted, actual)) / len(predicted)
        rmse = mse ** 0.5
        
        # 计算方向准确率
        correct_direction = sum(
            1 for i in range(1, len(predicted))
            if (predicted[i] - predicted[i-1]) * (actual[i] - actual[i-1]) > 0
        ) / max(1, len(predicted) - 1)
        
        return {
            'mae': round(mae, 4),
            'mse': round(mse, 4),
            'rmse': round(rmse, 4),
            'direction_accuracy': round(correct_direction * 100, 2)
        }
    
    def get_statistics(self, project_id: str) -> Dict:
        """获取项目统计信息"""
        records = self.get_project_history(project_id, limit=1000)
        
        if not records:
            return {'total': 0}
        
        completed = [r for r in records if r.status == PredictionStatus.COMPLETED]
        
        total_anomalies = sum(len(r.anomalies) for r in records)
        has_actual = [r for r in records if r.actual_values]
        
        # 方法使用统计
        method_counts: Dict[str, int] = {}
        for r in records:
            method_counts[r.method] = method_counts.get(r.method, 0) + 1
        
        return {
            'total': len(records),
            'completed': len(completed),
            'failed': len(records) - len(completed),
            'anomalies_detected': total_anomalies,
            'with_actual': len(has_actual),
            'methods': method_counts
        }
    
    def delete_old_records(self, project_id: str, keep_count: int = 100) -> int:
        """删除旧记录"""
        record_ids = self.index.get(project_id, [])
        
        if len(record_ids) <= keep_count:
            return 0
        
        to_delete = record_ids[:-keep_count]
        deleted = 0
        
        for record_id in to_delete:
            record_file = self.storage_path / f"{record_id}.json"
            if record_file.exists():
                record_file.unlink()
                deleted += 1
        
        # 更新索引
        self.index[project_id] = record_ids[-keep_count:]
        self._save_index()
        
        return deleted
    
    def _dict_to_record(self, data: Dict) -> PredictionRecord:
        """字典转记录"""
        return PredictionRecord(
            id=data['id'],
            project_id=data['project_id'],
            timestamp=data['timestamp'],
            status=PredictionStatus(data['status']),
            horizon=data['horizon'],
            method=data['method'],
            result=data.get('result'),
            anomalies=data.get('anomalies', []),
            duration=data.get('duration'),
            error=data.get('error'),
            actual_values=data.get('actual_values')
        )
