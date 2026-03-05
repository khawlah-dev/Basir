from rest_framework import serializers

from apps.accounts.permissions import can_access_teacher
from apps.audit.services import log_audit
from apps.cycles.models import EvaluationCycle
from apps.teachers.models import Teacher

from .models import TeacherMetricSnapshot


class TeacherMetricSnapshotSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeacherMetricSnapshot
        fields = [
            "id",
            "teacher",
            "cycle",
            "pd_hours",
            "plans_count",
            "created_by",
            "approval_status",
            "approved_by",
            "approved_at",
            "created_at",
        ]
        read_only_fields = ["id", "created_by", "approval_status", "approved_by", "approved_at", "created_at"]

    def validate(self, attrs):
        request = self.context["request"]
        teacher = attrs.get("teacher") or getattr(self.instance, "teacher", None)
        cycle = attrs.get("cycle") or getattr(self.instance, "cycle", None)
        if teacher is None or cycle is None:
            raise serializers.ValidationError("teacher and cycle are required")
        if request.user.role != request.user.Role.TEACHER:
            raise serializers.ValidationError("Only teachers can submit metrics")
        if teacher.user_id != request.user.id:
            raise serializers.ValidationError("Teachers can only submit their own metrics")
        if not can_access_teacher(user=request.user, teacher=teacher):
            raise serializers.ValidationError("Not allowed to submit metrics for this teacher")
        if teacher.school_id != cycle.school_id:
            raise serializers.ValidationError("Teacher and cycle must belong to the same school")
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        teacher: Teacher = validated_data["teacher"]
        cycle: EvaluationCycle = validated_data["cycle"]

        obj, created = TeacherMetricSnapshot.objects.update_or_create(
            teacher=teacher,
            cycle=cycle,
            defaults={
                "pd_hours": validated_data["pd_hours"],
                "plans_count": validated_data["plans_count"],
                "created_by": request.user,
                "approval_status": TeacherMetricSnapshot.ApprovalStatus.PENDING,
                "approved_by": None,
                "approved_at": None,
            },
        )

        action = "metrics.submitted" if created else "metrics.resubmitted"
        log_audit(
            actor=request.user,
            action=action,
            entity_type="TeacherMetricSnapshot",
            entity_id=str(obj.id),
            after={
                "teacher_id": obj.teacher_id,
                "cycle_id": obj.cycle_id,
                "pd_hours": str(obj.pd_hours),
                "plans_count": obj.plans_count,
            },
        )
        return obj
