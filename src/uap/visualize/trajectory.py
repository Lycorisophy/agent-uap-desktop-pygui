"""
轨迹图绘制器
绘制系统状态变量的预测轨迹，包含置信区间和异常标注
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
import json
from pathlib import Path


@dataclass
class DataPoint:
    """数据点"""
    timestamp: float
    value: float
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    is_anomaly: bool = False
    confidence: float = 1.0


@dataclass
class TrajectoryData:
    """轨迹数据"""
    variable_name: str
    unit: str
    data_points: List[DataPoint]
    color: str = "#4f46e5"


class TrajectoryPlotter:
    """
    轨迹图绘制器
    
    生成SVG格式的轨迹图，支持：
    - 多变量同时显示
    - 置信区间显示
    - 异常点标注
    - 缩放和平移
    """
    
    def __init__(
        self,
        width: int = 800,
        height: int = 400,
        padding: int = 60,
        bg_color: str = "#ffffff"
    ):
        self.width = width
        self.height = height
        self.padding = padding
        self.bg_color = bg_color
        self.plot_width = width - 2 * padding
        self.plot_height = height - 2 * padding
        
        # 颜色方案
        self.colors = [
            "#4f46e5",  # 靛蓝
            "#10b981",  # 翡翠绿
            "#f59e0b",  # 琥珀
            "#ef4444",  # 红色
            "#8b5cf6",  # 紫色
            "#06b6d4",  # 青色
            "#ec4899",  # 粉色
            "#84cc16",  # 青柠
        ]
    
    def plot(
        self,
        trajectories: List[TrajectoryData],
        title: str = "预测轨迹",
        x_label: str = "时间",
        y_label: str = "状态值",
        show_grid: bool = True,
        show_legend: bool = True
    ) -> str:
        """
        绘制轨迹图
        
        Args:
            trajectories: 轨迹数据列表
            title: 图表标题
            x_label: X轴标签
            y_label: Y轴标签
            
        Returns:
            SVG格式的图表字符串
        """
        if not trajectories:
            return self._empty_chart("无数据")
        
        # 计算数据范围
        all_times = []
        all_values = []
        for traj in trajectories:
            for point in traj.data_points:
                all_times.append(point.timestamp)
                all_values.append(point.value)
                if point.lower_bound is not None:
                    all_values.append(point.lower_bound)
                if point.upper_bound is not None:
                    all_values.append(point.upper_bound)
        
        if not all_times or not all_values:
            return self._empty_chart("数据为空")
        
        # 计算范围和缩放
        x_min, x_max = min(all_times), max(all_times)
        y_min, y_max = min(all_values), max(all_values)
        y_range = y_max - y_min if y_max != y_min else 1
        
        # 添加边距
        y_min -= y_range * 0.1
        y_max += y_range * 0.1
        
        # 构建SVG
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}">',
            f'<rect width="100%" height="100%" fill="{self.bg_color}"/>',
        ]
        
        # 标题
        svg_parts.append(
            f'<text x="{self.width // 2}" y="30" text-anchor="middle" '
            f'font-family="system-ui, sans-serif" font-size="16" font-weight="600" fill="#1f2937">'
            f'{self._escape(title)}</text>'
        )
        
        # 网格
        if show_grid:
            svg_parts.append(self._draw_grid(x_min, x_max, y_min, y_max))
        
        # 坐标轴
        svg_parts.append(self._draw_axes(x_min, x_max, y_min, y_max, x_label, y_label))
        
        # 绘制每个轨迹
        anomaly_points = []
        for i, traj in enumerate(trajectories):
            color = traj.color or self.colors[i % len(self.colors)]
            
            # 置信区间
            has_confidence = any(
                p.lower_bound is not None and p.upper_bound is not None 
                for p in traj.data_points
            )
            if has_confidence:
                svg_parts.append(self._draw_confidence_band(traj, x_min, x_max, y_min, y_max, color))
            
            # 轨迹线
            svg_parts.append(self._draw_trajectory_line(traj, x_min, x_max, y_min, y_max, color))
            
            # 异常点
            for point in traj.data_points:
                if point.is_anomaly:
                    anomaly_points.append((traj, point, x_min, x_max, y_min, y_max))
        
        # 绘制异常点
        for traj, point, x_min, x_max, y_min, y_max in anomaly_points:
            svg_parts.append(self._draw_anomaly_marker(point, x_min, x_max, y_min, y_max))
        
        # 图例
        if show_legend:
            svg_parts.append(self._draw_legend(trajectories))
        
        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)
    
    def _draw_grid(self, x_min: float, x_max: float, y_min: float, y_max: float) -> str:
        """绘制网格"""
        lines = ['<g class="grid" stroke="#e5e7eb" stroke-width="1">']
        
        # 水平线
        for i in range(5):
            y = self.padding + (i / 4) * self.plot_height
            lines.append(f'<line x1="{self.padding}" y1="{y}" x2="{self.width - self.padding}" y2="{y}"/>')
        
        # 垂直线
        for i in range(6):
            x = self.padding + (i / 5) * self.plot_width
            lines.append(f'<line x1="{x}" y1="{self.padding}" x2="{x}" y2="{self.height - self.padding}"/>')
        
        lines.append('</g>')
        return '\n'.join(lines)
    
    def _draw_axes(
        self,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        x_label: str, y_label: str
    ) -> str:
        """绘制坐标轴"""
        parts = ['<g class="axes">']
        
        # X轴
        parts.append(
            f'<line x1="{self.padding}" y1="{self.height - self.padding}" '
            f'x2="{self.width - self.padding}" y2="{self.height - self.padding}" '
            f'stroke="#1f2937" stroke-width="2"/>'
        )
        
        # Y轴
        parts.append(
            f'<line x1="{self.padding}" y1="{self.padding}" '
            f'x2="{self.padding}" y2="{self.height - self.padding}" '
            f'stroke="#1f2937" stroke-width="2"/>'
        )
        
        # X轴刻度和标签
        for i in range(6):
            x = self.padding + (i / 5) * self.plot_width
            value = x_min + (i / 5) * (x_max - x_min)
            parts.append(
                f'<text x="{x}" y="{self.height - self.padding + 20}" '
                f'text-anchor="middle" font-family="system-ui" font-size="12" fill="#6b7280">'
                f'{self._format_time(value)}</text>'
            )
        
        # X轴标签
        parts.append(
            f'<text x="{self.width // 2}" y="{self.height - 10}" '
            f'text-anchor="middle" font-family="system-ui" font-size="13" fill="#374151">'
            f'{self._escape(x_label)}</text>'
        )
        
        # Y轴刻度和标签
        for i in range(5):
            y = self.padding + (i / 4) * self.plot_height
            value = y_max - (i / 4) * (y_max - y_min)
            parts.append(
                f'<text x="{self.padding - 10}" y="{y + 4}" '
                f'text-anchor="end" font-family="system-ui" font-size="12" fill="#6b7280">'
                f'{value:.2f}</text>'
            )
        
        # Y轴标签
        parts.append(
            f'<text x="15" y="{self.height // 2}" '
            f'text-anchor="middle" font-family="system-ui" font-size="13" fill="#374151" '
            f'transform="rotate(-90, 15, {self.height // 2})">'
            f'{self._escape(y_label)}</text>'
        )
        
        parts.append('</g>')
        return '\n'.join(parts)
    
    def _draw_confidence_band(
        self,
        trajectory: TrajectoryData,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        color: str
    ) -> str:
        """绘制置信区间带"""
        valid_points = [
            p for p in trajectory.data_points
            if p.lower_bound is not None and p.upper_bound is not None
        ]
        
        if len(valid_points) < 2:
            return ""
        
        points = []
        for p in valid_points:
            x = self.padding + (p.timestamp - x_min) / (x_max - x_min) * self.plot_width
            y_upper = self.padding + (y_max - p.upper_bound) / (y_max - y_min) * self.plot_height
            y_lower = self.padding + (y_max - p.lower_bound) / (y_max - y_min) * self.plot_height
            points.append((x, y_upper, y_lower))
        
        # 构建路径
        upper_path = 'M ' + ' '.join(f'{x},{y}' for x, y, _ in points)
        lower_path = ' M ' + ' '.join(f'{x},{y}' for x, _, y in reversed(points))
        
        fill_color = color.replace('#', '') + '20'  # 20% 透明度
        
        return f'''
        <g class="confidence-band">
            <path d="{upper_path}{lower_path}Z" fill="#{fill_color}" stroke="none"/>
        </g>
        '''
    
    def _draw_trajectory_line(
        self,
        trajectory: TrajectoryData,
        x_min: float, x_max: float,
        y_min: float, y_max: float,
        color: str
    ) -> str:
        """绘制轨迹线"""
        if len(trajectory.data_points) < 2:
            return ""
        
        points = []
        for p in trajectory.data_points:
            x = self.padding + (p.timestamp - x_min) / (x_max - x_min) * self.plot_width
            y = self.padding + (y_max - p.value) / (y_max - y_min) * self.plot_height
            points.append((x, y))
        
        path_data = 'M ' + ' L '.join(f'{x},{y}' for x, y in points)
        
        return f'''
        <g class="trajectory">
            <path d="{path_data}" fill="none" stroke="{color}" stroke-width="2.5" 
                  stroke-linecap="round" stroke-linejoin="round"/>
        </g>
        '''
    
    def _draw_anomaly_marker(
        self,
        point: DataPoint,
        x_min: float, x_max: float,
        y_min: float, y_max: float
    ) -> str:
        """绘制异常点标记"""
        x = self.padding + (point.timestamp - x_min) / (x_max - x_min) * self.plot_width
        y = self.padding + (y_max - point.value) / (y_max - y_min) * self.plot_height
        
        # 红色圆圈
        return f'''
        <g class="anomaly-marker">
            <circle cx="{x}" cy="{y}" r="8" fill="#ef4444" fill-opacity="0.2" stroke="#ef4444" stroke-width="2"/>
            <circle cx="{x}" cy="{y}" r="3" fill="#ef4444"/>
        </g>
        '''
    
    def _draw_legend(self, trajectories: List[TrajectoryData]) -> str:
        """绘制图例"""
        legend_x = self.width - self.padding - 150
        legend_y = self.padding + 10
        
        items = []
        for i, traj in enumerate(trajectories[:5]):  # 最多5个
            color = traj.color or self.colors[i % len(self.colors)]
            label = f"{traj.variable_name}"
            if traj.unit:
                label += f" ({traj.unit})"
            
            y = legend_y + i * 22
            items.append(f'''
                <line x1="{legend_x}" y1="{y}" x2="{legend_x + 20}" y2="{y}" 
                      stroke="{color}" stroke-width="3" stroke-linecap="round"/>
                <text x="{legend_x + 28}" y="{y + 4}" font-family="system-ui" font-size="12" fill="#374151">
                    {self._escape(label[:12])}
                </text>
            ''')
        
        return f'<g class="legend">{chr(10).join(items)}</g>'
    
    def _empty_chart(self, message: str) -> str:
        """空图表"""
        return f'''
        <svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}">
            <rect width="100%" height="100%" fill="{self.bg_color}"/>
            <text x="{self.width // 2}" y="{self.height // 2}" text-anchor="middle" 
                  font-family="system-ui" font-size="14" fill="#9ca3af">
                {self._escape(message)}
            </text>
        </svg>
        '''
    
    def _escape(self, text: str) -> str:
        """转义XML特殊字符"""
        return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))
    
    def _format_time(self, timestamp: float) -> str:
        """格式化时间标签"""
        hours = int(timestamp / 3600)
        if hours < 24:
            return f"{hours}h"
        days = hours // 24
        remaining_hours = hours % 24
        return f"{days}d{remaining_hours}h" if remaining_hours else f"{days}d"
    
    def save(self, svg_content: str, filepath: str) -> None:
        """保存SVG到文件"""
        Path(filepath).parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(svg_content)
    
    def to_base64(self, svg_content: str) -> str:
        """SVG转Base64用于嵌入"""
        import base64
        return base64.b64encode(svg_content.encode('utf-8')).decode('ascii')


def create_demo_trajectory() -> List[TrajectoryData]:
    """创建演示轨迹数据"""
    import math
    
    trajectories = []
    
    # 频率变量
    freq_points = []
    for i in range(100):
        t = i * 3600  # 每小时
        base = 50.0
        noise = math.sin(i * 0.3) * 0.2
        anomaly = 0.5 if 40 < i < 45 else 0
        freq_points.append(DataPoint(
            timestamp=t,
            value=base + noise + anomaly,
            lower_bound=base + noise - 0.3,
            upper_bound=base + noise + 0.3,
            is_anomaly=anomaly > 0
        ))
    trajectories.append(TrajectoryData(
        variable_name="frequency",
        unit="Hz",
        data_points=freq_points,
        color="#4f46e5"
    ))
    
    # 电压变量
    volt_points = []
    for i in range(100):
        t = i * 3600
        base = 1.0
        noise = math.cos(i * 0.2) * 0.05
        volt_points.append(DataPoint(
            timestamp=t,
            value=base + noise,
            lower_bound=base + noise - 0.08,
            upper_bound=base + noise + 0.08,
            is_anomaly=False
        ))
    trajectories.append(TrajectoryData(
        variable_name="voltage",
        unit="p.u.",
        data_points=volt_points,
        color="#10b981"
    ))
    
    return trajectories
