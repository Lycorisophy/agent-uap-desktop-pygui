"""
历史回放播放器
模拟Silly Tavern的对话历史回放功能
"""

from typing import List, Dict, Optional, Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json


class PlaybackState(Enum):
    """播放状态"""
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"


@dataclass
class PlaybackEvent:
    """播放事件"""
    timestamp: str
    event_type: str  # 'prediction', 'anomaly', 'user_feedback'
    content: Dict
    display_time: float  # 显示时长(秒)


class HistoryPlayer:
    """
    历史回放播放器
    
    功能：
    1. 按时间顺序回放预测历史
    2. 支持播放/暂停/停止
    3. 回调通知UI更新
    4. 生成可视化数据
    """
    
    def __init__(self, history_store):
        self.history_store = history_store
        self.state = PlaybackState.STOPPED
        self.current_index = 0
        self.events: List[PlaybackEvent] = []
        self.playback_speed = 1.0
        self.on_event: Optional[Callable] = None
        self.on_complete: Optional[Callable] = None
    
    def load_project(self, project_id: str) -> int:
        """加载项目的预测历史"""
        records = self.history_store.get_project_history(project_id, limit=100)
        
        self.events = []
        for record in records:
            # 预测事件
            self.events.append(PlaybackEvent(
                timestamp=record.timestamp,
                event_type='prediction',
                content={
                    'id': record.id,
                    'method': record.method,
                    'horizon': record.horizon,
                    'result': record.result,
                    'status': record.status.value
                },
                display_time=3.0
            ))
            
            # 异常事件
            for anomaly in record.anomalies:
                self.events.append(PlaybackEvent(
                    timestamp=record.timestamp,
                    event_type='anomaly',
                    content=anomaly,
                    display_time=2.5
                ))
        
        # 按时间排序
        self.events.sort(key=lambda e: e.timestamp)
        
        return len(self.events)
    
    def play(self) -> None:
        """开始播放"""
        if not self.events:
            return
        
        self.state = PlaybackState.PLAYING
    
    def pause(self) -> None:
        """暂停播放"""
        self.state = PlaybackState.PAUSED
    
    def stop(self) -> None:
        """停止播放"""
        self.state = PlaybackState.STOPPED
        self.current_index = 0
    
    def next(self) -> Optional[PlaybackEvent]:
        """下一条事件"""
        if self.current_index < len(self.events):
            event = self.events[self.current_index]
            self.current_index += 1
            return event
        return None
    
    def previous(self) -> Optional[PlaybackEvent]:
        """上一条事件"""
        if self.current_index > 0:
            self.current_index -= 1
            return self.events[self.current_index]
        return None
    
    def seek(self, index: int) -> Optional[PlaybackEvent]:
        """跳转到指定位置"""
        if 0 <= index < len(self.events):
            self.current_index = index
            return self.events[index]
        return None
    
    def get_timeline_data(self) -> Dict:
        """获取时间线数据"""
        if not self.events:
            return {'events': [], 'markers': []}
        
        # 生成时间线标记
        markers = []
        for i, event in enumerate(self.events):
            markers.append({
                'index': i,
                'timestamp': event.timestamp,
                'type': event.event_type,
                'summary': self._get_event_summary(event)
            })
        
        return {
            'events': [
                {
                    'index': i,
                    'timestamp': e.timestamp,
                    'type': e.event_type
                }
                for i, e in enumerate(self.events)
            ],
            'markers': markers,
            'current_index': self.current_index,
            'total': len(self.events)
        }
    
    def get_comparison_data(self, record_id: str) -> Optional[Dict]:
        """获取对比数据"""
        record = self.history_store.get_record(record_id)
        if not record:
            return None
        
        predicted = record.result.get('values', []) if record.result else []
        actual = record.actual_values.get('values', []) if record.actual_values else []
        
        if not predicted:
            return None
        
        # 生成对比数据
        comparison = {
            'timestamp': record.timestamp,
            'method': record.method,
            'horizon': record.horizon,
            'points': []
        }
        
        for i in range(len(predicted)):
            point = {
                'index': i,
                'predicted': predicted[i] if i < len(predicted) else None,
                'actual': actual[i] if i < len(actual) else None
            }
            
            # 计算误差
            if point['predicted'] is not None and point['actual'] is not None:
                point['error'] = point['predicted'] - point['actual']
                point['error_percent'] = (
                    abs(point['error'] / point['actual'] * 100)
                    if point['actual'] != 0 else 0
                )
            
            comparison['points'].append(point)
        
        # 统计
        if actual and predicted:
            errors = [p - a for p, a in zip(predicted[:len(actual)], actual)]
            comparison['stats'] = {
                'mae': sum(abs(e) for e in errors) / len(errors) if errors else 0,
                'rmse': (sum(e**2 for e in errors) / len(errors)) ** 0.5 if errors else 0,
                'max_error': max(abs(e) for e in errors) if errors else 0,
                'direction_accuracy': self._calc_direction_accuracy(predicted, actual)
            }
        
        return comparison
    
    def export_comparison_report(self, project_id: str) -> Dict:
        """导出对比报告"""
        records = self.history_store.get_project_history(project_id, limit=100)
        
        # 筛选有实际值的记录
        with_actual = [r for r in records if r.actual_values]
        
        if not with_actual:
            return {'error': 'No records with actual values'}
        
        # 汇总统计
        total_predictions = len(with_actual)
        method_stats: Dict[str, Dict] = {}
        
        for record in with_actual:
            method = record.method
            if method not in method_stats:
                method_stats[method] = {'count': 0, 'total_error': 0}
            
            # 计算误差
            predicted = record.result.get('values', []) if record.result else []
            actual = record.actual_values.get('values', [])
            
            if predicted and actual:
                errors = [
                    abs(p - a) / max(abs(a), 0.001)
                    for p, a in zip(predicted[:len(actual)], actual)
                ]
                avg_error = sum(errors) / len(errors) if errors else 0
                
                method_stats[method]['count'] += 1
                method_stats[method]['total_error'] += avg_error
        
        # 计算平均误差
        for method in method_stats:
            count = method_stats[method]['count']
            if count > 0:
                method_stats[method]['avg_error'] = (
                    method_stats[method]['total_error'] / count
                )
        
        return {
            'generated_at': datetime.now().isoformat(),
            'project_id': project_id,
            'total_records': total_predictions,
            'method_performance': {
                method: {
                    'predictions': stats['count'],
                    'avg_error_percent': round(stats.get('avg_error', 0) * 100, 2)
                }
                for method, stats in method_stats.items()
            }
        }
    
    def _get_event_summary(self, event: PlaybackEvent) -> str:
        """获取事件摘要"""
        if event.event_type == 'prediction':
            method = event.content.get('method', 'unknown')
            status = event.content.get('status', 'unknown')
            return f"预测({method}) - {status}"
        elif event.event_type == 'anomaly':
            anomaly_type = event.content.get('type', 'unknown')
            severity = event.content.get('severity', 'unknown')
            return f"异常: {anomaly_type} ({severity})"
        return ""
    
    def _calc_direction_accuracy(self, predicted: List, actual: List) -> float:
        """计算方向准确率"""
        if len(predicted) < 2 or len(actual) < 2:
            return 0.0
        
        correct = 0
        total = 0
        
        for i in range(1, min(len(predicted), len(actual))):
            pred_dir = predicted[i] - predicted[i-1]
            actual_dir = actual[i] - actual[i-1]
            
            if pred_dir * actual_dir > 0:
                correct += 1
            total += 1
        
        return correct / total if total > 0 else 0.0


