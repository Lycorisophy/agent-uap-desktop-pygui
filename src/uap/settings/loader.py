"""配置加载、合并与本地覆盖写回。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

from uap.settings.models import LLMConfig, UapConfig

# 本地配置覆盖文件名
LOCAL_OVERRIDE_REL = Path(".uap") / "uap.local.yaml"


def local_override_config_path() -> Path:
    """界面保存的 LLM 等覆盖层路径"""
    return Path.home() / LOCAL_OVERRIDE_REL


def llm_provider_presets() -> dict[str, dict[str, str]]:
    """各提供商默认 base_url / 示例 model"""
    return {
        "ollama": {
            "base_url": "http://127.0.0.1:11434",
            "model": "llama3.2",
            "hint": "本地 Ollama",
        },
        "minimax": {
            "base_url": "https://api.minimax.io/v1",
            "model": "MiniMax-M2.7",
            "hint": (
                "MiniMax OpenAI 兼容；model 须与控制台一致（如 MiniMax-M2.7、MiniMax-M2.7-highspeed）。"
                "勿填「minimax 2.7」等带空格的展示名。旧域名 api.minimax.chat 若仍可用可改 base_url。"
            ),
        },
        "deepseek": {
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "hint": "DeepSeek",
        },
        "qwen": {
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": "qwen-turbo",
            "hint": "阿里云 DashScope",
        },
        "openai": {
            "base_url": "https://api.openai.com/v1",
            "model": "gpt-4o",
            "hint": "OpenAI API",
        },
        "doubao": {
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model": "ep-your-endpoint-id",
            "hint": "豆包/火山方舟：模型名常填推理接入点 Endpoint ID",
        },
        "kimi": {
            "base_url": "https://api.moonshot.cn/v1",
            "model": "moonshot-v1-8k",
            "hint": "Moonshot Kimi OpenAI 兼容接口",
        },
    }


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深度合并字典"""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def _default_dict() -> dict[str, Any]:
    """默认配置字典"""
    return UapConfig().model_dump()


def config_search_paths() -> list[Path]:
    """配置文件搜索路径"""
    paths = []
    env = os.environ.get("UAP_CONFIG", "").strip()
    if env:
        paths.append(Path(env).expanduser())
    paths.append(Path.cwd() / "uap.yaml")
    paths.append(Path.cwd() / "config" / "uap.yaml")
    home = Path.home()
    paths.append(home / ".uap" / "uap.yaml")
    return paths


def load_config_file(path: Path) -> dict[str, Any]:
    """加载单个配置文件"""
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"配置文件根节点必须是映射: {path}")
    return data


def load_config() -> UapConfig:
    """
    合并默认配置与首个命中的主 YAML，再合并 ~/.uap/uap.local.yaml
    """
    merged: dict[str, Any] = _default_dict()

    for p in config_search_paths():
        try:
            if p.is_file():
                merged = _deep_merge(merged, load_config_file(p))
                break
        except OSError:
            continue

    local = local_override_config_path()
    try:
        if local.is_file():
            merged = _deep_merge(merged, load_config_file(local))
    except OSError:
        pass

    return UapConfig.model_validate(merged)


def save_llm_local_yaml(llm: LLMConfig) -> Path:
    """将 llm 块写入 ~/.uap/uap.local.yaml"""
    path = local_override_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    try:
        if path.is_file():
            existing = load_config_file(path)
            if not isinstance(existing, dict):
                existing = {}
    except OSError:
        existing = {}

    existing["version"] = existing.get("version") or 1
    existing["llm"] = llm.model_dump(mode="json")

    text = yaml.safe_dump(
        existing,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    )
    path.write_text(text, encoding="utf-8")
    return path
