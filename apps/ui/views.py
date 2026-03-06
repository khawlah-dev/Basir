from __future__ import annotations

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.accounts.models import User
from apps.audit.services import log_audit
from apps.comparisons.models import ComparisonResult
from apps.comparisons.services import compare_scores_and_generate_flags
from apps.cycles.models import EvaluationCycle
from apps.evaluations.models import EvidenceAttachment, ManagerEvaluation, TeacherEvidence
from apps.evaluations.services import finalize_evaluation
from apps.flags_cases.models import Case, Flag
from apps.metrics.models import TeacherMetricSnapshot
from apps.objective_scoring.models import ObjectiveScore
from apps.objective_scoring.services import compute_objective_score
from apps.teachers.models import Teacher

from .forms import CaseCloseForm, EvaluationCreateForm, EvaluationItemsForm, MetricSnapshotForm, TeacherEvidenceForm
from .forms import SemesterCreateForm, TeacherCreateForm


def _teacher_for_user(user: User) -> Teacher | None:
    return Teacher.objects.filter(user=user).first()


def _active_semester_for_school(school):
    return (
        EvaluationCycle.objects.filter(school=school, is_active=True)
        .order_by("-start_date")
        .first()
    )


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
    quick_evidence_form = None
    recent_evidences = []
    teacher_profile_missing = False
    current_semester = None
    manager_dashboard = None

    if user.role == User.Role.TEACHER:
        if teacher is None:
            teacher_profile_missing = True
        else:
            current_semester = _active_semester_for_school(teacher.school)
            recent_evidences = (
                TeacherEvidence.objects.filter(teacher=teacher)
                .select_related("cycle", "criterion")
                .prefetch_related("attachments")
                .order_by("-created_at")[:5]
            )
            if request.method == "POST" and request.POST.get("action") == "quick_evidence":
                if current_semester is None:
                    messages.error(request, "لا يوجد فصل دراسي نشط. يجب على المدير إضافة فصل دراسي أولاً.")
                    return redirect("ui:dashboard")
                quick_evidence_form = TeacherEvidenceForm(request.POST, request.FILES, user=request.user, teacher=teacher)
                if quick_evidence_form.is_valid():
                    evidence = quick_evidence_form.save(commit=False)
                    evidence.teacher = teacher
                    evidence.cycle = current_semester
                    evidence.submitted_by = request.user
                    evidence.save()
                    attachments = quick_evidence_form.cleaned_data.get("attachments", [])
                    for uploaded_file in attachments:
                        EvidenceAttachment.objects.create(
                            evidence=evidence,
                            file=uploaded_file,
                            uploaded_by=request.user,
                        )
                    log_audit(
                        actor=request.user,
                        action="evidence.created",
                        entity_type="TeacherEvidence",
                        entity_id=str(evidence.id),
                        after={
                            "teacher_id": evidence.teacher_id,
                            "cycle_id": evidence.cycle_id,
                            "criterion_id": evidence.criterion_id,
                            "attachments_count": len(attachments),
                        },
                    )
                    messages.success(request, "تم رفع الشاهد من لوحة التحكم بنجاح.")
                    return redirect("ui:dashboard")
            else:
                quick_evidence_form = TeacherEvidenceForm(user=request.user, teacher=teacher)
    elif user.role in [User.Role.LEADER, User.Role.ADMIN]:
        semesters_qs = EvaluationCycle.objects.select_related("school").order_by("-start_date")
        if user.role == User.Role.LEADER:
            semesters_qs = semesters_qs.filter(school=user.school)

        selected_cycle_id = request.GET.get("cycle_id", "").strip()
        search_text = request.GET.get("q", "").strip()

        selected_cycle = None
        if selected_cycle_id:
            selected_cycle = semesters_qs.filter(id=selected_cycle_id).first()
        if selected_cycle is None:
            selected_cycle = semesters_qs.first()

        teachers_qs = _by_role_teacher_scope(user).select_related("user", "school")
        if selected_cycle is not None:
            teachers_qs = teachers_qs.filter(school=selected_cycle.school)
        if search_text:
            teachers_qs = teachers_qs.filter(
                Q(user__username__icontains=search_text)
                | Q(user__first_name__icontains=search_text)
                | Q(user__last_name__icontains=search_text)
                | Q(employee_id__icontains=search_text)
            ).distinct()
        teachers_qs = teachers_qs.order_by("user__first_name", "user__last_name", "user__username")

        teacher_ids = list(teachers_qs.values_list("id", flat=True))
        evaluation_map = {}
        comparison_map = {}
        evidence_count_map = {}
        metrics_set = set()
        pending_metrics_set = set()
        objective_set = set()
        objective_total_map = {}
        top_teachers = []
        recent_manager_evidences = []
        level_counts = {
            "ممتاز (90+)": 0,
            "جيد جدًا (80-89)": 0,
            "جيد (70-79)": 0,
            "يحتاج دعم (<70)": 0,
            "بدون تقييم": 0,
        }

        if selected_cycle and teacher_ids:
            evaluations = ManagerEvaluation.objects.filter(teacher_id__in=teacher_ids, cycle=selected_cycle).select_related("teacher")
            evaluation_map = {item.teacher_id: item for item in evaluations}

            comparisons = ComparisonResult.objects.filter(teacher_id__in=teacher_ids, cycle=selected_cycle)
            comparison_map = {item.teacher_id: item for item in comparisons}

            evidence_count_map = {
                item["teacher_id"]: item["total"]
                for item in TeacherEvidence.objects.filter(teacher_id__in=teacher_ids, cycle=selected_cycle)
                .values("teacher_id")
                .annotate(total=Count("id"))
            }

            metrics_rows = TeacherMetricSnapshot.objects.filter(teacher_id__in=teacher_ids, cycle=selected_cycle).values(
                "teacher_id", "approval_status"
            )
            for metric_row in metrics_rows:
                if metric_row["approval_status"] == TeacherMetricSnapshot.ApprovalStatus.APPROVED:
                    metrics_set.add(metric_row["teacher_id"])
                else:
                    pending_metrics_set.add(metric_row["teacher_id"])
            objective_scores = ObjectiveScore.objects.filter(teacher_id__in=teacher_ids, cycle=selected_cycle)
            objective_total_map = {item.teacher_id: item.objective_total for item in objective_scores}
            objective_set = set(objective_total_map.keys())

            ranked_evaluations = (
                ManagerEvaluation.objects.filter(
                    teacher_id__in=teacher_ids,
                    cycle=selected_cycle,
                    status=ManagerEvaluation.Status.FINAL,
                    summary__isnull=False,
                )
                .select_related("teacher", "teacher__user", "summary")
                .order_by("-summary__manager_total_score", "teacher__user__first_name", "teacher__user__last_name")
            )

            ranked_evaluations_list = list(ranked_evaluations)

            for ev in ranked_evaluations_list:
                score_value = float(ev.summary.manager_total_score)
                if score_value >= 90:
                    level_counts["ممتاز (90+)"] += 1
                elif score_value >= 80:
                    level_counts["جيد جدًا (80-89)"] += 1
                elif score_value >= 70:
                    level_counts["جيد (70-79)"] += 1
                else:
                    level_counts["يحتاج دعم (<70)"] += 1

            level_counts["بدون تقييم"] = max(len(teacher_ids) - len(ranked_evaluations_list), 0)

            for ev in ranked_evaluations_list[:7]:
                comparison = comparison_map.get(ev.teacher_id)
                top_teachers.append(
                    {
                        "teacher": ev.teacher,
                        "manager_total": float(ev.summary.manager_total_score),
                        "objective_total": (
                            float(objective_total_map[ev.teacher_id]) if ev.teacher_id in objective_total_map else None
                        ),
                        "deviation": float(comparison.deviation) if comparison else None,
                    }
                )

            recent_manager_evidences = list(
                TeacherEvidence.objects.filter(teacher_id__in=teacher_ids, cycle=selected_cycle)
                .select_related("teacher", "teacher__user", "criterion", "cycle")
                .annotate(attachments_total=Count("attachments"))
                .order_by("-created_at")[:12]
            )

        manager_rows = []
        draft_count = 0
        final_count = 0
        review_count = 0
        high_risk_count = 0

        for item in teachers_qs:
            evaluation = evaluation_map.get(item.id)
            comparison = comparison_map.get(item.id)
            if selected_cycle is None:
                evaluation_state = "لا يوجد فصل دراسي"
                evaluation_badge = "secondary"
                action_mode = "no_cycle"
                action_label = "أضف فصل دراسي"
                workflow_step = "-"
            elif evaluation is None:
                evaluation_state = "لم يبدأ"
                evaluation_badge = "secondary"
                action_mode = "start"
                action_label = "بدء التقييم"
                workflow_step = "1/4"
            elif evaluation.status == ManagerEvaluation.Status.DRAFT:
                evaluation_state = "قيد الإدخال"
                evaluation_badge = "warning"
                action_mode = "resume"
                action_label = "استكمال التقييم"
                draft_count += 1
                workflow_step = "2/4"
            else:
                evaluation_state = "معتمد"
                evaluation_badge = "success"
                action_mode = "final"
                action_label = "تم الاعتماد"
                final_count += 1
                workflow_step = "3/4"

            deviation_badge = "secondary"
            deviation_label = "غير متاح"
            if comparison:
                workflow_step = "4/4"
                if comparison.deviation_level == ComparisonResult.DeviationLevel.NORMAL:
                    deviation_badge = "success"
                    deviation_label = "طبيعي"
                elif comparison.deviation_level == ComparisonResult.DeviationLevel.REVIEW:
                    deviation_badge = "warning"
                    deviation_label = "مراجعة"
                    review_count += 1
                else:
                    deviation_badge = "danger"
                    deviation_label = "مخاطرة عالية"
                    high_risk_count += 1

            manager_rows.append(
                {
                    "teacher": item,
                    "evaluation": evaluation,
                    "comparison": comparison,
                    "evidence_count": evidence_count_map.get(item.id, 0),
                    "has_metrics": item.id in metrics_set,
                    "has_pending_metrics": item.id in pending_metrics_set,
                    "has_objective": item.id in objective_set,
                    "evaluation_state": evaluation_state,
                    "evaluation_badge": evaluation_badge,
                    "action_mode": action_mode,
                    "action_label": action_label,
                    "deviation_badge": deviation_badge,
                    "deviation_label": deviation_label,
                    "workflow_step": workflow_step,
                    "review_evidence_url": f"{reverse('ui:evidences-admin')}?q={item.user.username}&cycle_id={selected_cycle.id if selected_cycle else ''}",
                    "comparison_url": (
                        f"{reverse('ui:comparisons')}?teacher_id={item.id}&cycle_id={selected_cycle.id}"
                        if selected_cycle
                        else reverse("ui:comparisons")
                    ),
                }
            )

        manager_dashboard = {
            "cycles": semesters_qs,
            "selected_cycle": selected_cycle,
            "selected_cycle_id": str(selected_cycle.id) if selected_cycle else "",
            "search_text": search_text,
            "rows": manager_rows,
            "total_teachers": len(manager_rows),
            "draft_count": draft_count,
            "final_count": final_count,
            "review_count": review_count,
            "high_risk_count": high_risk_count,
            "performance_labels": list(level_counts.keys()),
            "performance_values": list(level_counts.values()),
            "top_teachers": top_teachers,
            "top_chart_labels": [str(item["teacher"]) for item in top_teachers],
            "top_chart_manager_values": [item["manager_total"] for item in top_teachers],
            "top_chart_objective_values": [item["objective_total"] for item in top_teachers],
            "recent_evidences": recent_manager_evidences,
        }

    context = {
        "teacher": teacher,
        "metrics_count": _by_role_queryset(user, TeacherMetricSnapshot).count(),
        "objectives_count": _by_role_queryset(user, ObjectiveScore).count(),
        "evaluations_count": _by_role_queryset(user, ManagerEvaluation).count(),
        "comparisons_count": _by_role_queryset(user, ComparisonResult).count(),
        "open_cases_count": _by_role_queryset(user, Case).exclude(status=Case.Status.CLOSED).count(),
        "quick_evidence_form": quick_evidence_form,
        "recent_evidences": recent_evidences,
        "teacher_profile_missing": teacher_profile_missing,
        "current_semester": current_semester,
        "manager_dashboard": manager_dashboard,
    }
    return render(request, "ui/dashboard.html", context)


