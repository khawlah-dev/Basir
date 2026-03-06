"""Prediction service for ML scoring.

Loads a trained model and generates score predictions for teachers.
"""

import logging
import os
from decimal import Decimal, ROUND_HALF_UP

import joblib
import numpy as np
from django.conf import settings

from .features import extract_features
from .models import MLModelRecord, MLPrediction

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.join(settings.BASE_DIR, "ml_models")

# Cache for loaded model to avoid re-reading from disk on every call
_model_cache: dict = {}


def _load_model(record: MLModelRecord):
    """Load model from disk with caching."""
    cache_key = record.version
    if cache_key not in _model_cache:
        filepath = os.path.join(MODELS_DIR, record.model_path)
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Model file not found: {filepath}")
        _model_cache[cache_key] = joblib.load(filepath)
        logger.info("Loaded ML model: %s", record.version)
    return _model_cache[cache_key]


def get_active_model() -> MLModelRecord:
    """Return the latest active ML model record."""
    record = MLModelRecord.objects.filter(is_active=True).order_by("-trained_at").first()
    if record is None:
        raise RuntimeError(
            "No active ML model found. Run 'python manage.py train_ml_model' first."
        )
    return record


def predict_score(*, teacher, cycle, model_record: MLModelRecord | None = None) -> MLPrediction:
    """Generate an ML prediction for a teacher/cycle pair.

    Args:
        teacher: Teacher instance
        cycle: EvaluationCycle instance
        model_record: Optional specific model to use (defaults to active model)

    Returns:
        MLPrediction instance (created or updated)
    """
    record = model_record or get_active_model()
    model = _load_model(record)

    features = extract_features(teacher=teacher, cycle=cycle)

    # Build feature vector in the same order as training
    feature_vector = [features.get(name, 0.0) for name in record.feature_names]
    X = np.array([feature_vector])

    raw_score = float(model.predict(X)[0])
    # Clamp to 0–100
    clamped = max(0.0, min(100.0, raw_score))

    ml_score = Decimal(str(clamped)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    prediction, _ = MLPrediction.objects.update_or_create(
        teacher=teacher,
        cycle=cycle,
        defaults={
            "ml_expected_score": ml_score,
            "features_json": features,
            "model_record": record,
        },
    )

    logger.info(
        "ML prediction for teacher %s cycle %s: score=%s (model=%s)",
        teacher.id, cycle.id, ml_score, record.version,
    )
    return prediction


def get_or_predict(*, teacher, cycle, force: bool = False) -> MLPrediction:
    """Return cached prediction or compute a new one."""
    if not force:
        try:
            return MLPrediction.objects.get(teacher=teacher, cycle=cycle)
        except MLPrediction.DoesNotExist:
            pass
    return predict_score(teacher=teacher, cycle=cycle)
