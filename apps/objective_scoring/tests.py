from decimal import Decimal
from datetime import date

from django.test import TestCase

from apps.accounts.models import User
from apps.cycles.models import EvaluationCycle
from apps.metrics.models import TeacherMetricSnapshot
from apps.objective_scoring.models import ObjectiveScoringPolicy
from apps.objective_scoring.services import capped_linear_score, compute_objective_score
from apps.schools.models import School
from apps.teachers.models import Teacher


class ObjectiveScoringTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(code="S1", name="School 1")
        self.user = User.objects.create_user(username="t1", password="x", role=User.Role.TEACHER, school=self.school)
        self.teacher = Teacher.objects.create(user=self.user, school=self.school, employee_id="EMP1")
        self.cycle = EvaluationCycle.objects.create(
            school=self.school,
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
        )
        self.policy = ObjectiveScoringPolicy.objects.create(
            version="v1.0.0",
            is_active=True,
            normalization_method="CAPPED_LINEAR_V1",
            pd_weight=Decimal("0.45"),
            training_weight=Decimal("0.55"),
            pd_target_hours=Decimal("20"),
            pd_max_hours=Decimal("40"),
            training_target_hours=Decimal("100"),
            training_max_hours=Decimal("150"),
            effective_from=date(2025, 1, 1),
        )

    def test_capped_linear_boundaries(self):
        self.assertEqual(capped_linear_score(Decimal("0"), Decimal("20"), Decimal("40")), Decimal("0.00"))
        self.assertEqual(capped_linear_score(Decimal("20"), Decimal("20"), Decimal("40")), Decimal("85.00"))
        self.assertEqual(capped_linear_score(Decimal("40"), Decimal("20"), Decimal("40")), Decimal("100.00"))
        self.assertEqual(capped_linear_score(Decimal("200"), Decimal("20"), Decimal("40")), Decimal("100.00"))

    def test_objective_total_weighted_sum(self):
        TeacherMetricSnapshot.objects.create(
            teacher=self.teacher,
            cycle=self.cycle,
            pd_hours=Decimal("20"),
            training_hours=Decimal("100"),
            created_by=self.user,
        )
        result = compute_objective_score(teacher=self.teacher, cycle=self.cycle, policy=self.policy, actor=self.user)
        # both metrics at target => both are 85, weighted total remains 85
        self.assertEqual(result.objective_total, Decimal("85.00"))
        self.assertEqual(result.policy_version, "v1.0.0")
        self.assertEqual(result.breakdown_json["score_scope"], "PARTIAL_OBJECTIVE_SCORE")
