from rest_framework import serializers

from apps.accounts.permissions import can_access_teacher
from apps.audit.services import log_audit
from apps.criteria.models import EvaluationCriterion

from .models import EvaluationItem, ManagerEvaluation, ScoreSummary, TeacherEvidence


class EvaluationItemInputSerializer(serializers.Serializer):
    criterion_id = serializers.IntegerField()
    score = serializers.IntegerField(min_value=1, max_value=5)


class EvaluationItemSerializer(serializers.ModelSerializer):
    criterion_name = serializers.CharField(source="criterion.name", read_only=True)
    criterion_weight = serializers.IntegerField(source="criterion.weight_percent", read_only=True)

    class Meta:
        model = EvaluationItem
        fields = ["id", "criterion", "criterion_name", "criterion_weight", "score"]


class ScoreSummarySerializer(serializers.ModelSerializer):
    class Meta:
        model = ScoreSummary
        fields = ["manager_total_score", "rating_level", "calculated_at"]


class ManagerEvaluationSerializer(serializers.ModelSerializer):
    items = EvaluationItemSerializer(many=True, read_only=True)
    summary = ScoreSummarySerializer(read_only=True)

    class Meta:
        model = ManagerEvaluation
        fields = [
            "id",
            "teacher",
            "cycle",
            "manager",
            "status",
            "finalized_at",
            "created_at",
            "items",
            "summary",
        ]
        read_only_fields = ["id", "manager", "status", "finalized_at", "created_at", "items", "summary"]

    def validate(self, attrs):
        teacher = attrs["teacher"]
        cycle = attrs["cycle"]
        request = self.context["request"]
        if not can_access_teacher(user=request.user, teacher=teacher):
            raise serializers.ValidationError("Not allowed to evaluate this teacher")
        if teacher.school_id != cycle.school_id:
            raise serializers.ValidationError("Teacher and cycle must be in the same school")
        return attrs

    def create(self, validated_data):
        validated_data["manager"] = self.context["request"].user
        return super().create(validated_data)


class EvaluationItemsUpsertSerializer(serializers.Serializer):
    items = EvaluationItemInputSerializer(many=True)

    def validate(self, attrs):
        items = attrs["items"]
        ids = [x["criterion_id"] for x in items]
        if len(ids) != len(set(ids)):
            raise serializers.ValidationError("Duplicate criterion_id provided")
        found = set(EvaluationCriterion.objects.filter(id__in=ids, is_active=True).values_list("id", flat=True))
        missing = set(ids) - found
        if missing:
            raise serializers.ValidationError(f"Invalid or inactive criteria: {sorted(missing)}")
        return attrs

    def save(self, **kwargs):
        evaluation: ManagerEvaluation = self.context["evaluation"]
        request = self.context["request"]
        for item in self.validated_data["items"]:
            EvaluationItem.objects.update_or_create(
                evaluation=evaluation,
                criterion_id=item["criterion_id"],
                defaults={"score": item["score"]},
            )
        log_audit(
            actor=request.user,
            action="evaluation.items_upserted",
            entity_type="ManagerEvaluation",
            entity_id=str(evaluation.id),
            after={"items_count": len(self.validated_data['items'])},
        )
        return evaluation


class TeacherEvidenceSerializer(serializers.ModelSerializer):
    criterion_name = serializers.CharField(source="criterion.name", read_only=True)
    attachments = serializers.SerializerMethodField()

    def get_attachments(self, obj):
        return [
            {
                "id": attachment.id,
                "file_url": attachment.file.url if attachment.file else "",
                "filename": attachment.filename,
                "uploaded_at": attachment.uploaded_at,
            }
            for attachment in obj.attachments.all()
        ]

    class Meta:
        model = TeacherEvidence
        fields = [
            "id",
            "teacher",
            "cycle",
            "criterion",
            "criterion_name",
            "evidence_text",
            "submitted_by",
            "attachments",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "submitted_by", "created_at", "updated_at", "criterion_name", "cycle", "attachments"]
        extra_kwargs = {
            "cycle": {"required": False},
        }

    def validate(self, attrs):
        request = self.context["request"]
        teacher = attrs.get("teacher") or getattr(self.instance, "teacher", None)
        cycle = attrs.get("cycle") or getattr(self.instance, "cycle", None)
        criterion = attrs.get("criterion") or getattr(self.instance, "criterion", None)

        if not teacher or not criterion:
            raise serializers.ValidationError("teacher and criterion are required")

        if self.instance is None and request.user.role != request.user.Role.TEACHER:
            raise serializers.ValidationError("Only teachers can submit evidence")

        if cycle and teacher.school_id != cycle.school_id:
            raise serializers.ValidationError("Teacher and cycle must be in the same school")

        if not criterion.is_active:
            raise serializers.ValidationError("Evidence can only be added to active criteria")

        if request.user.role == request.user.Role.TEACHER and teacher.user_id != request.user.id:
            raise serializers.ValidationError("Teachers can only add their own evidence")
        return attrs
