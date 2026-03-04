import os

from django.core.validators import FileExtensionValidator
from django.db import models


class ManagerEvaluation(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        FINAL = "FINAL", "Final"

    teacher = models.ForeignKey("teachers.Teacher", on_delete=models.CASCADE, related_name="evaluations")
    cycle = models.ForeignKey("cycles.EvaluationCycle", on_delete=models.CASCADE, related_name="evaluations")
    manager = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="manager_evaluations")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["teacher", "cycle"], name="uq_eval_teacher_cycle"),
        ]
        indexes = [models.Index(fields=["cycle", "status"])]


class EvaluationItem(models.Model):
    evaluation = models.ForeignKey(ManagerEvaluation, on_delete=models.CASCADE, related_name="items")
    criterion = models.ForeignKey("criteria.EvaluationCriterion", on_delete=models.PROTECT)
    score = models.PositiveSmallIntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["evaluation", "criterion"], name="uq_evalitem_eval_criterion"),
            models.CheckConstraint(check=models.Q(score__gte=1, score__lte=5), name="ck_evalitem_score_1_5"),
        ]


class ScoreSummary(models.Model):
    evaluation = models.OneToOneField(ManagerEvaluation, on_delete=models.CASCADE, related_name="summary")
    manager_total_score = models.DecimalField(max_digits=5, decimal_places=2)
    rating_level = models.CharField(max_length=32)
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                check=models.Q(manager_total_score__gte=0, manager_total_score__lte=100),
                name="ck_manager_total_0_100",
            ),
        ]


class TeacherEvidence(models.Model):
    teacher = models.ForeignKey("teachers.Teacher", on_delete=models.CASCADE, related_name="evidences")
    cycle = models.ForeignKey("cycles.EvaluationCycle", on_delete=models.CASCADE, related_name="evidences")
    criterion = models.ForeignKey("criteria.EvaluationCriterion", on_delete=models.PROTECT, related_name="evidences")
    evidence_text = models.TextField()
    evidence_url = models.URLField(blank=True, default="")
    submitted_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="submitted_evidences")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=~models.Q(evidence_text=""), name="ck_evidence_text_not_empty"),
        ]
        indexes = [
            models.Index(fields=["teacher", "cycle", "created_at"]),
            models.Index(fields=["criterion", "created_at"]),
        ]


class EvidenceAttachment(models.Model):
    evidence = models.ForeignKey(TeacherEvidence, on_delete=models.CASCADE, related_name="attachments")
    file = models.FileField(
        upload_to="evidences/%Y/%m/%d/",
        validators=[
            FileExtensionValidator(
                allowed_extensions=[
                    "jpg",
                    "jpeg",
                    "png",
                    "gif",
                    "webp",
                    "pdf",
                    "doc",
                    "docx",
                    "xls",
                    "xlsx",
                    "ppt",
                    "pptx",
                    "txt",
                    "mp4",
                    "mov",
                    "avi",
                    "mkv",
                    "webm",
                    "m4v",
                ]
            )
        ],
    )
    uploaded_by = models.ForeignKey("accounts.User", on_delete=models.PROTECT, related_name="evidence_attachments")
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["evidence", "uploaded_at"]),
        ]

    @property
    def filename(self) -> str:
        return os.path.basename(self.file.name)
