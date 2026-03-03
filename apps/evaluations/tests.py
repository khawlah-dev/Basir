from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.accounts.models import User
from apps.criteria.models import EvaluationCriterion
from apps.cycles.models import EvaluationCycle
from apps.evaluations.models import EvaluationItem, ManagerEvaluation
from apps.evaluations.services import compute_manager_total_score
from apps.schools.models import School
from apps.teachers.models import Teacher


class EvaluationScoringTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(code="S1", name="School 1")
        self.manager = User.objects.create_user(username="m1", password="x", role=User.Role.LEADER, school=self.school)
        self.teacher_user = User.objects.create_user(username="t1", password="x", role=User.Role.TEACHER, school=self.school)
        self.teacher = Teacher.objects.create(user=self.teacher_user, school=self.school, employee_id="EMP1")
        self.cycle = EvaluationCycle.objects.create(
            school=self.school,
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
        )

        for i in range(1, 10):
            EvaluationCriterion.objects.create(key=f"k{i}", name=f"C{i}", weight_percent=10, order=i, is_active=True)
        for i in range(10, 12):
            EvaluationCriterion.objects.create(key=f"k{i}", name=f"C{i}", weight_percent=5, order=i, is_active=True)

    def test_manager_total_score_correctness(self):
        evaluation = ManagerEvaluation.objects.create(teacher=self.teacher, cycle=self.cycle, manager=self.manager)
        for criterion in EvaluationCriterion.objects.filter(is_active=True):
            EvaluationItem.objects.create(evaluation=evaluation, criterion=criterion, score=5)

        total, rating = compute_manager_total_score(evaluation)
        self.assertEqual(total, Decimal("100.00"))
        self.assertEqual(rating, "EXCELLENT")

    def test_requires_11_items(self):
        evaluation = ManagerEvaluation.objects.create(teacher=self.teacher, cycle=self.cycle, manager=self.manager)
        for criterion in EvaluationCriterion.objects.filter(is_active=True)[:10]:
            EvaluationItem.objects.create(evaluation=evaluation, criterion=criterion, score=4)

        with self.assertRaises(ValidationError):
            compute_manager_total_score(evaluation)
