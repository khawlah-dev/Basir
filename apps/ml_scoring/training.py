"""Training service for ML scoring models.

Trains XGBoost or Random Forest models on historical evaluation data
and persists the trained model to disk + metadata to DB.
"""

import logging
import os
from datetime import datetime

import joblib
import numpy as np
from django.conf import settings
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from .features import build_training_dataset
from .models import MLModelRecord

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.join(settings.BASE_DIR, "ml_models")


def _ensure_models_dir():
    os.makedirs(MODELS_DIR, exist_ok=True)


def train_and_evaluate(
    algorithm: str = "xgboost",
    test_size: float = 0.2,
    random_state: int = 42,
) -> MLModelRecord:
    """Train an ML model and save it.

    Args:
        algorithm: 'xgboost' or 'random_forest'
        test_size: Fraction of data for testing
        random_state: Random seed for reproducibility

    Returns:
        MLModelRecord with training metrics
    """
    _ensure_models_dir()

    df = build_training_dataset()
    if df.empty or len(df) < 5:
        raise ValueError(
            f"Not enough training data ({len(df)} rows). "
            "Need at least 5 finalized evaluations with complete data."
        )

    feature_cols = [c for c in df.columns if c != "target"]
    X = df[feature_cols].values
    y = df["target"].values

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )

    if algorithm == "xgboost":
        from xgboost import XGBRegressor

        model = XGBRegressor(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            random_state=random_state,
            objective="reg:squarederror",
        )
    elif algorithm == "random_forest":
        model = RandomForestRegressor(
            n_estimators=200,
            max_depth=10,
            random_state=random_state,
            n_jobs=-1,
        )
    else:
        raise ValueError(f"Unknown algorithm: {algorithm}. Use 'xgboost' or 'random_forest'.")

    logger.info("Training %s model on %d samples...", algorithm, len(X_train))
    model.fit(X_train, y_train)

    # Evaluate
    y_pred = model.predict(X_test)
    # Clamp predictions to 0–100
    y_pred = np.clip(y_pred, 0, 100)

    mae = mean_absolute_error(y_test, y_pred)
    rmse = float(np.sqrt(mean_squared_error(y_test, y_pred)))
    r2 = r2_score(y_test, y_pred) if len(y_test) > 1 else 0.0

    metrics = {
        "mae": round(mae, 4),
        "rmse": round(rmse, 4),
        "r2": round(r2, 4),
        "train_samples": len(X_train),
        "test_samples": len(X_test),
        "total_samples": len(df),
    }

    logger.info(
        "Model trained — MAE: %.4f, RMSE: %.4f, R²: %.4f",
        mae, rmse, r2,
    )

    # Save model
    version = f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}_{algorithm}"
    filename = f"model_{version}.joblib"
    filepath = os.path.join(MODELS_DIR, filename)
    joblib.dump(model, filepath)
    logger.info("Model saved to %s", filepath)

    # Deactivate other models of same algorithm
    MLModelRecord.objects.filter(
        algorithm=algorithm, is_active=True
    ).update(is_active=False)

    # Create record
    record = MLModelRecord.objects.create(
        algorithm=algorithm,
        version=version,
        model_path=filename,
        metrics_json=metrics,
        feature_names=feature_cols,
        is_active=True,
        sample_count=len(df),
    )

    logger.info("MLModelRecord created: %s", record)
    return record
