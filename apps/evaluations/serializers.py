from rest_framework import serializers

from apps.accounts.permissions import can_access_teacher
from apps.audit.services import log_audit
from apps.criteria.models import EvaluationCriterion

from .models import EvaluationItem, ManagerEvaluation, ScoreSummary


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
