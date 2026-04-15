"""运行时配置读写。"""

from __future__ import annotations

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
        }

    def update_config(self, config_updates: dict) -> dict:
        """Update config and persist to file"""
        try:
            _LOG.info("[API] update_config called: %s", config_updates)

            if "llm" in config_updates:
                llm_data = config_updates["llm"]
                if "model" in llm_data:
                    self.config.llm.model = llm_data["model"]
                if "base_url" in llm_data:
                    self.config.llm.base_url = llm_data["base_url"]
                if llm_data.get("api_key"):
                    self.config.llm.api_key = llm_data["api_key"]

            if "prediction_defaults" in config_updates:
                pd = config_updates["prediction_defaults"]
                freq = pd.get("frequency_sec") or pd.get("defaultFrequency") or 3600
                horizon = pd.get("horizon_sec") or pd.get("defaultHorizon") or 259200
                self.config.prediction.default_frequency_sec = int(freq)
                self.config.prediction.default_horizon_sec = int(horizon)

            from uap.config import local_override_config_path

            config_path = local_override_config_path()
            config_path.parent.mkdir(parents=True, exist_ok=True)
            import yaml

            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(
                    self.config.model_dump(mode="json"),
                    f,
                    allow_unicode=True,
                    default_flow_style=False,
                )

            self.project_service.refresh_extractor()

            _LOG.info(
                "[API] Config saved to: %s, model=%s",
                config_path,
                self.config.llm.model,
            )
            return {
                "success": True,
                "message": "Config saved",
                "config": self.config.model_dump(),
            }
        except Exception as e:
            _LOG.exception("[API] Failed to save config: %s", str(e))
            return {"success": False, "error": str(e)}
