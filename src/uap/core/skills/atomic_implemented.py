"""
建模路径「已实现」原子技能：注册子集 + 执行器实现。

全量元数据仍在 ``atomic_skills.get_atomic_skills_library``；本模块仅对
``MODELING_ATOMIC_SKILL_IDS`` 构造 ``AtomicSkill`` 并 ``set_executor``。
"""

from __future__ import annotations

import csv
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np

from uap.core.skills.atomic_skills import AtomicSkill, get_atomic_skills_library

_LOG = logging.getLogger("uap.core.skills.atomic_implemented")

MAX_ATOMIC_FILE_BYTES = 8 * 1024 * 1024
PREVIEW_MAX_ROWS = 15
PREVIEW_MAX_COLS = 50
OBSERVATION_MAX_CHARS = 8000
_MC_MAX_PATHS = 500
_MC_MAX_STEPS = 2000


MODELING_ATOMIC_SKILL_IDS: frozenset[str] = frozenset(
    {
        "data_load_csv",
        "data_load_json",
        "preprocess_missing",
        "preprocess_normalize",
        "preprocess_resample",
        "feature_derivative",
        "model_monte_carlo",
    }
)


def _truncate(s: str, n: int = OBSERVATION_MAX_CHARS) -> str:
    s = s or ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _resolve_path_under_workspace(file_path: str, workspace: Optional[str]) -> Path:
    raw = (file_path or "").strip()
    if not raw:
        raise ValueError("file_path 为空")
    p = Path(raw)
    if not workspace or not str(workspace).strip():
        if p.is_absolute():
            raise ValueError("未配置 project_workspace，禁止使用绝对路径")
        base = Path.cwd().resolve()
        cand = (base / raw).resolve()
    else:
        base = Path(str(workspace).strip()).expanduser().resolve()
        if not base.is_dir():
            raise ValueError(f"project_workspace 不是目录: {base}")
        cand = (p if p.is_absolute() else (base / raw)).resolve()
    try:
        cand.relative_to(base)
    except ValueError as e:
        raise ValueError("路径必须位于 project_workspace 之下") from e
    return cand


def _to_float_matrix(data: Any, *, label: str = "data") -> np.ndarray:
    if data is None:
        raise ValueError(f"{label} 不能为空")
    if isinstance(data, np.ndarray):
        arr = np.asarray(data, dtype=float)
    elif isinstance(data, list):
        if not data:
            raise ValueError(f"{label} 为空列表")
        arr = np.asarray(data, dtype=float)
    else:
        raise ValueError(f"{label} 须为二维数组（list of list）")
    if arr.ndim != 2:
        raise ValueError(f"{label} 须为二维数组，当前维度={arr.ndim}")
    if arr.size == 0:
        raise ValueError(f"{label} 无元素")
    return arr


def _exec_data_load_csv(skill: AtomicSkill, **kwargs: Any) -> dict[str, Any]:
    file_path = str(kwargs.get("file_path") or "").strip()
    workspace = (kwargs.get("project_workspace") or "").strip() or None
    sep = (kwargs.get("separator") or ",")[:8] or ","
    enc = (kwargs.get("encoding") or "utf-8").strip() or "utf-8"
    try:
        path = _resolve_path_under_workspace(file_path, workspace)
    except ValueError as e:
        return {"error": str(e)}
    if not path.is_file():
        return {"error": f"文件不存在: {path}"}
    size = path.stat().st_size
    if size > MAX_ATOMIC_FILE_BYTES:
        return {"error": f"文件过大（>{MAX_ATOMIC_FILE_BYTES} 字节）"}
    text = path.read_bytes().decode(enc, errors="replace")
    sample = text[: min(len(text), MAX_ATOMIC_FILE_BYTES)]
    reader = csv.reader(sample.splitlines(), delimiter=sep)
    rows: list[list[str]] = []
    for i, row in enumerate(reader):
        if i >= PREVIEW_MAX_ROWS + 1:
            break
        rows.append(row[:PREVIEW_MAX_COLS])
    n_preview = len(rows)
    total_lines = text.count("\n") + (1 if text and not text.endswith("\n") else 0)
    header = rows[0] if rows else []
    obs = (
        f"已读取 CSV（编码={enc}, 分隔符={repr(sep)}）\n"
        f"path={path}\n"
        f"约 {total_lines} 行（预览前 {n_preview} 行）\n"
        f"列名(预览首行): {header}\n"
        f"预览行: {json.dumps(rows[1:PREVIEW_MAX_ROWS], ensure_ascii=False)[:2000]}"
    )
    return {"observation": _truncate(obs)}


