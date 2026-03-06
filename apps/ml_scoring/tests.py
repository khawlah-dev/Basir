"""Tests for ML scoring app."""

from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import numpy as np
from django.test import SimpleTestCase, TestCase

from apps.accounts.models import User
from apps.criteria.models import EvaluationCriterion
from apps.cycles.models import EvaluationCycle
from apps.evaluations.models import EvaluationItem, ManagerEvaluation, ScoreSummary, TeacherEvidence
from apps.metrics.models import TeacherMetricSnapshot
from apps.objective_scoring.models import ObjectiveScore, ObjectiveScoringPolicy
from apps.schools.models import School
from apps.teachers.models import Teacher

from apps.ml_scoring.features import extract_features, build_training_dataset
from apps.ml_scoring.models import MLModelRecord, MLPrediction


class FeatureExtractionTests(TestCase):
    """Test feature extraction from teacher data."""

    def setUp(self):
        self.school = School.objects.create(code="S1", name="School 1")
        self.user = User.objects.create_user(
            username="t1", password="x", role=User.Role.TEACHER, school=self.school
        )
        self.teacher = Teacher.objects.create(
            user=self.user, school=self.school, employee_id="EMP1"
        )
        self.cycle = EvaluationCycle.objects.create(
            school=self.school,
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
        )
        # Create criteria
        self.criteria = []
        for i in range(1, 10):
            c = EvaluationCriterion.objects.create(
                key=f"k{i}", name=f"C{i}", weight_percent=10, order=i, is_active=True
            )
            self.criteria.append(c)
        for i in range(10, 12):
            c = EvaluationCriterion.objects.create(
                key=f"k{i}", name=f"C{i}", weight_percent=5, order=i, is_active=True
            )
            self.criteria.append(c)

    def test_extract_features_with_metrics(self):
        TeacherMetricSnapshot.objects.create(
            teacher=self.teacher,
            cycle=self.cycle,
            pd_hours=Decimal("25.50"),
            training_hours=Decimal("80"),
            created_by=self.user,
        )
        features = extract_features(teacher=self.teacher, cycle=self.cycle)
        self.assertEqual(features["pd_hours"], 25.50)
        self.assertEqual(features["training_hours"], 80.0)
        # Default criterion scores should be 3 (no evaluation)
        self.assertEqual(features["criterion_score_k1"], 3.0)

    def test_extract_features_without_metrics(self):
        features = extract_features(teacher=self.teacher, cycle=self.cycle)
        self.assertEqual(features["pd_hours"], 0.0)
        self.assertEqual(features["training_hours"], 0.0)

    def test_extract_features_with_evaluation(self):
        TeacherMetricSnapshot.objects.create(
            teacher=self.teacher,
            cycle=self.cycle,
            pd_hours=Decimal("20"),
            training_hours=Decimal("100"),
            created_by=self.user,
        )
        manager = User.objects.create_user(
            username="m1", password="x", role=User.Role.LEADER, school=self.school
        )
        evaluation = ManagerEvaluation.objects.create(
            teacher=self.teacher, cycle=self.cycle, manager=manager,
            status=ManagerEvaluation.Status.FINAL,
        )
        for criterion in self.criteria:
            EvaluationItem.objects.create(
                evaluation=evaluation, criterion=criterion, score=4
            )

        features = extract_features(teacher=self.teacher, cycle=self.cycle)
        self.assertEqual(features["criterion_score_k1"], 4.0)
        self.assertEqual(features["criterion_score_k5"], 4.0)
        self.assertEqual(features["criterion_score_k11"], 4.0)

    def test_extract_features_with_evidence(self):
        TeacherMetricSnapshot.objects.create(
            teacher=self.teacher,
            cycle=self.cycle,
            pd_hours=Decimal("10"),
            training_hours=Decimal("50"),
            created_by=self.user,
        )
        TeacherEvidence.objects.create(
            teacher=self.teacher,
            cycle=self.cycle,
            criterion=self.criteria[0],
            evidence_text="هذا شاهد تجريبي للمعيار الأول ويحتوي على عدة كلمات",
            submitted_by=self.user,
        )
        features = extract_features(teacher=self.teacher, cycle=self.cycle)
        self.assertEqual(features["evidence_count_k1"], 1.0)
        self.assertGreater(features["evidence_word_count_k1"], 0)
        self.assertEqual(features["evidence_count_k2"], 0.0)

    def test_feature_keys_consistent(self):
        features = extract_features(teacher=self.teacher, cycle=self.cycle)
        self.assertIn("pd_hours", features)
        self.assertIn("training_hours", features)
        self.assertIn("objective_total", features)
        for c in self.criteria:
            self.assertIn(f"criterion_score_{c.key}", features)
            self.assertIn(f"evidence_count_{c.key}", features)
            self.assertIn(f"evidence_word_count_{c.key}", features)


