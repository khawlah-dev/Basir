from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.permissions import IsLeaderOrAdmin
from apps.accounts.throttles import SensitiveActionThrottle, WriteUserThrottle
from apps.comparisons.services import compare_scores_and_generate_flags
from apps.objective_scoring.services import compute_objective_score

from .models import ManagerEvaluation
from .serializers import EvaluationItemsUpsertSerializer, ManagerEvaluationSerializer
from .services import finalize_evaluation


class ManagerEvaluationViewSet(viewsets.ModelViewSet):
    serializer_class = ManagerEvaluationSerializer
    permission_classes = [IsLeaderOrAdmin]

    def get_throttles(self):
        if self.action in ["finalize"]:
            return [SensitiveActionThrottle()]
        return [WriteUserThrottle()]

    def get_queryset(self):
        user = self.request.user
        qs = ManagerEvaluation.objects.select_related("teacher", "cycle", "manager").prefetch_related("items__criterion", "summary")
        if user.role == User.Role.ADMIN:
            return qs
        return qs.filter(teacher__school_id=user.school_id)

    @action(detail=True, methods=["put"], url_path="items")
    def upsert_items(self, request, pk=None):
        evaluation = self.get_object()
        if evaluation.status == ManagerEvaluation.Status.FINAL:
            raise ValidationError("Cannot edit finalized evaluation")
        serializer = EvaluationItemsUpsertSerializer(data=request.data, context={"request": request, "evaluation": evaluation})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(ManagerEvaluationSerializer(evaluation, context={"request": request}).data)

    @action(detail=True, methods=["post"], url_path="finalize")
    def finalize(self, request, pk=None):
        evaluation = self.get_object()
        if evaluation.status == ManagerEvaluation.Status.FINAL:
            return Response({"detail": "Evaluation already finalized"}, status=status.HTTP_200_OK)

        try:
            with transaction.atomic():
                summary = finalize_evaluation(evaluation, actor=request.user)
                objective = compute_objective_score(
                    teacher=evaluation.teacher,
                    cycle=evaluation.cycle,
                    actor=request.user,
                )
                comparison = compare_scores_and_generate_flags(
                    teacher=evaluation.teacher,
                    cycle=evaluation.cycle,
                    actor=request.user,
                )
        except DjangoValidationError as exc:
            raise ValidationError(exc.message)

        return Response(
            {
                "evaluation_id": evaluation.id,
                "manager_total_score": summary.manager_total_score,
                "rating_level": summary.rating_level,
                "objective_total_score": objective.objective_total,
                "objective_score_scope": "PARTIAL_OBJECTIVE_SCORE",
                "deviation": comparison.deviation,
                "deviation_level": comparison.deviation_level,
            },
            status=status.HTTP_200_OK,
        )
