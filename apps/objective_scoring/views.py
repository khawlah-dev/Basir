from rest_framework import mixins, viewsets

from apps.accounts.models import User
from apps.accounts.permissions import IsTeacherLeaderOrAdmin

from .models import ObjectiveScore
from .serializers import ObjectiveScoreSerializer


class ObjectiveScoreViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ObjectiveScoreSerializer
    permission_classes = [IsTeacherLeaderOrAdmin]

    def get_queryset(self):
        user = self.request.user
        qs = ObjectiveScore.objects.select_related("teacher", "teacher__user", "cycle")

        teacher_id = self.request.query_params.get("teacher_id")
        cycle_id = self.request.query_params.get("cycle_id")
        if teacher_id:
            qs = qs.filter(teacher_id=teacher_id)
        if cycle_id:
            qs = qs.filter(cycle_id=cycle_id)

        if user.role == User.Role.ADMIN:
            return qs
        if user.role == User.Role.LEADER:
            return qs.filter(teacher__school_id=user.school_id)
        return qs.filter(teacher__user_id=user.id)
