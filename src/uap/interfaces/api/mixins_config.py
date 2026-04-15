"""运行时配置读写。"""

from __future__ import annotations

from uap.config import local_override_config_path

from uap.interfaces.api._log import _LOG


class ConfigApiMixin:
    def get_config(self) -> dict:
        """Get current config（与前端字段 prediction_defaults 对齐）。"""
        pred = self.config.prediction
        return {
            "prediction_defaults": {
                "frequency_sec": pred.default_frequency_sec,
                "horizon_sec": pred.default_horizon_sec,
            },
            "llm": self.config.llm.model_dump(),
            "storage": self.config.storage.model_dump(),
            "config_path": str(local_override_config_path()),
        }

    def update_config(self, config_updates: dict) -> dict:
        """
        更新内存配置并写入 ``%USERPROFILE%/.uap/uap.local.yaml``。

        与界面字段对齐：必须写入 ``llm.provider`` 等，否则重启后会回落到默认提供商。
        """
        try:
            _LOG.info("[API] update_config called: %s", config_updates)

            if "llm" in config_updates:
                llm_data = config_updates["llm"]
                if "provider" in llm_data and llm_data["provider"]:
                    self.config.llm.provider = llm_data["provider"]
                if "model" in llm_data:
                    self.config.llm.model = llm_data["model"]
                if "base_url" in llm_data:
                    self.config.llm.base_url = llm_data["base_url"]
                if llm_data.get("api_key"):
                    self.config.llm.api_key = llm_data["api_key"]
                if "temperature" in llm_data and llm_data["temperature"] is not None:
                    self.config.llm.temperature = float(llm_data["temperature"])
                if "max_tokens" in llm_data and llm_data["max_tokens"] is not None:
                    self.config.llm.max_tokens = int(llm_data["max_tokens"])
                if "api_mode" in llm_data and llm_data["api_mode"]:
                    self.config.llm.api_mode = llm_data["api_mode"]

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

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(
                    merged,
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                    sort_keys=False,
                )

            self.project_service.refresh_extractor()

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