@login_required
def metrics_page(request: HttpRequest) -> HttpResponse:
    snapshots = (
        _by_role_queryset(request.user, TeacherMetricSnapshot)
        .select_related("teacher", "teacher__user", "cycle", "approved_by")
        .order_by("-created_at")
    )
    can_approve = request.user.role in [User.Role.LEADER, User.Role.ADMIN]
    is_teacher = request.user.role == User.Role.TEACHER

    if request.method == "POST":
        action = request.POST.get("action", "submit_metric")
        if action == "approve_metric":
            if not can_approve:
                messages.error(request, "اعتماد المؤشرات متاح للمدير فقط.")
                return redirect("ui:dashboard")
            snapshot_id = request.POST.get("snapshot_id")
            snapshot = get_object_or_404(_by_role_queryset(request.user, TeacherMetricSnapshot), id=snapshot_id)
            if snapshot.approval_status == TeacherMetricSnapshot.ApprovalStatus.APPROVED:
                messages.info(request, "هذا السجل معتمد مسبقًا.")
                return redirect("ui:metrics")
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
            messages.success(request, "تم اعتماد سجل المؤشرات بنجاح.")
            return redirect("ui:metrics")

        if not is_teacher:
            messages.error(request, "إدخال المؤشرات متاح للمعلم فقط، والاعتماد للمدير.")
            return redirect("ui:dashboard")

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
                            "training_hours": data["training_hours"],
                            "created_by": request.user,
                            "approval_status": TeacherMetricSnapshot.ApprovalStatus.PENDING,
                            "approved_by": None,
                            "approved_at": None,
                        },
                    )
                    log_audit(
                        actor=request.user,
                        action="metrics.submitted" if created else "metrics.resubmitted",
                        entity_type="TeacherMetricSnapshot",
                        entity_id=str(obj.id),
                        after={
                            "teacher_id": obj.teacher_id,
                            "cycle_id": obj.cycle_id,
                            "pd_hours": str(obj.pd_hours),
                            "training_hours": str(obj.training_hours),
                        },
                    )
                messages.success(request, "تم إرسال سجل المؤشرات للمراجعة والاعتماد.")
                return redirect("ui:metrics")
            except IntegrityError:
                messages.error(request, "تعذر حفظ البيانات بسبب تعارض في السجلات.")
    else:
        form = MetricSnapshotForm(user=request.user) if is_teacher else None

    return render(
        request,
        "ui/metrics.html",
        {"form": form, "snapshots": snapshots, "can_approve": can_approve, "is_teacher": is_teacher},
    )


