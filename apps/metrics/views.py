from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.accounts.models import User
from apps.accounts.permissions import IsLeaderOrAdmin, IsTeacher, IsTeacherLeaderOrAdmin
from apps.accounts.throttles import WriteUserThrottle
from apps.audit.services import log_audit

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

    def get_permissions(self):
        if self.action == "create":
            permission_classes = [IsTeacher]
        elif self.action == "approve":
            permission_classes = [IsLeaderOrAdmin]
        else:
            permission_classes = [IsTeacherLeaderOrAdmin]
        return [permission() for permission in permission_classes]

    def get_queryset(self):
        user = self.request.user
        qs = TeacherMetricSnapshot.objects.select_related("teacher", "teacher__user", "cycle")
        if user.role == User.Role.ADMIN:
            return qs
        if user.role == User.Role.LEADER:
            return qs.filter(teacher__school_id=user.school_id)
        return qs.filter(teacher__user_id=user.id)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        snapshot = self.get_object()
        if snapshot.approval_status != TeacherMetricSnapshot.ApprovalStatus.APPROVED:
            snapshot.approval_status = TeacherMetricSnapshot.ApprovalStatus.APPROVED
            snapshot.approved_by = request.user
            snapshot.approved_at = timezone.now()
            snapshot.save(update_fields=["approval_status", "approved_by", "approved_at"])
            log_audit(
                actor=request.user,
                action="metrics.approved",
                entity_type="TeacherMetricSnapshot",
                entity_id=str(snapshot.id),
                after={
                    "teacher_id": snapshot.teacher_id,
                    "cycle_id": snapshot.cycle_id,
                    "approved_by": request.user.id,
                },
            )
        serializer = self.get_serializer(snapshot)
        return Response(serializer.data, status=status.HTTP_200_OK)