def _exec_data_load_json(skill: AtomicSkill, **kwargs: Any) -> dict[str, Any]:
    file_path = str(kwargs.get("source") or kwargs.get("file_path") or "").strip()
    workspace = (kwargs.get("project_workspace") or "").strip() or None
    try:
        path = _resolve_path_under_workspace(file_path, workspace)
    except ValueError as e:
        return {"error": str(e)}
    if not path.is_file():
        return {"error": f"文件不存在: {path}"}
    size = path.stat().st_size
    if size > MAX_ATOMIC_FILE_BYTES:
        return {"error": f"文件过大（>{MAX_ATOMIC_FILE_BYTES} 字节）"}
    raw = path.read_text(encoding="utf-8", errors="replace")
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        return {"error": f"JSON 解析失败: {e}"}
    if isinstance(obj, dict):
        keys = list(obj.keys())[:40]
        parts = [f"顶层键: {keys}"]
        for k in keys[:10]:
            v = obj[k]
            if isinstance(v, list):
                parts.append(f"  {k}: list 长度={len(v)}")
            elif isinstance(v, dict):
                parts.append(f"  {k}: dict 键数={len(v)}")
            else:
                parts.append(f"  {k}: {type(v).__name__}")
        obs = f"已读取 JSON: {path}\n" + "\n".join(parts)
    elif isinstance(obj, list):
        obs = f"已读取 JSON 数组: {path}，长度={len(obj)}，首元素类型={type(obj[0]).__name__ if obj else 'n/a'}"
    else:
        obs = f"已读取 JSON 标量: {path}，类型={type(obj).__name__}"
    return {"observation": _truncate(obs)}


def _fill_column_mean(col: np.ndarray) -> np.ndarray:
    x = col.astype(float, copy=True)
    m = np.nanmean(x)
    x[np.isnan(x)] = m if not np.isnan(m) else 0.0
    return x


def _fill_column_forward(col: np.ndarray) -> np.ndarray:
    x = col.astype(float, copy=True)
    mask = np.isnan(x)
    if not mask.any():
        return x
    idx = np.where(~mask, np.arange(len(x)), 0)
    np.maximum.accumulate(idx, out=idx)
    return x[idx]


def _fill_column_backward(col: np.ndarray) -> np.ndarray:
    return _fill_column_forward(col[::-1])[::-1]


def _fill_column_linear(col: np.ndarray) -> np.ndarray:
    x = col.astype(float, copy=True)
    n = len(x)
    idx = np.arange(n)
    mask = ~np.isnan(x)
    if mask.sum() < 2:
        return _fill_column_mean(col)
    x[~mask] = np.interp(idx[~mask], idx[mask], x[mask])
    return x


def _exec_preprocess_missing(skill: AtomicSkill, **kwargs: Any) -> dict[str, Any]:
    data = _to_float_matrix(kwargs.get("data"), label="data")
    method = str(kwargs.get("method") or "mean").strip().lower()
    out = np.empty_like(data)
    for j in range(data.shape[1]):
        col = data[:, j].copy()
        if method == "mean":
            out[:, j] = _fill_column_mean(col)
        elif method == "forward":
            out[:, j] = _fill_column_forward(col)
        elif method == "backward":
            out[:, j] = _fill_column_backward(col)
        elif method in ("linear", "spline"):
            out[:, j] = _fill_column_linear(col)
        else:
            return {"error": f"不支持的 method: {method}"}
    preview = out[: min(5, out.shape[0]), : min(8, out.shape[1])]
    obs = (
        f"缺失值处理 method={method}，形状={out.shape}\n"
        f"预览(前5x8): {json.dumps(preview.tolist(), ensure_ascii=False)}"
    )
    return {"observation": _truncate(obs), "metadata": {}}


def _exec_preprocess_normalize(skill: AtomicSkill, **kwargs: Any) -> dict[str, Any]:
    data = _to_float_matrix(kwargs.get("data"), label="data")
    method = str(kwargs.get("method") or "zscore").strip().lower()
    out = np.empty_like(data)
    for j in range(data.shape[1]):
        col = data[:, j].astype(float)
        if method == "zscore":
            mu, sig = float(np.mean(col)), float(np.std(col))
            sig = sig if sig > 1e-12 else 1.0
            out[:, j] = (col - mu) / sig
        elif method == "minmax":
            lo, hi = float(np.min(col)), float(np.max(col))
            span = hi - lo
            out[:, j] = (col - lo) / span if span > 1e-12 else np.zeros_like(col)
        else:
            return {"error": f"不支持的 method: {method}"}
    preview = out[: min(5, out.shape[0]), : min(8, out.shape[1])]
    obs = f"标准化 method={method}，形状={out.shape}\n预览: {json.dumps(preview.tolist(), ensure_ascii=False)}"
    return {"observation": _truncate(obs)}


def _parse_n_target(frequency: str, fallback_len: int) -> int:
    s = str(frequency or "").strip()
    if s.isdigit():
        return max(2, int(s))
    m = re.match(r"^n\s*[:=]\s*(\d+)$", s, re.I)
    if m:
        return max(2, int(m.group(1)))
    return max(2, min(fallback_len * 2, 256))


