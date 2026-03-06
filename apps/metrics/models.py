from django.db import models


class TeacherMetricSnapshot(models.Model):
    class ApprovalStatus(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"

    teacher = models.ForeignKey("teachers.Teacher", on_delete=models.CASCADE, related_name="metric_snapshots")
    cycle = models.ForeignKey("cycles.EvaluationCycle", on_delete=models.CASCADE, related_name="metric_snapshots")
    pd_hours = models.DecimalField(max_digits=7, decimal_places=2)
    training_hours = models.DecimalField(max_digits=7, decimal_places=2)
    created_by = models.ForeignKey("accounts.User", null=True, on_delete=models.SET_NULL, related_name="metric_snapshots_created")
    approval_status = models.CharField(max_length=16, choices=ApprovalStatus.choices, default=ApprovalStatus.PENDING)
    approved_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="metric_snapshots_approved"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["teacher", "cycle"], name="uq_metric_teacher_cycle"),
            models.CheckConstraint(check=models.Q(pd_hours__gte=0), name="ck_pd_hours_non_negative"),
            models.CheckConstraint(check=models.Q(training_hours__gte=0), name="ck_training_hours_non_negative"),
        ]
        indexes = [
            models.Index(fields=["teacher", "cycle"]),
            models.Index(fields=["cycle", "created_at"]),
            models.Index(fields=["approval_status", "cycle"]),
        ]

    def __str__(self) -> str:
        return f"Metrics({self.teacher_id}, {self.cycle_id})"
