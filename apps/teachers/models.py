from django.db import models


class Teacher(models.Model):
    user = models.OneToOneField("accounts.User", on_delete=models.CASCADE, related_name="teacher_profile")
    school = models.ForeignKey("schools.School", on_delete=models.PROTECT, related_name="teachers")
    employee_id = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [models.Index(fields=["school", "employee_id"])]

    def __str__(self) -> str:
        return self.user.get_full_name() or self.user.username
