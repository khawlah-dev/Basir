from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction
from django.utils import timezone
from django.core.exceptions import ValidationError

from apps.audit.services import log_audit
from apps.criteria.models import EvaluationCriterion

from .models import ManagerEvaluation, ScoreSummary


def compute_manager_total_score(evaluation: ManagerEvaluation) -> tuple[Decimal, str]:
    items = list(evaluation.items.select_related("criterion"))
    if len(items) != 11:
        raise ValidationError("Evaluation must contain exactly 11 criterion scores.")

    active_criteria_count = EvaluationCriterion.objects.filter(is_active=True).count()
    if active_criteria_count != 11:
        raise ValidationError("Exactly 11 active criteria are required.")

    total_weight = sum(item.criterion.weight_percent for item in items)
    if total_weight != 100:
        raise ValidationError("Criterion weights must sum to 100.")

    total = Decimal("0")
    for item in items:
        total += (Decimal(item.score) / Decimal("5")) * Decimal(item.criterion.weight_percent)
    total = total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    rating = (
        "EXCELLENT"
        if total >= 90
        else "VERY_GOOD"
        if total >= 80
        else "GOOD"
        if total >= 70
        else "NEEDS_SUPPORT"
        if total >= 60
        else "CRITICAL_SUPPORT"
    )
    return total, rating


@transaction.atomic
def finalize_evaluation(evaluation: ManagerEvaluation, actor) -> ScoreSummary:
    if evaluation.status == ManagerEvaluation.Status.FINAL:
        raise ValidationError("Evaluation already finalized.")

    total, rating = compute_manager_total_score(evaluation)
    summary, _ = ScoreSummary.objects.update_or_create(
        evaluation=evaluation,
        defaults={"manager_total_score": total, "rating_level": rating},
    )

    before = {"status": evaluation.status, "finalized_at": evaluation.finalized_at.isoformat() if evaluation.finalized_at else None}
    evaluation.status = ManagerEvaluation.Status.FINAL
    evaluation.finalized_at = timezone.now()
    evaluation.save(update_fields=["status", "finalized_at"])

    after = {"status": evaluation.status, "finalized_at": evaluation.finalized_at.isoformat()}
    log_audit(
        actor=actor,
        action="evaluation.finalized",
        entity_type="ManagerEvaluation",
        entity_id=str(evaluation.id),
        before=before,
        after=after,
    )
    return summary
