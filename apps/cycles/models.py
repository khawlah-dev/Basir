from django.db import models


class EvaluationCycle(models.Model):
    school = models.ForeignKey("schools.School", on_delete=models.CASCADE, related_name="cycles")
    name = models.CharField(max_length=100)
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["school", "name"], name="uq_cycle_school_name"),
            models.CheckConstraint(check=models.Q(end_date__gte=models.F("start_date")), name="ck_cycle_dates_order"),
        ]
        indexes = [models.Index(fields=["school", "is_active"])]

    def __str__(self) -> str:
        return f"{self.school.code}:{self.name}"
