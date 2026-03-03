from rest_framework import serializers

from .models import ComparisonResult


class ComparisonResultSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComparisonResult
        fields = [
            "id",
            "teacher",
            "cycle",
            "manager_total",
            "objective_total",
            "deviation",
            "deviation_level",
            "created_at",
        ]
