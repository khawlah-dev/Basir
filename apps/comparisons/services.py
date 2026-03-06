import logging
from decimal import Decimal, ROUND_HALF_UP

from django.db import transaction

from apps.audit.services import log_audit
from apps.evaluations.models import ScoreSummary
from apps.flags_cases.models import Case, Flag
from apps.objective_scoring.models import ObjectiveScore

from .models import ComparisonResult

logger = logging.getLogger(__name__)


def classify_deviation(abs_deviation: Decimal) -> str:
    if abs_deviation <= Decimal("5"):
        return ComparisonResult.DeviationLevel.NORMAL
    if abs_deviation <= Decimal("10"):
        return ComparisonResult.DeviationLevel.REVIEW
    return ComparisonResult.DeviationLevel.HIGH_RISK


def _try_ml_prediction(*, teacher, cycle):
    """Attempt to get an ML prediction. Returns (score, prediction) or (None, None)."""
    try:
        from apps.ml_scoring.prediction import get_or_predict

        prediction = get_or_predict(teacher=teacher, cycle=cycle)
        return prediction.ml_expected_score, prediction
    except Exception:
        logger.warning(
            "ML prediction failed for teacher %s cycle %s, continuing without it.",
            teacher.id, cycle.id, exc_info=True,
        )
        return None, None


@transaction.atomic
def compare_scores_and_generate_flags(*, teacher, cycle, actor=None) -> ComparisonResult:
    manager_total = ScoreSummary.objects.get(evaluation__teacher=teacher, evaluation__cycle=cycle).manager_total_score
    objective_total = ObjectiveScore.objects.get(teacher=teacher, cycle=cycle).objective_total

    deviation = (Decimal(manager_total) - Decimal(objective_total)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    level = classify_deviation(abs(deviation))

    # --- ML Prediction ---
    ml_score, ml_prediction = _try_ml_prediction(teacher=teacher, cycle=cycle)
    ml_deviation = None
    if ml_score is not None:
        ml_deviation = (Decimal(manager_total) - Decimal(ml_score)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

    comparison, _ = ComparisonResult.objects.update_or_create(
        teacher=teacher,
        cycle=cycle,
        defaults={
            "manager_total": manager_total,
            "objective_total": objective_total,
            "deviation": deviation,
            "deviation_level": level,
            "ml_expected_score": ml_score,
            "ml_deviation": ml_deviation,
        },
    )

    # --- Flags: Objective deviation ---
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
                "(based only on pd_hours and training_hours). Human review is recommended."
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

    # --- Flags: ML deviation ---
    if ml_deviation is not None:
        ml_level = classify_deviation(abs(ml_deviation))
        if ml_level in [ComparisonResult.DeviationLevel.REVIEW, ComparisonResult.DeviationLevel.HIGH_RISK]:
            ml_flag = Flag.objects.create(
                teacher=teacher,
                cycle=cycle,
                comparison=comparison,
                case=None,
                severity=ml_level,
                code=f"ML_SCORE_DEVIATION_{ml_level}",
                message=(
                    "فرق ملحوظ بين درجة المدير والدرجة المتوقعة من نموذج ML. "
                    "يُنصح بالمراجعة البشرية."
                ),
                payload_json={
                    "ml_expected_score": str(ml_score),
                    "manager_total": str(manager_total),
                    "ml_deviation": str(ml_deviation),
                    "ml_model": ml_prediction.model_record.version if ml_prediction else "",
                },
            )
            log_audit(
                actor=actor,
                action="flag.created",
                entity_type="Flag",
                entity_id=str(ml_flag.id),
                after={"severity": ml_flag.severity, "code": ml_flag.code},
            )

    log_audit(
        actor=actor,
        action="comparison.computed",
        entity_type="ComparisonResult",
        entity_id=str(comparison.id),
        after={
            "deviation": str(deviation),
            "deviation_level": level,
            "ml_expected_score": str(ml_score) if ml_score else None,
            "ml_deviation": str(ml_deviation) if ml_deviation else None,
        },
    )

    return comparison