@login_required
def objective_scores_page(request: HttpRequest) -> HttpResponse:
    scores = (
        _by_role_queryset(request.user, ObjectiveScore)
        .select_related("teacher", "teacher__user", "cycle")
        .order_by("-computed_at")
    )
    return render(request, "ui/objective_scores.html", {"scores": scores})


@login_required
def evidences_page(request: HttpRequest) -> HttpResponse:
    if request.user.role != User.Role.TEACHER:
        messages.error(request, "إدخال الشواهد متاح للمعلم فقط.")
        return redirect("ui:dashboard")

    teacher = _teacher_for_user(request.user)
    if teacher is None:
        return render(request, "ui/evidences_missing_profile.html", status=400)
    current_semester = _active_semester_for_school(teacher.school)
    evidences = (
        TeacherEvidence.objects.filter(teacher=teacher)
        .select_related("cycle", "criterion")
        .prefetch_related("attachments")
        .order_by("-created_at")
    )

    if request.method == "POST":
        if current_semester is None:
            messages.error(request, "لا يوجد فصل دراسي نشط. يجب على المدير إضافة فصل دراسي أولاً.")
            return redirect("ui:evidences")
        form = TeacherEvidenceForm(request.POST, request.FILES, user=request.user, teacher=teacher)
        if form.is_valid():
            evidence = form.save(commit=False)
            evidence.teacher = teacher
            evidence.cycle = current_semester
            evidence.submitted_by = request.user
            evidence.save()
            attachments = form.cleaned_data.get("attachments", [])
            for uploaded_file in attachments:
                EvidenceAttachment.objects.create(
                    evidence=evidence,
                    file=uploaded_file,
                    uploaded_by=request.user,
                )
            log_audit(
                actor=request.user,
                action="evidence.created",
                entity_type="TeacherEvidence",
                entity_id=str(evidence.id),
                after={
                    "teacher_id": evidence.teacher_id,
                    "cycle_id": evidence.cycle_id,
                    "criterion_id": evidence.criterion_id,
                    "attachments_count": len(attachments),
                },
            )
            messages.success(request, "تمت إضافة الشاهد بنجاح.")
            return redirect("ui:evidences")
    else:
        form = TeacherEvidenceForm(user=request.user, teacher=teacher)

    return render(
        request,
        "ui/evidences.html",
        {"form": form, "evidences": evidences, "current_semester": current_semester},
    )


