from rest_framework import mixins, viewsets

from apps.accounts.models import User
from apps.accounts.permissions import IsTeacherLeaderOrAdmin
from apps.accounts.throttles import WriteUserThrottle

from .models import TeacherMetricSnapshot
from .serializers import TeacherMetricSnapshotSerializer


class TeacherMetricSnapshotViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = TeacherMetricSnapshotSerializer
    permission_classes = [IsTeacherLeaderOrAdmin]
    throttle_classes = [WriteUserThrottle]

    def get_queryset(self):
        user = self.request.user
        qs = TeacherMetricSnapshot.objects.select_related("teacher", "teacher__user", "cycle")
        if user.role == User.Role.ADMIN:
            return qs
        if user.role == User.Role.LEADER:
            return qs.filter(teacher__school_id=user.school_id)
        return qs.filter(teacher__user_id=user.id)
