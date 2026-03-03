from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from apps.audit.services import log_audit
from apps.evaluations.models import ScoreSummary
from apps.flags_cases.models import Case, Flag
from apps.objective_scoring.models import ObjectiveScore

from .models import ComparisonResult


def classify_deviation(abs_deviation: Decimal) -> str:
    if abs_deviation <= Decimal("5"):
        return ComparisonResult.DeviationLevel.NORMAL
    if abs_deviation <= Decimal("10"):
        return ComparisonResult.DeviationLevel.REVIEW
    return ComparisonResult.DeviationLevel.HIGH_RISK


@transaction.atomic
def compare_scores_and_generate_flags(*, teacher, cycle, actor=None) -> ComparisonResult:
    manager_total = ScoreSummary.objects.get(evaluation__teacher=teacher, evaluation__cycle=cycle).manager_total_score
    objective_total = ObjectiveScore.objects.get(teacher=teacher, cycle=cycle).objective_total

    deviation = (Decimal(manager_total) - Decimal(objective_total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    level = classify_deviation(abs(deviation))

    comparison, _ = ComparisonResult.objects.update_or_create(
        teacher=teacher,
        cycle=cycle,
        defaults={
            "manager_total": manager_total,
            "objective_total": objective_total,
            "deviation": deviation,
            "deviation_level": level,
        },
    )

    if level in [ComparisonResult.DeviationLevel.REVIEW, ComparisonResult.DeviationLevel.HIGH_RISK]:
        case = None
        if level == ComparisonResult.DeviationLevel.HIGH_RISK:
            case, _ = Case.objects.get_or_create(
                teacher=teacher,
                cycle=cycle,
                status__in=[Case.Status.OPEN, Case.Status.IN_REVIEW],
                defaults={
                    "teacher": teacher,
                    "cycle": cycle,
                    "opened_by": actor or teacher.user,
                },
            )

        flag = Flag.objects.create(
            teacher=teacher,
            cycle=cycle,
            comparison=comparison,
            case=case,
            severity=level,
            code=f"SCORE_DEVIATION_{level}",
            message=(
                "Difference detected between manager score and partial objective score "
                "(based only on pd_hours and plans_count). Human review is recommended."
            ),
            payload_json={
                "deviation": str(deviation),
                "thresholds": {"normal": 5, "review": 10},
            },
        )

        log_audit(
            actor=actor,
            action="flag.created",
            entity_type="Flag",
            entity_id=str(flag.id),
            after={"severity": flag.severity, "code": flag.code},
        )

    log_audit(
        actor=actor,
        action="comparison.computed",
        entity_type="ComparisonResult",
        entity_id=str(comparison.id),
        after={"deviation": str(deviation), "deviation_level": level},
    )

    return comparison