@login_required
def evidences_admin_page(request: HttpRequest) -> HttpResponse:
    if request.user.role not in [User.Role.LEADER, User.Role.ADMIN]:
        messages.error(request, "هذه الصفحة متاحة للقادة أو المديرين فقط.")
        return redirect("ui:dashboard")

    teachers_qs = _by_role_teacher_scope(request.user).select_related("user", "school")
    cycles_qs = EvaluationCycle.objects.select_related("school").order_by("-start_date")
    if request.user.role == User.Role.LEADER:
        cycles_qs = cycles_qs.filter(school=request.user.school)

    search_text = request.GET.get("q", "").strip()
    cycle_id = request.GET.get("cycle_id", "").strip()

    if search_text:
        teachers_qs = teachers_qs.filter(
            Q(user__username__icontains=search_text)
            | Q(user__first_name__icontains=search_text)
            | Q(user__last_name__icontains=search_text)
            | Q(employee_id__icontains=search_text)
        ).distinct()
    teachers_qs = teachers_qs.order_by("school__name", "user__first_name", "user__last_name", "user__username")

    evidences_qs = (
        _by_role_queryset(request.user, TeacherEvidence)
        .select_related("teacher", "teacher__user", "cycle", "criterion", "submitted_by")
        .prefetch_related("attachments")
        .order_by("-created_at")
    )
    if cycle_id:
        evidences_qs = evidences_qs.filter(cycle_id=cycle_id)

    teacher_ids = list(teachers_qs.values_list("id", flat=True))
    evidences_qs = evidences_qs.filter(teacher_id__in=teacher_ids)

    grouped_evidences: dict[int, list[TeacherEvidence]] = {teacher_id: [] for teacher_id in teacher_ids}
    for evidence in evidences_qs:
        grouped_evidences[evidence.teacher_id].append(evidence)

    teacher_rows = []
    for teacher in teachers_qs:
        teacher_evidences = grouped_evidences.get(teacher.id, [])
        teacher_rows.append(
            {
                "teacher": teacher,
                "evidences": teacher_evidences,
                "count": len(teacher_evidences),
            }
        )

    return render(
        request,
        "ui/evidences_admin.html",
        {
            "teacher_rows": teacher_rows,
            "cycles": cycles_qs,
            "selected_cycle_id": cycle_id,
            "search_text": search_text,
            "total_evidence_count": sum(row["count"] for row in teacher_rows),
        },
    )