def _exec_preprocess_resample(skill: AtomicSkill, **kwargs: Any) -> dict[str, Any]:
    data = _to_float_matrix(kwargs.get("data"), label="data")
    frequency = str(kwargs.get("frequency") or "")
    n_old = data.shape[0]
    n_new = _parse_n_target(frequency, n_old)
    n_new = min(n_new, 4096)
    old_x = np.linspace(0.0, 1.0, n_old)
    new_x = np.linspace(0.0, 1.0, n_new)
    out = np.empty((n_new, data.shape[1]), dtype=float)
    for j in range(data.shape[1]):
        out[:, j] = np.interp(new_x, old_x, data[:, j].astype(float))
    preview = out[: min(5, out.shape[0]), : min(8, out.shape[1])]
    obs = (
        f"重采样 {n_old}->{n_new} 点（frequency={frequency!r}）\n"
        f"预览: {json.dumps(preview.tolist(), ensure_ascii=False)}"
    )
    return {"observation": _truncate(obs)}


def _exec_feature_derivative(skill: AtomicSkill, **kwargs: Any) -> dict[str, Any]:
    data = _to_float_matrix(kwargs.get("data"), label="data")
    method = str(kwargs.get("method") or "finite_diff").strip().lower()
    if method not in ("finite_diff", "spline"):
        return {"error": f"不支持的 method: {method}"}
    d = np.diff(data.astype(float), axis=0)
    preview = d[: min(5, d.shape[0]), : min(8, d.shape[1])]
    obs = (
        f"数值差分 shape {data.shape} -> {d.shape} (method={method})\n"
        f"预览: {json.dumps(preview.tolist(), ensure_ascii=False)}"
    )
    return {"observation": _truncate(obs)}


def _exec_model_monte_carlo(skill: AtomicSkill, **kwargs: Any) -> dict[str, Any]:
    model = kwargs.get("model") or {}
    if not isinstance(model, dict):
        return {"error": "model 须为对象，且包含 initial_state 等字段"}
    initial = model.get("initial_state")
    if not isinstance(initial, dict) or not initial:
        return {"error": "model.initial_state 须为非空对象（变量名->数值）"}
    keys = list(initial.keys())
    vec0 = np.array([float(initial[k]) for k in keys], dtype=float)
    n_steps = int(model.get("n_steps") or 10)
    n_steps = max(1, min(n_steps, _MC_MAX_STEPS))
    step_noise = float(model.get("step_noise") or 0.05)
    step_noise = max(0.0, step_noise)
    n_paths = int(kwargs.get("num_samples") or 100)
    n_paths = max(1, min(n_paths, _MC_MAX_PATHS))
    rng = np.random.default_rng()
    finals: list[np.ndarray] = []
    for _ in range(n_paths):
        v = vec0.copy()
        for _t in range(n_steps):
            v = v + rng.normal(0.0, step_noise, size=v.shape)
        finals.append(v)
    stack = np.stack(finals, axis=0)
    mean = np.mean(stack, axis=0)
    std = np.std(stack, axis=0)
    lines = [
        f"简化随机游走 MC: keys={keys}, n_paths={n_paths}, n_steps={n_steps}, step_noise={step_noise}",
        "终点均值: " + json.dumps({keys[i]: float(mean[i]) for i in range(len(keys))}, ensure_ascii=False),
        "终点标准差: " + json.dumps({keys[i]: float(std[i]) for i in range(len(keys))}, ensure_ascii=False),
        "示例路径末点: " + json.dumps(stack[0].tolist(), ensure_ascii=False),
    ]
    return {"observation": _truncate("\n".join(lines))}


_EXECUTORS: dict[str, Callable[[AtomicSkill, Any], dict[str, Any]]] = {
    "data_load_csv": _exec_data_load_csv,
    "data_load_json": _exec_data_load_json,
    "preprocess_missing": _exec_preprocess_missing,
    "preprocess_normalize": _exec_preprocess_normalize,
    "preprocess_resample": _exec_preprocess_resample,
    "feature_derivative": _exec_feature_derivative,
    "model_monte_carlo": _exec_model_monte_carlo,
}


def build_modeling_atomic_registry() -> dict[str, AtomicSkill]:
    """仅包含已实现原子技能的注册表（供建模 ReAct/Plan 与默认 create_react_agent）。"""
    lib = get_atomic_skills_library()
    out: dict[str, AtomicSkill] = {}
    for sid in sorted(MODELING_ATOMIC_SKILL_IDS):
        meta = lib.get(sid)
        if meta is None:
            _LOG.warning("[atomic_implemented] Missing metadata for %s", sid)
            continue
        fn = _EXECUTORS.get(sid)
        if fn is None:
            _LOG.warning("[atomic_implemented] Missing executor for %s", sid)
            continue
        skill = AtomicSkill(meta)
        skill.set_executor(fn)
        out[sid] = skill
    return out
