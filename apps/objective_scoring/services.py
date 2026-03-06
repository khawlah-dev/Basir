import logging
from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import log_audit
from apps.metrics.models import TeacherMetricSnapshot

from .models import ObjectiveScore, ObjectiveScoringPolicy

logger = logging.getLogger(__name__)


def capped_linear_score(x: Decimal, target: Decimal, max_cap: Decimal) -> Decimal:
    x = max(Decimal("0"), x)
    if x <= target:
        score = Decimal("85") * (x / target)
    elif x < max_cap:
        score = Decimal("85") + Decimal("15") * ((x - target) / (max_cap - target))
    else:
        score = Decimal("100")
    return max(Decimal("0"), min(Decimal("100"), score)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def get_active_policy(for_date) -> ObjectiveScoringPolicy:
    policy = (
        ObjectiveScoringPolicy.objects.filter(is_active=True, effective_from__lte=for_date)
        .filter(effective_to__isnull=True)
        .order_by("-effective_from")
        .first()
    )
    if not policy:
        policy = (
            ObjectiveScoringPolicy.objects.filter(is_active=True, effective_from__lte=for_date, effective_to__gte=for_date)
            .order_by("-effective_from")
            .first()
        )
    if not policy:
        raise ValidationError("No active objective scoring policy for the cycle date.")
    return policy


@transaction.atomic
def compute_objective_score(*, teacher, cycle, actor=None, policy=None) -> ObjectiveScore:
    """Compute AI prediction using the trained ML model.

    Falls back to formula-based scoring if no ML model is available.
    """
    # Try ML model prediction first
    try:
        from apps.ml_scoring.prediction import get_or_predict

        ml_prediction = get_or_predict(teacher=teacher, cycle=cycle, force=True)
        ai_score = ml_prediction.ml_expected_score
        breakdown = {
            "method": "ML_MODEL",
            "model_version": str(ml_prediction.model_record.version),
            "algorithm": ml_prediction.model_record.algorithm,
            "features": ml_prediction.features_json,
            "note": "توقع استرشادي من نموذج الذكاء الاصطناعي (ML)",
        }

        objective_score, _ = ObjectiveScore.objects.update_or_create(
            teacher=teacher,
            cycle=cycle,
            defaults={
                "objective_total": ai_score,
                "breakdown_json": breakdown,
                "policy_version": f"ML-{ml_prediction.model_record.version}",
            },
        )

        log_audit(
            actor=actor,
            action="ml_prediction.computed",
            entity_type="ObjectiveScore",
            entity_id=str(objective_score.id),
            after={"ml_score": str(ai_score), "model": ml_prediction.model_record.version},
        )
        return objective_score

    except Exception as ml_err:
        logger.warning("ML prediction failed, falling back to formula: %s", ml_err)

    # Fallback: formula-based scoring
    snapshot = TeacherMetricSnapshot.objects.filter(teacher=teacher, cycle=cycle).first()
    if snapshot is None:
        raise ValidationError(
            "لا توجد بيانات مؤشرات معتمدة لهذا المعلم في هذا الفصل الدراسي. "
            "يرجى اعتماد سجل المؤشرات أولاً."
        )

    policy = policy or get_active_policy(cycle.end_date)

    pd_score = capped_linear_score(Decimal(snapshot.pd_hours), Decimal(policy.pd_target_hours), Decimal(policy.pd_max_hours))
    training_score = capped_linear_score(
        Decimal(snapshot.training_hours), Decimal(policy.training_target_hours), Decimal(policy.training_max_hours)
    )

    objective_total = (
        pd_score * Decimal(policy.pd_weight) + training_score * Decimal(policy.training_weight)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    breakdown = {
        "method": "FORMULA_FALLBACK",
        "note": "تم الحساب بالصيغة الرياضية (النموذج ML غير متاح)",
        "normalization_method": policy.normalization_method,
        "inputs": {
            "pd_hours": str(snapshot.pd_hours),
            "training_hours": str(snapshot.training_hours),
        },
        "normalized_scores": {
            "pd_score": str(pd_score),
            "training_score": str(training_score),
        },
        "weights": {
            "pd_weight": str(policy.pd_weight),
            "training_weight": str(policy.training_weight),
        },
    }

    objective_score, _ = ObjectiveScore.objects.update_or_create(
        teacher=teacher,
        cycle=cycle,
        defaults={
            "objective_total": objective_total,
            "breakdown_json": breakdown,
            "policy_version": policy.version,
        },
    )

    log_audit(
        actor=actor,
        action="objective_score.computed",
        entity_type="ObjectiveScore",
        entity_id=str(objective_score.id),
        after={"objective_total": str(objective_total), "policy_version": policy.version},
    )
    return objective_score