@login_required
def evidence_delete(request: HttpRequest, evidence_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("ui:evidences")
    if request.user.role != User.Role.TEACHER:
        messages.error(request, "حذف الشواهد متاح للمعلم فقط.")
        return redirect("ui:dashboard")

    teacher = _teacher_for_user(request.user)
    if teacher is None:
        messages.error(request, "لا يوجد ملف معلم مرتبط بهذا الحساب.")
        return redirect("ui:evidences")
    evidence = get_object_or_404(TeacherEvidence, id=evidence_id, teacher=teacher)
    evidence.delete()
    log_audit(
        actor=request.user,
        action="evidence.deleted",
        entity_type="TeacherEvidence",
        entity_id=str(evidence_id),
    )
    messages.success(request, "تم حذف الشاهد.")
    return redirect("ui:evidences")


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
        messages.success(request, "تم إعادة حساب توقع نموذج ML.")
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
            existing = ManagerEvaluation.objects.filter(teacher=data["teacher"], cycle=data["cycle"]).first()
            if existing:
                messages.info(request, "يوجد تقييم مسبق لهذا المعلم في نفس الفصل الدراسي. تم فتح التقييم الحالي.")
                if existing.status == ManagerEvaluation.Status.DRAFT:
                    return redirect("ui:evaluation-items", evaluation_id=existing.id)
                return redirect("ui:evaluations")
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
def evaluation_start(request: HttpRequest, teacher_id: int) -> HttpResponse:
    if request.method != "POST":
        return redirect("ui:dashboard")
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "إدارة التقييمات متاحة فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    teacher = get_object_or_404(_by_role_teacher_scope(request.user), id=teacher_id)
    cycle_id = request.POST.get("cycle_id")
    cycles_qs = EvaluationCycle.objects.all()
    if request.user.role == User.Role.LEADER:
        cycles_qs = cycles_qs.filter(school=request.user.school)
    cycle = get_object_or_404(cycles_qs, id=cycle_id)

    if teacher.school_id != cycle.school_id:
        messages.error(request, "يجب أن ينتمي المعلم والفصل الدراسي إلى نفس المدرسة.")
        return redirect("ui:dashboard")

    evaluation, created = ManagerEvaluation.objects.get_or_create(
        teacher=teacher,
        cycle=cycle,
        defaults={"manager": request.user},
    )
    if created:
        messages.success(request, "تم إنشاء تقييم جديد للمعلم.")
        return redirect("ui:evaluation-items", evaluation_id=evaluation.id)

    messages.info(request, "تم فتح التقييم الحالي لهذا المعلم.")
    if evaluation.status == ManagerEvaluation.Status.DRAFT:
        return redirect("ui:evaluation-items", evaluation_id=evaluation.id)
    return redirect("ui:evaluations")


@login_required
def evaluation_items_page(request: HttpRequest, evaluation_id: int) -> HttpResponse:
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "تعديل التقييمات متاح فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    evaluation = get_object_or_404(
        _by_role_queryset(request.user, ManagerEvaluation),
        id=evaluation_id,
    )
    evidences = (
        TeacherEvidence.objects.filter(teacher=evaluation.teacher, cycle=evaluation.cycle)
        .select_related("criterion")
        .prefetch_related("attachments")
        .order_by("-created_at")
    )
    evidences_by_criterion: dict[int, list[TeacherEvidence]] = {}
    for evidence in evidences:
        evidences_by_criterion.setdefault(evidence.criterion_id, []).append(evidence)

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

    criterion_rows = []
    for field in form:
        criterion_id = int(field.name.split("_", 1)[1])
        criterion_rows.append(
            {
                "field": field,
                "evidences": evidences_by_criterion.get(criterion_id, []),
            }
        )

    try:
        from apps.ml_scoring.prediction import get_or_predict as ml_get_or_predict
        ml_prediction = ml_get_or_predict(teacher=evaluation.teacher, cycle=evaluation.cycle)
    except Exception:
        ml_prediction = None

    return render(
        request,
        "ui/evaluation_items.html",
        {
            "evaluation": evaluation,
            "form": form,
            "criterion_rows": criterion_rows,
            "ml_prediction": ml_prediction,
        },
    )


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
        messages.success(request, "تم اعتماد التقييم وحساب توقع ML وإكمال المقارنة.")
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
    teacher_id = request.GET.get("teacher_id", "").strip()
    cycle_id = request.GET.get("cycle_id", "").strip()
    if teacher_id:
        comparisons = comparisons.filter(teacher_id=teacher_id)
    if cycle_id:
        comparisons = comparisons.filter(cycle_id=cycle_id)
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
def teachers_manage_page(request: HttpRequest) -> HttpResponse:
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "إدارة المعلمين متاحة فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    teachers = _by_role_teacher_scope(request.user).order_by("-created_at")

    if request.method == "POST":
        form = TeacherCreateForm(request.POST, user=request.user)
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():
                user = User.objects.create_user(
                    username=data["username"],
                    password=data["password"],
                    role=User.Role.TEACHER,
                    school=data["school"],
                    first_name=data["first_name"],
                    last_name=data["last_name"],
                    email=data["email"],
                    is_staff=False,
                    is_superuser=False,
                )
                teacher = Teacher.objects.create(
                    user=user,
                    school=data["school"],
                    employee_id=data["employee_id"],
                    is_active=True,
                )
                log_audit(
                    actor=request.user,
                    action="teacher.created",
                    entity_type="Teacher",
                    entity_id=str(teacher.id),
                    after={
                        "teacher_user_id": teacher.user_id,
                        "school_id": teacher.school_id,
                        "employee_id": teacher.employee_id,
                    },
                )
            messages.success(request, "تم إنشاء حساب المعلم بنجاح.")
            return redirect("ui:teachers-manage")
    else:
        form = TeacherCreateForm(user=request.user)

    return render(request, "ui/teachers_manage.html", {"form": form, "teachers": teachers})


