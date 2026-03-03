from decimal import Decimal, ROUND_HALF_UP

from django.core.exceptions import ValidationError
from django.db import transaction

from apps.audit.services import log_audit
from apps.metrics.models import TeacherMetricSnapshot

from .models import ObjectiveScore, ObjectiveScoringPolicy


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
def compute_objective_score(*, teacher, cycle, actor=None, policy: ObjectiveScoringPolicy | None = None) -> ObjectiveScore:
    snapshot = TeacherMetricSnapshot.objects.get(teacher=teacher, cycle=cycle)
    policy = policy or get_active_policy(cycle.end_date)

    pd_score = capped_linear_score(Decimal(snapshot.pd_hours), Decimal(policy.pd_target_hours), Decimal(policy.pd_max_hours))
    plans_score = capped_linear_score(
        Decimal(snapshot.plans_count), Decimal(policy.plans_target_count), Decimal(policy.plans_max_count)
    )

    objective_total = (
        pd_score * Decimal(policy.pd_weight) + plans_score * Decimal(policy.plans_weight)
    ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    breakdown = {
        "score_scope": "PARTIAL_OBJECTIVE_SCORE",
        "disclaimer": "Partial objective score computed from pd_hours and plans_count only.",
        "normalization_method": policy.normalization_method,
        "inputs": {
            "pd_hours": str(snapshot.pd_hours),
            "plans_count": snapshot.plans_count,
        },
        "normalized_scores": {
            "pd_score": str(pd_score),
            "plans_score": str(plans_score),
        },
        "weights": {
            "pd_weight": str(policy.pd_weight),
            "plans_weight": str(policy.plans_weight),
        },
        "formula": "objective_total = pd_score*pd_weight + plans_score*plans_weight",
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
