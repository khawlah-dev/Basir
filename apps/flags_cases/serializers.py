from rest_framework import serializers

from .models import Case, Flag


class FlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Flag
        fields = [
            "id",
            "teacher",
            "cycle",
            "comparison",
            "case",
            "severity",
            "code",
            "message",
            "payload_json",
            "created_at",
        ]


class CaseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Case
        fields = [
            "id",
            "teacher",
            "cycle",
            "status",
            "opened_by",
            "decision_note",
            "closed_by",
            "closed_at",
            "opened_at",
        ]
        read_only_fields = ["opened_by", "closed_by", "closed_at", "opened_at"]


class CaseCloseSerializer(serializers.Serializer):
    decision_note = serializers.CharField(required=True, allow_blank=False)
