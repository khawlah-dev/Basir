from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models


class ObjectiveScoringPolicy(models.Model):
    version = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=False)
    normalization_method = models.CharField(max_length=32, default="CAPPED_LINEAR_V1")
    pd_weight = models.DecimalField(max_digits=4, decimal_places=2)
    training_weight = models.DecimalField(max_digits=4, decimal_places=2)
    pd_target_hours = models.DecimalField(max_digits=7, decimal_places=2)
    pd_max_hours = models.DecimalField(max_digits=7, decimal_places=2)
    training_target_hours = models.DecimalField(max_digits=7, decimal_places=2)
    training_max_hours = models.DecimalField(max_digits=7, decimal_places=2)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=models.Q(pd_weight__gte=0, pd_weight__lte=1), name="ck_pd_weight_range"),
            models.CheckConstraint(check=models.Q(training_weight__gte=0, training_weight__lte=1), name="ck_training_weight_range"),
            models.CheckConstraint(check=models.Q(pd_max_hours__gt=models.F("pd_target_hours")), name="ck_pd_cap_gt_target"),
            models.CheckConstraint(
                check=models.Q(training_max_hours__gt=models.F("training_target_hours")),
                name="ck_training_cap_gt_target",
            ),
        ]
        indexes = [models.Index(fields=["is_active", "effective_from"])]

    def clean(self) -> None:
        total = Decimal(self.pd_weight) + Decimal(self.training_weight)
        if total != Decimal("1.00"):
            raise ValidationError("pd_weight + training_weight must equal 1.00")

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)


class ObjectiveScore(models.Model):
    teacher = models.ForeignKey("teachers.Teacher", on_delete=models.CASCADE, related_name="objective_scores")
    cycle = models.ForeignKey("cycles.EvaluationCycle", on_delete=models.CASCADE, related_name="objective_scores")
    objective_total = models.DecimalField(max_digits=5, decimal_places=2)
    breakdown_json = models.JSONField(default=dict)
    policy_version = models.CharField(max_length=20)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["teacher", "cycle"], name="uq_objective_teacher_cycle"),
            models.CheckConstraint(check=models.Q(objective_total__gte=0, objective_total__lte=100), name="ck_objective_total_0_100"),
        ]
        indexes = [models.Index(fields=["cycle", "policy_version"])]
