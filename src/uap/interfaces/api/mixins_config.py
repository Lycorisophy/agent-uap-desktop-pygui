"""运行时配置读写。"""

from __future__ import annotations

import copy
from typing import Any

from uap.config import local_override_config_path, llm_provider_presets

from uap.interfaces.api._log import _LOG


def _redact_config_updates_for_log(updates: dict[str, Any]) -> dict[str, Any]:
    """日志用：避免把 llm.api_key 明文写入日志。"""
    if not isinstance(updates, dict):
        return {}
    out = copy.deepcopy(updates)
    llm = out.get("llm")
    if isinstance(llm, dict) and llm.get("api_key"):
        raw = llm["api_key"]
        llm["api_key"] = f"<redacted len={len(str(raw))}>"
    return out


class ConfigApiMixin:
    def get_config(self) -> dict:
        """Get current config（与前端字段 prediction_defaults 对齐）。"""
        override_path = local_override_config_path()
        pred = self.config.prediction
        emb = self.config.embedding
        _LOG.info(
            "[API] get_config: local_override_exists=%s path=%s llm=%s/%s embed=%s",
            override_path.is_file(),
            override_path,
            self.config.llm.provider,
            self.config.llm.model,
            emb.model,
        )
        llm_dump = self.config.llm.model_dump()
        llm_dump["api_key"] = ""
        llm_dump["api_key_set"] = bool(self.config.llm.api_key)
        payload = {
            "prediction_defaults": {
                "frequency_sec": pred.default_frequency_sec,
                "horizon_sec": pred.default_horizon_sec,
            },
            "llm": llm_dump,
            "llm_presets": llm_provider_presets(),
            "embedding": emb.model_dump(),
            "storage": self.config.storage.model_dump(),
            "config_path": str(override_path),
        }
        _LOG.info(
            "[API] get_config: return prediction freq=%s horizon=%s api_key_set=%s milvus_lite_path=%s",
            pred.default_frequency_sec,
            pred.default_horizon_sec,
            llm_dump.get("api_key_set"),
            (self.config.storage.milvus_lite_path or "")[:80] or "(empty)",
        )
        return payload

    def update_config(self, config_updates: dict) -> dict:
        """
        更新内存配置并写入 ``%USERPROFILE%/.uap/uap.local.yaml``。

        与界面字段对齐：必须写入 ``llm.provider`` 等，否则重启后会回落到默认提供商。
        """
        try:
            _LOG.info(
                "[API] update_config called (redacted): %s",
                _redact_config_updates_for_log(config_updates),
            )

            if "llm" in config_updates:
                from uap.config import LLMConfig

                llm_data = dict(config_updates["llm"])
                llm_data.pop("api_key_set", None)
                merged = self.config.llm.model_dump()
                for k, v in llm_data.items():
                    if k == "api_key" and v == "":
                        merged["api_key"] = None
                    elif v is not None:
                        merged[k] = v
                self.config.llm = LLMConfig.model_validate(merged)

            if "embedding" in config_updates:
                from uap.config import EmbeddingConfig

                emb_data = dict(config_updates["embedding"])
                merged_emb = self.config.embedding.model_dump()
                for k, v in emb_data.items():
                    if v is not None:
                        merged_emb[k] = v
                self.config.embedding = EmbeddingConfig.model_validate(merged_emb)

            if "storage" in config_updates:
                from uap.config import StorageConfig

                st_data = dict(config_updates["storage"])
                merged_st = self.config.storage.model_dump()
                for k, v in st_data.items():
                    if v is not None:
                        merged_st[k] = v
                self.config.storage = StorageConfig.model_validate(merged_st)

            if "prediction_defaults" in config_updates:
                pd = config_updates["prediction_defaults"]
                freq = pd.get("frequency_sec") or pd.get("defaultFrequency") or 3600
                horizon = pd.get("horizon_sec") or pd.get("defaultHorizon") or 259200
                self.config.prediction.default_frequency_sec = int(freq)
                self.config.prediction.default_horizon_sec = int(horizon)

            from uap.config import local_override_config_path, load_config_file, _deep_merge

            config_path = local_override_config_path()
            config_path.parent.mkdir(parents=True, exist_ok=True)

            existing: dict = {}
            if config_path.is_file():
                try:
                    raw = load_config_file(config_path)
                    if isinstance(raw, dict):
                        existing = raw
                except Exception:
                    existing = {}

            merged = _deep_merge(existing, self.config.model_dump(mode="json"))

            import yaml

            _LOG.info(
                "[API] update_config: writing yaml path=%s llm=%s/%s embed=%s pred_freq=%s pred_horizon=%s",
                config_path,
                self.config.llm.provider,
                self.config.llm.model,
                self.config.embedding.model,
                self.config.prediction.default_frequency_sec,
                self.config.prediction.default_horizon_sec,
            )
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    merged,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )

            self.project_service.refresh_extractor()
            if hasattr(self, "knowledge_service"):
                self.knowledge_service.reset_clients()

            _LOG.info(
                "[API] Config saved to: %s, provider=%s, model=%s",
                config_path,
                self.config.llm.provider,
                self.config.llm.model,
            )
            return {
                "success": True,
                "message": "Config saved",
                "config_path": str(config_path),
                "config": self.config.model_dump(),
            }
        except Exception as e:
            _LOG.exception("[API] Failed to save config: %s", str(e))
            return {"success": False, "error": str(e)}
