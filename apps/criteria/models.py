from django.db import models


class EvaluationCriterion(models.Model):
    key = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=255)
    weight_percent = models.PositiveSmallIntegerField()
    order = models.PositiveSmallIntegerField()
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["order"]
        constraints = [
            models.CheckConstraint(check=models.Q(weight_percent__in=[5, 10]), name="ck_criterion_weight_5_or_10"),
        ]
        indexes = [models.Index(fields=["is_active", "order"])]

    def __str__(self) -> str:
        return f"{self.order}. {self.name} ({self.weight_percent}%)"
