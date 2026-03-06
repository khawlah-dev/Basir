"""Feature extraction for ML scoring.

Extracts numerical features from teacher evaluation data
for use in training and prediction.
"""

import logging

from apps.criteria.models import EvaluationCriterion
from apps.evaluations.models import EvaluationItem, ManagerEvaluation, ScoreSummary, TeacherEvidence
from apps.metrics.models import TeacherMetricSnapshot
from apps.objective_scoring.models import ObjectiveScore

logger = logging.getLogger(__name__)


def _get_active_criteria_keys() -> list[str]:
    """Return ordered list of active criterion keys."""
    return list(
        EvaluationCriterion.objects.filter(is_active=True)
        .order_by("order")
        .values_list("key", flat=True)
    )


def extract_features(*, teacher, cycle) -> dict:
    """Build feature dict for a single teacher/cycle pair.

    Features:
    - pd_hours: Professional development hours
    - training_hours: Training hours
    - criterion_score_{key}: Manager-assigned score (1-5) per criterion
    - evidence_count_{key}: Number of evidence items per criterion
    - evidence_word_count_{key}: Total word count of evidence per criterion
    - objective_total: Formula-based objective score (0-100)

    Returns:
        dict of feature_name -> float value
    """
    features = {}
    criteria_keys = _get_active_criteria_keys()

    # --- Metrics ---
    try:
        metrics = TeacherMetricSnapshot.objects.get(teacher=teacher, cycle=cycle)
        features["pd_hours"] = float(metrics.pd_hours)
        features["training_hours"] = float(metrics.training_hours)
    except TeacherMetricSnapshot.DoesNotExist:
        features["pd_hours"] = 0.0
        features["training_hours"] = 0.0

    # --- Criterion scores from manager evaluation ---
    evaluation = (
        ManagerEvaluation.objects.filter(
            teacher=teacher, cycle=cycle, status=ManagerEvaluation.Status.FINAL
        )
        .first()
    )
    items_by_key = {}
    if evaluation:
        items = EvaluationItem.objects.filter(evaluation=evaluation).select_related("criterion")
        items_by_key = {item.criterion.key: item.score for item in items}

    for key in criteria_keys:
        features[f"criterion_score_{key}"] = float(items_by_key.get(key, 3))

    # --- Evidence features ---
    evidences = (
        TeacherEvidence.objects.filter(teacher=teacher, cycle=cycle)
        .select_related("criterion")
    )
    evidence_counts = {}
    evidence_word_counts = {}
    for ev in evidences:
        k = ev.criterion.key
        evidence_counts[k] = evidence_counts.get(k, 0) + 1
        word_count = len(ev.evidence_text.split()) if ev.evidence_text else 0
        evidence_word_counts[k] = evidence_word_counts.get(k, 0) + word_count

    for key in criteria_keys:
        features[f"evidence_count_{key}"] = float(evidence_counts.get(key, 0))
        features[f"evidence_word_count_{key}"] = float(evidence_word_counts.get(key, 0))

    # --- Objective score ---
    try:
        obj_score = ObjectiveScore.objects.get(teacher=teacher, cycle=cycle)
        features["objective_total"] = float(obj_score.objective_total)
    except ObjectiveScore.DoesNotExist:
        features["objective_total"] = 0.0

    return features


def build_training_dataset():
    """Build a pandas DataFrame with features + target for all finalized evaluations.

    Target: manager_total_score from ScoreSummary.

    Returns:
        pandas.DataFrame with columns = feature names + 'target'
    """
    import pandas as pd

    rows = []
    summaries = (
        ScoreSummary.objects.select_related(
            "evaluation", "evaluation__teacher", "evaluation__cycle"
        )
        .filter(evaluation__status=ManagerEvaluation.Status.FINAL)
    )

    for summary in summaries:
        teacher = summary.evaluation.teacher
        cycle = summary.evaluation.cycle
        try:
            features = extract_features(teacher=teacher, cycle=cycle)
            features["target"] = float(summary.manager_total_score)
            rows.append(features)
        except Exception:
            logger.warning(
                "Skipping teacher %s cycle %s due to feature extraction error",
                teacher.id, cycle.id, exc_info=True,
            )

    if not rows:
        logger.warning("No training data found. Ensure finalized evaluations exist.")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    logger.info("Built training dataset with %d rows and %d columns", len(df), len(df.columns))
    return df
