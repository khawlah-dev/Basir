from django.db import models


class Case(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        IN_REVIEW = "IN_REVIEW", "In Review"
        CLOSED = "CLOSED", "Closed"

    teacher = models.ForeignKey("teachers.Teacher", on_delete=models.CASCADE, related_name="cases")
    cycle = models.ForeignKey("cycles.EvaluationCycle", on_delete=models.CASCADE, related_name="cases")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.OPEN)
    opened_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="cases_opened")
    decision_note = models.TextField(blank=True, default="")
    closed_by = models.ForeignKey(
        "accounts.User", null=True, blank=True, on_delete=models.PROTECT, related_name="cases_closed"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["status", "opened_at"])]


class Flag(models.Model):
    class Severity(models.TextChoices):
        REVIEW = "REVIEW", "Review"
        HIGH_RISK = "HIGH_RISK", "High Risk"

    teacher = models.ForeignKey("teachers.Teacher", on_delete=models.CASCADE, related_name="flags")
    cycle = models.ForeignKey("cycles.EvaluationCycle", on_delete=models.CASCADE, related_name="flags")
    comparison = models.ForeignKey("comparisons.ComparisonResult", on_delete=models.CASCADE, related_name="flags")
    case = models.ForeignKey(Case, null=True, blank=True, on_delete=models.SET_NULL, related_name="flags")
    severity = models.CharField(max_length=16, choices=Severity.choices)
    code = models.CharField(max_length=64)
    message = models.TextField()
    payload_json = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["severity", "created_at"]),
            models.Index(fields=["teacher", "cycle"]),
        ]
