from django.db import models


class MLModelRecord(models.Model):
    """Metadata for a trained ML model."""

    class Algorithm(models.TextChoices):
        XGBOOST = "xgboost", "XGBoost"
        RANDOM_FOREST = "random_forest", "Random Forest"

    algorithm = models.CharField(max_length=32, choices=Algorithm.choices)
    version = models.CharField(max_length=32, unique=True)
    model_path = models.CharField(
        max_length=255,
        help_text="Relative path to the .joblib file inside ml_models/",
    )
    metrics_json = models.JSONField(
        default=dict,
        help_text="Training metrics: MAE, R², RMSE, etc.",
    )
    feature_names = models.JSONField(
        default=list,
        help_text="Ordered list of feature names used during training",
    )
    is_active = models.BooleanField(default=False)
    trained_at = models.DateTimeField(auto_now_add=True)
    sample_count = models.PositiveIntegerField(
        default=0, help_text="Number of training samples used"
    )

    class Meta:
        ordering = ["-trained_at"]
        indexes = [models.Index(fields=["is_active", "algorithm"])]

    def __str__(self) -> str:
        return f"MLModel({self.algorithm}, {self.version}, active={self.is_active})"


class MLPrediction(models.Model):
    """Per-teacher-cycle prediction from a trained ML model."""

    teacher = models.ForeignKey(
        "teachers.Teacher", on_delete=models.CASCADE, related_name="ml_predictions"
    )
    cycle = models.ForeignKey(
        "cycles.EvaluationCycle", on_delete=models.CASCADE, related_name="ml_predictions"
    )
    ml_expected_score = models.DecimalField(max_digits=5, decimal_places=2)
    features_json = models.JSONField(
        default=dict, help_text="Feature values used for this prediction"
    )
    model_record = models.ForeignKey(
        MLModelRecord, on_delete=models.CASCADE, related_name="predictions"
    )
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["teacher", "cycle"], name="uq_ml_prediction_teacher_cycle"
            ),
            models.CheckConstraint(
                check=models.Q(ml_expected_score__gte=0, ml_expected_score__lte=100),
                name="ck_ml_expected_score_0_100",
            ),
        ]
        indexes = [models.Index(fields=["cycle", "computed_at"])]

    def __str__(self) -> str:
        return f"MLPrediction({self.teacher_id}, {self.cycle_id}) = {self.ml_expected_score}"
