from rest_framework import serializers

from .models import ObjectiveScore


class ObjectiveScoreSerializer(serializers.ModelSerializer):
    class Meta:
        model = ObjectiveScore
        fields = [
            "id",
            "teacher",
            "cycle",
            "objective_total",
            "breakdown_json",
            "policy_version",
            "computed_at",
        ]
