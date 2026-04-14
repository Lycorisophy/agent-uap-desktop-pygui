# -*- coding: utf-8 -*-
"""更新报告：添加原子技能分类体系"""

with open(r'C:\project\python\agent-uap-desktop-pygui\复杂系统未来势态量化预测统一智能体可行性研究与总体实施方案报告.md', 'r', encoding='utf-8') as f:
    content = f.read()

# 插入位置：在 4.7.6 预置技能模板 表格之后，4.7.7 技能执行与反馈 之前
insert_after = """### 4.7.7 技能执行与反馈"""

# 要插入的内容
new_section = """### 4.7.7 原子技能分类体系

为实现可复用、可组合的技能架构，系统建立了**原子技能分类体系**，将预测建模流程分解为6大类共22个原子技能。

#### 7.7.1 技能分类总览

| 类别 | 数量 | 说明 |
| :--- | :--- | :--- |
| **数据技能** | 3 | 数据获取、加载、转换 |
| **预处理技能** | 4 | 清洗、插值、归一化、重采样 |
| **特征技能** | 4 | 相空间重构、特征提取、排列熵、多尺度熵 |
| **模型技能** | 5 | Koopman、Monte Carlo、Neural ODE、PINN、Transformer |
| **后处理技能** | 3 | 不确定性量化、混沌检测、置信区间 |
| **可视化技能** | 3 | 相图、预测区间、演化热力图 |

#### 7.7.2 原子技能库详情

**数据技能（Data）**
| 技能ID | 名称 | 描述 |
|--------|------|------|
| `data_load_timeseries` | 时序数据加载 | 从CSV/JSON/HDF5加载时间序列数据 |
| `data_api_fetch` | API数据获取 | 从REST/GraphQL API获取实时数据 |
| `data_stream_subscribe` | 流数据订阅 | 订阅WebSocket/Kafka等数据流 |

**预处理技能（Preprocessing）**
| 技能ID | 名称 | 描述 |
|--------|------|------|
| `preprocess_clean` | 数据清洗 | 缺失值处理、异常值检测、噪声过滤 |
| `preprocess_interpolate` | 插值补全 | 线性/样条/拉格朗日插值 |
| `preprocess_normalize` | 归一化 | MinMax/Z-score/Robust归一化 |
| `preprocess_resample` | 重采样 | 升采样/降采样，时间对齐 |

**特征技能（Feature）**
| 技能ID | 名称 | 描述 |
|--------|------|------|
| `feature_delay_embed` | 延迟嵌入 | Takens定理相空间重构 |
| `feature_statistical` | 统计特征 | 均值、方差、偏度、峰度 |
| `feature_permutation_entropy` | 排列熵 | 量化时间序列复杂度 |
| `feature_multiscale_entropy` | 多尺度熵 | 多尺度样本熵分析 |

**模型技能（Model）**
| 技能ID | 名称 | 描述 |
|--------|------|------|
| `model_koopman` | Koopman算子 | 全局线性化，线性预测 |
| `model_monte_carlo` | Monte Carlo | 不确定性传播模拟 |
| `model_neural_ode` | 神经常微分方程 | 连续时间动力学学习 |
| `model_pinn` | 物理信息神经网络 | 守恒律约束学习 |
| `model_transformer` | Transformer预测 | 自注意力机制时序预测 |

**后处理技能（Postprocess）**
| 技能ID | 名称 | 描述 |
|--------|------|------|
| `postprocess_uncertainty` | 不确定性量化 | 预测区间/分布估计 |
| `postprocess_chaos_detect` | 混沌检测 | Lyapunov指数，最大可预测时长 |
| `postprocess_confidence` | 置信区间 | 误差传播/ bootstrap |

**可视化技能（Visualization）**
| 技能ID | 名称 | 描述 |
|--------|------|------|
| `viz_phase_portrait` | 相图绘制 | 二维/三维相空间可视化 |
| `viz_prediction_interval` | 预测区间图 | 概率带/置信区间可视化 |
| `viz_heatmap_evolution` | 演化热力图 | 多步预测动态演化 |

#### 7.7.3 技能链推荐（SkillChain）

针对不同任务类型，系统提供智能技能链推荐：

| 任务类型 | 推荐技能链 | 说明 |
| :--- | :--- | :--- |
| **短期预测** | data_load → preprocess → model_koopman → postprocess_uncertainty | 适用于周期性强、噪声低的数据 |
| **异常检测** | data_load → feature_permutation_entropy → postprocess_chaos_detect | 基于复杂度变化的异常识别 |
| **不确定性量化** | data_load → model_monte_carlo → postprocess_uncertainty → viz_prediction_interval | 概率预测与可视化 |
| **物理约束建模** | data_load → preprocess → model_pinn → postprocess_uncertainty | 守恒律约束的动力学建模 |
| **混沌系统预测** | data_load → feature_delay_embed → feature_permutation_entropy → model_neural_ode → postprocess_chaos_detect | 混沌边缘状态识别与预测 |

#### 7.7.4 技能状态机

```
                    ┌─────────────┐
                    │   draft     │ ← 新生成
                    └──────┬──────┘
                           │ 用户确认
                           ▼
                    ┌─────────────┐
         ┌──────────│  validated  │ ← 可用状态
         │          └──────┬──────┘
         │                 │ 首次执行成功
         ▼                 │
┌─────────────────┐         │
│   deprecated    │         ▼
│ (被新技能替代)   │  ┌─────────────┐
└─────────────────┘  │   active    │ ← 正式启用
                      └──────┬──────┘
                             │ ≥10次成功执行
                             ▼
                      ┌─────────────┐
                      │  optimized   │ ← 表现优异
                      └─────────────┘
```

### 4.7.8 技能执行与反馈"""

if insert_after in content:
    content = content.replace(insert_after, new_section)
    with open(r'C:\project\python\agent-uap-desktop-pygui\复杂系统未来势态量化预测统一智能体可行性研究与总体实施方案报告.md', 'w', encoding='utf-8') as f:
        f.write(content)
    print('报告已更新：添加原子技能分类体系')
else:
    print('插入点未找到')