@login_required
def semesters_manage_page(request: HttpRequest) -> HttpResponse:
    if not _require_roles(request.user, [User.Role.LEADER, User.Role.ADMIN]):
        messages.error(request, "إدارة الفصول الدراسية متاحة فقط للقادة أو المديرين.")
        return redirect("ui:dashboard")

    semesters = EvaluationCycle.objects.select_related("school").order_by("-start_date")
    if request.user.role == User.Role.LEADER:
        semesters = semesters.filter(school=request.user.school)

    if request.method == "POST":
        form = SemesterCreateForm(request.POST, user=request.user)
        if form.is_valid():
            semester = form.save()
            log_audit(
                actor=request.user,
                action="semester.created",
                entity_type="EvaluationCycle",
                entity_id=str(semester.id),
                after={
                    "school_id": semester.school_id,
                    "name": semester.name,
                    "start_date": str(semester.start_date),
                    "end_date": str(semester.end_date),
                    "is_active": semester.is_active,
                },
            )
            messages.success(request, "تمت إضافة الفصل الدراسي بنجاح.")
            return redirect("ui:semesters-manage")
    else:
        form = SemesterCreateForm(user=request.user)

    return render(request, "ui/semesters_manage.html", {"form": form, "semesters": semesters})


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


class PingView(View):
    def get(self, request: HttpRequest) -> HttpResponse:
        return HttpResponse("OK")


@login_required
def profile_page(request):
    teacher_profile = None
    try:
        teacher_profile = request.user.teacher_profile
    except Exception:
        pass
    return render(request, "ui/profile.html", {"teacher_profile": teacher_profile})
