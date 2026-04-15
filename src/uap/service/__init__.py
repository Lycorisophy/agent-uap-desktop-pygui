"""兼容包：应用服务已迁至 ``uap.application``。"""

from uap.application.project_service import ProjectService
from uap.application.prediction_service import PredictionService

__all__ = ["ProjectService", "PredictionService"]
