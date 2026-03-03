from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    class Role(models.TextChoices):
        TEACHER = "TEACHER", "Teacher"
        LEADER = "LEADER", "Leader"
        ADMIN = "ADMIN", "Admin"

    role = models.CharField(max_length=16, choices=Role.choices, default=Role.TEACHER)
    school = models.ForeignKey("schools.School", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        indexes = [models.Index(fields=["role", "school"])]
