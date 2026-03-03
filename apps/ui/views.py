from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.accounts.models import User
from apps.audit.services import log_audit
from apps.comparisons.models import ComparisonResult
from apps.comparisons.services import compare_scores_and_generate_flags
from apps.evaluations.models import ManagerEvaluation
from apps.evaluations.services import finalize_evaluation
from apps.flags_cases.models import Case, Flag
from apps.metrics.models import TeacherMetricSnapshot
from apps.objective_scoring.models import ObjectiveScore
from apps.objective_scoring.services import compute_objective_score
from apps.teachers.models import Teacher

from .forms import CaseCloseForm, EvaluationCreateForm, EvaluationItemsForm, MetricSnapshotForm


def _teacher_for_user(user: User) -> Teacher | None:
    return Teacher.objects.filter(user=user).first()


def _by_role_teacher_scope(user: User):
    qs = Teacher.objects.select_related("user", "school")
    if user.role == User.Role.ADMIN:
        return qs
    if user.role == User.Role.LEADER:
        return qs.filter(school=user.school)
    return qs.filter(user=user)


def _by_role_queryset(user: User, model, teacher_lookup: str = "teacher"):
    qs = model.objects.all()
    if user.role == User.Role.ADMIN:
        return qs
    if user.role == User.Role.LEADER:
        return qs.filter(**{f"{teacher_lookup}__school": user.school})
    return qs.filter(**{f"{teacher_lookup}__user": user})


def _require_roles(user: User, allowed: list[str]) -> bool:
    return user.is_authenticated and user.role in allowed


@login_required
def home(request: HttpRequest) -> HttpResponse:
    return redirect("ui:dashboard")


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    user = request.user
    teacher = _teacher_for_user(user)

    context = {
        "teacher": teacher,
        "metrics_count": _by_role_queryset(user, TeacherMetricSnapshot).count(),
        "objectives_count": _by_role_queryset(user, ObjectiveScore).count(),
        "evaluations_count": _by_role_queryset(user, ManagerEvaluation).count(),
        "comparisons_count": _by_role_queryset(user, ComparisonResult).count(),
        "open_cases_count": _by_role_queryset(user, Case).exclude(status=Case.Status.CLOSED).count(),
    }
    return render(request, "ui/dashboard.html", context)


@login_required
def metrics_page(request: HttpRequest) -> HttpResponse:
    snapshots = (
        _by_role_queryset(request.user, TeacherMetricSnapshot)
        .select_related("teacher", "teacher__user", "cycle")
        .order_by("-created_at")
    )

    if request.method == "POST":
        form = MetricSnapshotForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            try:
                with transaction.atomic():
                    obj, created = TeacherMetricSnapshot.objects.update_or_create(
                        teacher=data["teacher"],
                        cycle=data["cycle"],
                        defaults={
                            "pd_hours": data["pd_hours"],
                            "plans_count": data["plans_count"],
                            "created_by": request.user,
                        },
                    )
                    log_audit(
                        actor=request.user,
                        action="metrics.created" if created else "metrics.updated",
                        entity_type="TeacherMetricSnapshot",
                        entity_id=str(obj.id),
                        after={
                            "teacher_id": obj.teacher_id,
                            "cycle_id": obj.cycle_id,
                            "pd_hours": str(obj.pd_hours),
                            "plans_count": obj.plans_count,
                        },
                    )
                messages.success(request, "تم حفظ بيانات المؤشرات بنجاح.")
                return redirect("ui:metrics")
            except IntegrityError:
                messages.error(request, "تعذر حفظ البيانات بسبب تعارض في السجلات.")
    else:
        form = MetricSnapshotForm(user=request.user)

    return render(request, "ui/metrics.html", {"form": form, "snapshots": snapshots})


@login_required
def objective_scores_page(request: HttpRequest) -> HttpResponse:
    scores = (
        _by_role_queryset(request.user, ObjectiveScore)
        .select_related("teacher", "teacher__user", "cycle")
        .order_by("-computed_at")
    )
    return render(request, "ui/objective_scores.html", {"scores": scores})


@login_required
def objective_recompute(request: HttpRequest, teacher_id: int, cycle_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("ui:objective-scores")

    teacher = get_object_or_404(_by_role_teacher_scope(request.user), id=teacher_id)
    snapshot = get_object_or_404(
        _by_role_queryset(request.user, TeacherMetricSnapshot),
        teacher_id=teacher_id,
        cycle_id=cycle_id,
    )

    try:
        compute_objective_score(teacher=teacher, cycle=snapshot.cycle, actor=request.user)
        messages.success(request, "تمت إعادة احتساب الدرجة الموضوعية الجزئية.")
    except ValidationError as exc:
        messages.error(request, str(exc))
    return redirect("ui:objective-scores")


@login_required
def evaluations_page(request: HttpRequest) -> HttpResponse:
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "إدارة التقييمات متاحة فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    evaluations = (
        _by_role_queryset(request.user, ManagerEvaluation)
        .select_related("teacher", "teacher__user", "cycle", "manager")
        .prefetch_related("items__criterion", "summary")
        .order_by("-created_at")
    )

    if request.method == "POST":
        form = EvaluationCreateForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            evaluation = ManagerEvaluation.objects.create(
                teacher=data["teacher"],
                cycle=data["cycle"],
                manager=request.user,
            )
            messages.success(request, "تم إنشاء التقييم. أدخل درجات المعايير الـ 11.")
            return redirect("ui:evaluation-items", evaluation_id=evaluation.id)
    else:
        form = EvaluationCreateForm(user=request.user)

    return render(request, "ui/evaluations.html", {"form": form, "evaluations": evaluations})