class TimelineVisualizer:
    """时间线可视化"""
    
    def __init__(self, width: int = 800, height: int = 100):
        self.width = width
        self.height = height
    
    def generate_svg(self, timeline_data: Dict) -> str:
        """生成SVG时间线"""
        events = timeline_data.get('events', [])
        current = timeline_data.get('current_index', 0)
        
        if not events:
            return self._empty_timeline()
        
        # 布局
        padding = 20
        track_height = 40
        plot_width = self.width - 2 * padding
        plot_height = self.height - 2 * padding
        
        # 生成SVG
        svg = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}">',
            '<defs>',
            '<style>',
            '.marker { cursor: pointer; }',
            '.marker:hover { opacity: 0.8; }',
            '.current { stroke: #4f46e5; stroke-width: 3; }',
            '</style>',
            '</defs>'
        ]
        
        # 背景
        svg.append(f'<rect width="100%" height="100%" fill="#f9fafb"/>')
        
        # 时间线轨道
        y = padding + plot_height // 2
        svg.append(f'<line x1="{padding}" y1="{y}" x2="{self.width - padding}" y2="{y}" stroke="#e5e7eb" stroke-width="2"/>')
        
        # 事件标记
        for i, event in enumerate(events):
            x = padding + (i / max(len(events) - 1, 1)) * plot_width
            
            # 颜色
            if event['type'] == 'prediction':
                color = '#4f46e5'
            elif event['type'] == 'anomaly':
                color = '#ef4444'
            else:
                color = '#6b7280'
            
            # 当前选中
            classes = 'marker' + (' current' if i == current else '')
            
            svg.append(
                f'<circle cx="{x}" cy="{y}" r="6" fill="{color}" class="{classes}" '
                f'data-index="{i}">'
                f'<title>{event["timestamp"]}</title></circle>'
            )
        
        # 当前指示器
        if 0 <= current < len(events):
            x = padding + (current / max(len(events) - 1, 1)) * plot_width
            svg.append(
                f'<line x1="{x}" y1="{y - 15}" x2="{x}" y2="{y + 15}" '
                f'stroke="#4f46e5" stroke-width="2"/>'
            )
        
        svg.append('</svg>')
        return '\n'.join(svg)
    
    def _empty_timeline(self) -> str:
        """空时间线"""
        return f'''
        <svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}">
            <rect width="100%" height="100%" fill="#f9fafb"/>
            <text x="{self.width // 2}" y="{self.height // 2}" text-anchor="middle" 
                  fill="#9ca3af" font-family="system-ui" font-size="14">
                无历史记录
            </text>
        </svg>
        '''
