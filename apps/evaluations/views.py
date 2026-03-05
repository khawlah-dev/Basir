from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.exceptions import ValidationError

from apps.accounts.models import User
from apps.accounts.permissions import IsLeaderOrAdmin, IsTeacher, IsTeacherLeaderOrAdmin
from apps.accounts.throttles import SensitiveActionThrottle, WriteUserThrottle
from apps.audit.services import log_audit
from apps.comparisons.services import compare_scores_and_generate_flags
from apps.cycles.models import EvaluationCycle
from apps.objective_scoring.services import compute_objective_score

from .models import EvidenceAttachment, ManagerEvaluation, TeacherEvidence
from .serializers import EvaluationItemsUpsertSerializer, ManagerEvaluationSerializer, TeacherEvidenceSerializer
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


class TeacherEvidenceViewSet(viewsets.ModelViewSet):
    serializer_class = TeacherEvidenceSerializer
    permission_classes = [IsTeacherLeaderOrAdmin]

    def get_permissions(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            permission_classes = [IsTeacher]
        else:
            permission_classes = [IsTeacherLeaderOrAdmin]
        return [permission() for permission in permission_classes]

    def get_throttles(self):
        if self.action in ["create", "update", "partial_update", "destroy"]:
            return [WriteUserThrottle()]
        return super().get_throttles()

    def get_queryset(self):
        user = self.request.user
        qs = TeacherEvidence.objects.select_related("teacher", "teacher__user", "cycle", "criterion", "submitted_by").prefetch_related(
            "attachments"
        )
        if user.role == User.Role.ADMIN:
            return qs
        if user.role == User.Role.LEADER:
            return qs.filter(teacher__school_id=user.school_id)
        return qs.filter(teacher__user_id=user.id)

    def perform_create(self, serializer):
        if self.request.user.role != User.Role.TEACHER:
            raise ValidationError("Only teachers can submit evidence.")
        teacher = serializer.validated_data["teacher"]
        if teacher.user_id != self.request.user.id:
            raise ValidationError("Teachers can only submit evidence for themselves.")
        active_semester = (
            EvaluationCycle.objects.filter(school=teacher.school, is_active=True)
            .order_by("-start_date")
            .first()
        )
        if not active_semester:
            raise ValidationError("No active semester configured for this school.")
        uploaded_files = self.request.FILES.getlist("files") or self.request.FILES.getlist("attachments")
        if not uploaded_files:
            raise ValidationError("At least one file/image/video must be uploaded.")

        evidence = serializer.save(submitted_by=self.request.user, cycle=active_semester)
        for uploaded_file in uploaded_files:
            EvidenceAttachment.objects.create(
                evidence=evidence,
                file=uploaded_file,
                uploaded_by=self.request.user,
            )
        log_audit(
            actor=self.request.user,
            action="evidence.created",
            entity_type="TeacherEvidence",
            entity_id=str(evidence.id),
            after={
                "teacher_id": evidence.teacher_id,
                "cycle_id": evidence.cycle_id,
                "criterion_id": evidence.criterion_id,
                "attachments_count": len(uploaded_files),
            },
        )

    def perform_update(self, serializer):
        evidence = self.get_object()
        if self.request.user.role != User.Role.TEACHER or evidence.teacher.user_id != self.request.user.id:
            raise ValidationError("Only the teacher owner can edit this evidence.")
        updated = serializer.save()
        log_audit(
            actor=self.request.user,
            action="evidence.updated",
            entity_type="TeacherEvidence",
            entity_id=str(updated.id),
            after={
                "teacher_id": updated.teacher_id,
                "cycle_id": updated.cycle_id,
                "criterion_id": updated.criterion_id,
            },
        )

    def perform_destroy(self, instance):
        if self.request.user.role != User.Role.TEACHER or instance.teacher.user_id != self.request.user.id:
            raise ValidationError("Only the teacher owner can delete this evidence.")
        evidence_id = instance.id
        instance.delete()
        log_audit(
            actor=self.request.user,
            action="evidence.deleted",
            entity_type="TeacherEvidence",
            entity_id=str(evidence_id),
        )
