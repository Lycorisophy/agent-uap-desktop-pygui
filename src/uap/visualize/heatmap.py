"""
演化热力图模块
可视化多步预测的动态演化过程
"""

from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import json


class HeatmapColorScheme(Enum):
    """热力图配色方案"""
    BLUES = "blues"
    VIRIDIS = "viridis"
    MAGMA = "magma"
    INFERNO = "inferno"
    TURBO = "turbo"
    GRAYSCALE = "grayscale"


@dataclass
class HeatmapCell:
    """热力图单元格"""
    time_index: int
    variable_index: int
    value: float
    normalized_value: float  # 0-1 归一化值
    is_anomaly: bool = False


class EvolutionHeatmap:
    """
    演化热力图
    
    用于可视化：
    1. 多变量多时间步的预测演化
    2. 不确定性随时间的传播
    3. 系统状态的动态变化
    """
    
    # 配色表
    COLOR_SCHEMES = {
        HeatmapColorScheme.BLUES: [
            "#f7fbff", "#deebf7", "#c6dbef", "#9ecae1",
            "#6baed6", "#4292c6", "#2171b5", "#08519c", "#08306b"
        ],
        HeatmapColorScheme.VIRIDIS: [
            "#440154", "#482878", "#3e4a89", "#31688e",
            "#26838f", "#1f9e89", "#35b779", "#6ece58", "#b5de2b", "#fde725"
        ],
        HeatmapColorScheme.MAGMA: [
            "#000004", "#180f3d", "#440f76", "#721f81",
            "#9e2f7f", "#cd4071", "#f1605d", "#fd9668", "#feca8d", "#fcfdbf"
        ],
        HeatmapColorScheme.GRAYSCALE: [
            "#ffffff", "#f0f0f0", "#d9d9d9", "#bdbdbd",
            "#969696", "#737373", "#525252", "#252525", "#000000"
        ]
    }
    
    def __init__(
        self,
        width: int = 600,
        height: int = 400,
        color_scheme: HeatmapColorScheme = HeatmapColorScheme.BLUES
    ):
        self.width = width
        self.height = height
        self.color_scheme = color_scheme
        
        # 布局参数
        self.label_width = 80
        self.label_height = 40
        self.colorbar_width = 40
        
        # 数据
        self.data: List[List[float]] = []
        self.variables: List[str] = []
        self.timestamps: List[str] = []
        self.anomaly_mask: List[List[bool]] = []
        
        # 颜色映射
        self.color_scale: List[str] = self.COLOR_SCHEMES.get(
            color_scheme, self.COLOR_SCHEMES[HeatmapColorScheme.BLUES]
        )
    
    def set_data(
        self,
        data: List[List[float]],
        variables: List[str],
        timestamps: List[str],
        anomaly_mask: Optional[List[List[bool]]] = None
    ) -> None:
        """
        设置热力图数据
        
        Args:
            data: 2D数据矩阵 [time_steps][variables]
            variables: 变量名列表
            timestamps: 时间戳标签
            anomaly_mask: 异常标记矩阵
        """
        self.data = data
        self.variables = variables
        self.timestamps = timestamps
        self.anomaly_mask = anomaly_mask or [[False] * len(variables) for _ in range(len(data))]
        
        # 确保维度一致
        n_times = len(data)
        n_vars = len(variables)
        self.anomaly_mask = [
            row[:n_vars] + [False] * (n_vars - len(row))
            for row in self.anomaly_mask
        ]
        while len(self.anomaly_mask) < n_times:
            self.anomaly_mask.append([False] * n_vars)
    
    def plot(self, title: str = "预测演化热力图") -> str:
        """
        生成热力图SVG
        
        Args:
            title: 图表标题
            
        Returns:
            SVG格式的热力图
        """
        if not self.data or not self.variables:
            return self._empty_chart("无数据")
        
        n_times = len(self.data)
        n_vars = len(self.variables)
        
        # 计算尺寸
        plot_width = self.width - self.label_width - self.colorbar_width - 20
        plot_height = self.height - self.label_height - 20
        
        cell_width = plot_width / n_times
        cell_height = plot_height / n_vars
        
        # 计算归一化值
        all_values = [v for row in self.data for v in row if v is not None]
        if not all_values:
            return self._empty_chart("数据为空")
        
        v_min, v_max = min(all_values), max(all_values)
        v_range = v_max - v_min if v_max != v_min else 1
        
        # 构建SVG
        svg_parts = [
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}" viewBox="0 0 {self.width} {self.height}">',
            '<defs>',
            '<style>',
            '.cell:hover { stroke: #1f2937; stroke-width: 2; }',
            '.axis-label { font-family: system-ui, sans-serif; font-size: 11px; fill: #6b7280; }',
            '.title { font-family: system-ui, sans-serif; font-size: 14px; font-weight: 600; fill: #1f2937; }',
            '</style>',
            '</defs>'
        ]
        
        # 标题
        svg_parts.append(
            f'<text x="{self.width // 2}" y="20" text-anchor="middle" class="title">{self._escape(title)}</text>'
        )
        
        # 绘制热力图主体
        heatmap_x = self.label_width
        heatmap_y = self.label_height
        
        svg_parts.append(f'<g class="heatmap" transform="translate({heatmap_x}, {heatmap_y})">')
        
        for i in range(n_times):
            for j in range(n_vars):
                value = self.data[i][j] if j < len(self.data[i]) else 0
                if value is None:
                    continue
                
                # 归一化并获取颜色
                norm = (value - v_min) / v_range
                color = self._get_color(norm)
                
                x = i * cell_width
                y = j * cell_height
                
                # 正常单元格
                svg_parts.append(
                    f'<rect x="{x}" y="{y}" width="{cell_width - 1}" height="{cell_height - 1}" '
                    f'fill="{color}" class="cell">'
                    f'<title>时间: {self.timestamps[i] if i < len(self.timestamps) else i}\\n'
                    f'{self.variables[j]}: {value:.4f}</title>'
                    f'</rect>'
                )
                
                # 异常单元格标记
                if j < len(self.anomaly_mask[i]) and self.anomaly_mask[i][j]:
                    svg_parts.append(
                        f'<rect x="{x}" y="{y}" width="{cell_width - 1}" height="{cell_height - 1}" '
                        f'fill="none" stroke="#ef4444" stroke-width="2"/>'
                    )
        
        svg_parts.append('</g>')
        
        # Y轴标签（变量名）
        for j, var in enumerate(self.variables):
            y = self.label_height + j * cell_height + cell_height / 2 + 4
            svg_parts.append(
                f'<text x="{self.label_width - 10}" y="{y}" text-anchor="end" class="axis-label">'
                f'{self._escape(var[:10])}</text>'
            )
        
        # X轴标签（时间）
        n_labels = min(6, n_times)
        for k in range(n_labels):
            i = k * (n_times - 1) // (n_labels - 1) if n_labels > 1 else 0
            x = self.label_width + i * cell_width + cell_width / 2
            y = self.label_height + n_vars * cell_height + 15
            label = self.timestamps[i] if i < len(self.timestamps) else f"T{i}"
            svg_parts.append(
                f'<text x="{x}" y="{y}" text-anchor="middle" class="axis-label">'
                f'{self._escape(label)}</text>'
            )
        
        # 颜色条
        colorbar_x = self.width - self.colorbar_width - 10
        colorbar_height = self.height - 60
        step = colorbar_height / len(self.color_scale)
        
        for k, color in enumerate(self.color_scale):
            y = 30 + k * step
            svg_parts.append(
                f'<rect x="{colorbar_x}" y="{y}" width="{self.colorbar_width}" height="{step + 1}" fill="{color}"/>'
            )
        
        # 颜色条标签
        svg_parts.append(
            f'<text x="{colorbar_x + self.colorbar_width / 2}" y="20" text-anchor="middle" class="axis-label">'
            f'{v_max:.2f}</text>'
        )
        svg_parts.append(
            f'<text x="{colorbar_x + self.colorbar_width / 2}" y="{30 + colorbar_height + 15}" text-anchor="middle" class="axis-label">'
            f'{v_min:.2f}</text>'
        )
        
        svg_parts.append('</svg>')
        return '\n'.join(svg_parts)
    
    def _get_color(self, normalized_value: float) -> str:
        """根据归一化值获取颜色"""
        normalized_value = max(0, min(1, normalized_value))
        index = int(normalized_value * (len(self.color_scale) - 1))
        return self.color_scale[index]
    
    def _escape(self, text: str) -> str:
        """转义XML特殊字符"""
        return (text
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'))
    
    def _empty_chart(self, message: str) -> str:
        """空图表"""
        return f'''
        <svg xmlns="http://www.w3.org/2000/svg" width="{self.width}" height="{self.height}">
            <rect width="100%" height="100%" fill="#ffffff"/>
            <text x="{self.width // 2}" y="{self.height // 2}" text-anchor="middle" 
                  font-family="system-ui" font-size="14" fill="#9ca3af">
                {self._escape(message)}
            </text>
        </svg>
        '''
    
    def export_data(self) -> Dict:
        """导出数据为字典"""
        return {
            'variables': self.variables,
            'timestamps': self.timestamps,
            'data': self.data,
            'anomaly_mask': self.anomaly_mask,
            'color_scheme': self.color_scheme.value
        }


def create_demo_heatmap() -> Tuple[EvolutionHeatmap, List[List[float]]]:
    """创建演示热力图数据"""
    import math
    
    n_times = 24  # 24小时
    n_vars = 5     # 5个变量
    
    # 生成演示数据
    data = []
    for i in range(n_times):
        row = []
        for j in range(n_vars):
            # 基础值 + 周期性变化 + 噪声
            base = 50 + j * 10
            cycle = math.sin(i * 0.3 + j * 0.5) * 10
            noise = (hash(str(i) + str(j)) % 100) / 50 - 1
            value = base + cycle + noise
            
            # 添加一些异常
            if 10 < i < 15 and j == 2:
                value += 30  # 某区域异常高
            if 18 < i < 20 and j == 0:
                value -= 20  # 某区域异常低
            
            row.append(value)
        data.append(row)
    
    # 生成时间标签
    timestamps = [f"{h}:00" for h in range(n_times)]
    
    # 生成变量名
    variables = ["频率(Hz)", "电压(pu)", "功率(MW)", "相角(°)", "频率变化率"]
    
    # 创建异常掩码
    anomaly_mask = [[False] * n_vars for _ in range(n_times)]
    for i in range(10, 15):
        anomaly_mask[i][2] = True
    for i in range(18, 20):
        anomaly_mask[i][0] = True
    
    # 创建热力图
    heatmap = EvolutionHeatmap(
        width=700,
        height=400,
        color_scheme=HeatmapColorScheme.VIRIDIS
    )
    heatmap.set_data(data, variables, timestamps, anomaly_mask)
    
    return heatmap, data
