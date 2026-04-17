# 领域数据与 CSV 建模衔接

面向「天气、销量」等时序/表格类项目：在项目工作区内放置原始数据，建模对话中可通过技能 **`data_load_csv`** 加载（参数见 `atomic_skills` 中 `file_path`、`separator`、`encoding`）。

## 推荐目录结构

在**项目文件夹**下（与桌面端「项目工作区」一致）建议：

```
<project_root>/
  data/
    raw/           # 原始导出，尽量只读
    processed/     # 清洗、对齐后的中间结果（可选）
  docs/            # 业务说明、字段字典（可选）
```

将 CSV 放在 `data/raw/` 或 `data/processed/` 下，便于与用户说明「数据在项目内何处」。

## 示例 CSV（天气类）

首行表头，时间列 + 若干观测列；日期格式尽量统一（如 ISO `2024-01-01` 或 `2024-01-01T12:00:00`）。

```csv
timestamp,temperature_c,humidity_pct
2024-01-01,12.5,65
2024-01-02,11.0,70
```

建模时可将 `temperature_c`、`humidity_pct` 等声明为变量，并在约束中描述物理关系（由对话与 `extract_model` 等技能完成）。

## 示例 CSV（销量类）

```csv
date,sku,units_sold,revenue
2024-01-01,A001,120,3600.00
2024-01-01,B002,45,900.00
```

可按 SKU 拆成多条时间序列，或在模型中把 `sku` 作为分类维度（取决于业务与后续预测管线）。

## 与 `data_load_csv` 的衔接

- **`file_path`**：相对于项目根的路径，例如 `data/raw/weather.csv`（具体以运行时工作目录解析为准；若工具要求绝对路径，请放在项目目录下并传完整路径）。
- **`separator`**：默认 `,`；若使用制表符分隔，设为 `\t`。
- **`encoding`**：中文 Windows 导出常为 `gbk`，UTF-8 数据用 `utf-8`。

## 向导文案（可选）

向用户说明时可采用：

> 请将 CSV 放入本项目的 `data/raw/`，首行列名建议为英文或拼音以便与变量名对应；在建模对话中说明文件路径与列含义，代理将协助加载与变量定义。

---

*与 [MODELING_DELIVERY_PLAN.md](MODELING_DELIVERY_PLAN.md) 选做 A.2 对齐。*