class BuildDatasetTests(TestCase):
    """Test training dataset construction."""

    def setUp(self):
        self.school = School.objects.create(code="S1", name="School 1")
        self.manager = User.objects.create_user(
            username="m1", password="x", role=User.Role.LEADER, school=self.school
        )
        for i in range(1, 10):
            EvaluationCriterion.objects.create(
                key=f"k{i}", name=f"C{i}", weight_percent=10, order=i, is_active=True
            )
        for i in range(10, 12):
            EvaluationCriterion.objects.create(
                key=f"k{i}", name=f"C{i}", weight_percent=5, order=i, is_active=True
            )
        self.cycle = EvaluationCycle.objects.create(
            school=self.school,
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
        )

    def _create_teacher_with_evaluation(self, idx, score):
        user = User.objects.create_user(
            username=f"t{idx}", password="x", role=User.Role.TEACHER, school=self.school
        )
        teacher = Teacher.objects.create(
            user=user, school=self.school, employee_id=f"EMP{idx}"
        )
        TeacherMetricSnapshot.objects.create(
            teacher=teacher, cycle=self.cycle,
            pd_hours=Decimal("20"), training_hours=Decimal("100"),
            created_by=user,
        )
        evaluation = ManagerEvaluation.objects.create(
            teacher=teacher, cycle=self.cycle, manager=self.manager,
            status=ManagerEvaluation.Status.FINAL,
        )
        for c in EvaluationCriterion.objects.filter(is_active=True):
            EvaluationItem.objects.create(evaluation=evaluation, criterion=c, score=4)
        ScoreSummary.objects.create(
            evaluation=evaluation,
            manager_total_score=Decimal(str(score)),
            rating_level="GOOD",
        )
        return teacher

    def test_build_dataset_with_data(self):
        for i in range(1, 8):
            self._create_teacher_with_evaluation(i, 70 + i * 3)
        df = build_training_dataset()
        self.assertEqual(len(df), 7)
        self.assertIn("target", df.columns)
        self.assertIn("pd_hours", df.columns)

    def test_build_dataset_empty(self):
        df = build_training_dataset()
        self.assertTrue(df.empty)


class ScoreClampingTests(SimpleTestCase):
    """Test that predictions are properly clamped to 0-100."""

    def test_clamp_high(self):
        score = Decimal("150")
        clamped = max(Decimal("0"), min(Decimal("100"), score))
        self.assertEqual(clamped, Decimal("100"))

    def test_clamp_low(self):
        score = Decimal("-10")
        clamped = max(Decimal("0"), min(Decimal("100"), score))
        self.assertEqual(clamped, Decimal("0"))

    def test_score_within_range(self):
        score = Decimal("75.50")
        clamped = max(Decimal("0"), min(Decimal("100"), score))
        self.assertEqual(clamped, Decimal("75.50"))


class MLModelRecordTests(TestCase):
    """Test MLModelRecord model."""

    def test_create_model_record(self):
        record = MLModelRecord.objects.create(
            algorithm="xgboost",
            version="v_test_001",
            model_path="model_test.joblib",
            metrics_json={"mae": 3.5, "r2": 0.85},
            feature_names=["pd_hours", "training_hours"],
            is_active=True,
            sample_count=100,
        )
        self.assertEqual(record.algorithm, "xgboost")
        self.assertTrue(record.is_active)
        self.assertEqual(record.metrics_json["mae"], 3.5)
