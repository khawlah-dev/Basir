from django.db import models


class ComparisonResult(models.Model):
    class DeviationLevel(models.TextChoices):
        NORMAL = "NORMAL", "Normal"
        REVIEW = "REVIEW", "Review"
        HIGH_RISK = "HIGH_RISK", "High Risk"

    teacher = models.ForeignKey("teachers.Teacher", on_delete=models.CASCADE, related_name="comparison_results")
    cycle = models.ForeignKey("cycles.EvaluationCycle", on_delete=models.CASCADE, related_name="comparison_results")
    manager_total = models.DecimalField(max_digits=5, decimal_places=2)
    objective_total = models.DecimalField(max_digits=5, decimal_places=2)
    deviation = models.DecimalField(max_digits=6, decimal_places=2)
    deviation_level = models.CharField(max_length=16, choices=DeviationLevel.choices)
    created_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["teacher", "cycle"], name="uq_cmp_teacher_cycle")]
        indexes = [models.Index(fields=["deviation_level", "created_at"])]