@login_required
def evaluation_items_page(request: HttpRequest, evaluation_id: int) -> HttpResponse:
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "تعديل التقييمات متاح فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    evaluation = get_object_or_404(
        _by_role_queryset(request.user, ManagerEvaluation),
        id=evaluation_id,
    )

    if evaluation.status == ManagerEvaluation.Status.FINAL:
        messages.info(request, "تم اعتماد هذا التقييم مسبقا.")
        return redirect("ui:evaluations")

    if request.method == "POST":
        form = EvaluationItemsForm(request.POST, evaluation=evaluation)
        if form.is_valid():
            form.save()
            log_audit(
                actor=request.user,
                action="evaluation.items_upserted",
                entity_type="ManagerEvaluation",
                entity_id=str(evaluation.id),
                after={"items_count": evaluation.items.count()},
            )
            messages.success(request, "تم حفظ درجات المعايير.")
            return redirect("ui:evaluations")
    else:
        form = EvaluationItemsForm(evaluation=evaluation)

    return render(request, "ui/evaluation_items.html", {"evaluation": evaluation, "form": form})


@login_required
def evaluation_finalize(request: HttpRequest, evaluation_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("ui:evaluations")

    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "اعتماد التقييمات متاح فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    evaluation = get_object_or_404(
        _by_role_queryset(request.user, ManagerEvaluation),
        id=evaluation_id,
    )

    try:
        with transaction.atomic():
            finalize_evaluation(evaluation, actor=request.user)
            compute_objective_score(teacher=evaluation.teacher, cycle=evaluation.cycle, actor=request.user)
            compare_scores_and_generate_flags(teacher=evaluation.teacher, cycle=evaluation.cycle, actor=request.user)
        messages.success(request, "تم اعتماد التقييم واحتساب الدرجة الموضوعية الجزئية وإكمال المقارنة.")
    except ValidationError as exc:
        messages.error(request, str(exc))

    return redirect("ui:evaluations")


@login_required
def comparisons_page(request: HttpRequest) -> HttpResponse:
    comparisons = (
        _by_role_queryset(request.user, ComparisonResult)
        .select_related("teacher", "teacher__user", "cycle")
        .order_by("-created_at")
    )
    return render(request, "ui/comparisons.html", {"comparisons": comparisons})


@login_required
def flags_page(request: HttpRequest) -> HttpResponse:
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "عرض التنبيهات متاح فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    flags = (
        _by_role_queryset(request.user, Flag)
        .select_related("teacher", "teacher__user", "cycle", "case")
        .order_by("-created_at")
    )
    return render(request, "ui/flags.html", {"flags": flags})


@login_required
def cases_page(request: HttpRequest) -> HttpResponse:
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "عرض الحالات متاح فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    cases = (
        _by_role_queryset(request.user, Case)
        .select_related("teacher", "teacher__user", "cycle", "opened_by", "closed_by")
        .order_by("-opened_at")
    )
    return render(request, "ui/cases.html", {"cases": cases})


@login_required
def case_close_page(request: HttpRequest, case_id: int) -> HttpResponse:
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "إغلاق الحالات متاح فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    case = get_object_or_404(_by_role_queryset(request.user, Case), id=case_id)

    if case.status == Case.Status.CLOSED:
        messages.info(request, "الحالة مغلقة بالفعل.")
        return redirect("ui:cases")

    if request.method == "POST":
        form = CaseCloseForm(request.POST, instance=case)
        if form.is_valid():
            before = {"status": case.status, "decision_note": case.decision_note}
            updated = form.save(commit=False)
            updated.status = Case.Status.CLOSED
            updated.closed_by = request.user
            updated.closed_at = timezone.now()
            updated.save(update_fields=["decision_note", "status", "closed_by", "closed_at"])
            log_audit(
                actor=request.user,
                action="case.closed",
                entity_type="Case",
                entity_id=str(updated.id),
                before=before,
                after={"status": updated.status, "decision_note": updated.decision_note},
            )
            messages.success(request, "تم إغلاق الحالة بنجاح.")
            return redirect("ui:cases")
    else:
        form = CaseCloseForm(instance=case)

    return render(request, "ui/case_close.html", {"case": case, "form": form})


class PingView(LoginRequiredMixin, View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("OK")
