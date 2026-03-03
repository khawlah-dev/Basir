from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.permissions import IsLeaderOrAdmin
from apps.accounts.throttles import SensitiveActionThrottle
from apps.audit.services import log_audit

from .models import Case, Flag
from .serializers import CaseCloseSerializer, CaseSerializer, FlagSerializer


class FlagViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = FlagSerializer
    permission_classes = [IsLeaderOrAdmin]

    def get_queryset(self):
        user = self.request.user
        qs = Flag.objects.select_related("teacher", "cycle", "comparison", "case")

        teacher_id = self.request.query_params.get("teacher_id")
        cycle_id = self.request.query_params.get("cycle_id")
        if teacher_id:
            qs = qs.filter(teacher_id=teacher_id)
        if cycle_id:
            qs = qs.filter(cycle_id=cycle_id)

        if user.role == User.Role.ADMIN:
            return qs
        return qs.filter(teacher__school_id=user.school_id)


class CaseViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CaseSerializer
    permission_classes = [IsLeaderOrAdmin]
    throttle_classes = [SensitiveActionThrottle]

    def get_queryset(self):
        user = self.request.user
        qs = Case.objects.select_related("teacher", "cycle", "opened_by", "closed_by")
        if user.role == User.Role.ADMIN:
            return qs
        return qs.filter(teacher__school_id=user.school_id)

    @action(detail=True, methods=["post"], url_path="close")
    def close_case(self, request, pk=None):
        case = self.get_object()
        if case.status == Case.Status.CLOSED:
            raise ValidationError("Case already closed")

        serializer = CaseCloseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        before = {"status": case.status, "decision_note": case.decision_note}
        case.status = Case.Status.CLOSED
        case.decision_note = serializer.validated_data["decision_note"]
        case.closed_by = request.user
        case.closed_at = timezone.now()
        case.save(update_fields=["status", "decision_note", "closed_by", "closed_at"])

        log_audit(
            actor=request.user,
            action="case.closed",
            entity_type="Case",
            entity_id=str(case.id),
            before=before,
            after={"status": case.status, "decision_note": case.decision_note, "closed_at": case.closed_at.isoformat()},
        )

        return Response(CaseSerializer(case).data, status=status.HTTP_200_OK)
