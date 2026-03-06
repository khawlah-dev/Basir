from datetime import date

from django.test import TestCase
from rest_framework.test import APIRequestFactory, force_authenticate

from apps.accounts.models import User
from apps.cycles.models import EvaluationCycle
from apps.metrics.models import TeacherMetricSnapshot
from apps.metrics.views import TeacherMetricSnapshotViewSet
from apps.schools.models import School
from apps.teachers.models import Teacher


class TeacherMetricSnapshotViewSetTests(TestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.school = School.objects.create(code="SM1", name="School Metrics")
        self.teacher_user = User.objects.create_user(
            username="teacher_metrics", password="x", role=User.Role.TEACHER, school=self.school
        )
        self.leader_user = User.objects.create_user(
            username="leader_metrics", password="x", role=User.Role.LEADER, school=self.school
        )
        self.teacher = Teacher.objects.create(user=self.teacher_user, school=self.school, employee_id="EMP-M1")
        self.cycle = EvaluationCycle.objects.create(
            school=self.school,
            name="2025-2026",
            start_date=date(2025, 9, 1),
            end_date=date(2026, 6, 30),
            is_active=True,
        )

    def test_teacher_can_submit_metrics(self):
        view = TeacherMetricSnapshotViewSet.as_view({"post": "create"})
        request = self.factory.post(
            "/api/v1/metrics/snapshots/",
            {
                "teacher": self.teacher.id,
                "cycle": self.cycle.id,
                "pd_hours": "14.50",
                "training_hours": "6.00",
            },
        )
        force_authenticate(request, user=self.teacher_user)
        response = view(request)
        self.assertEqual(response.status_code, 201)
        snapshot = TeacherMetricSnapshot.objects.get(teacher=self.teacher, cycle=self.cycle)
        self.assertEqual(snapshot.approval_status, TeacherMetricSnapshot.ApprovalStatus.PENDING)
        self.assertIsNone(snapshot.approved_by)
        self.assertIsNone(snapshot.approved_at)

    def test_leader_cannot_submit_metrics(self):
        view = TeacherMetricSnapshotViewSet.as_view({"post": "create"})
        request = self.factory.post(
            "/api/v1/metrics/snapshots/",
            {
                "teacher": self.teacher.id,
                "cycle": self.cycle.id,
                "pd_hours": "12.00",
                "training_hours": "4.00",
            },
        )
        force_authenticate(request, user=self.leader_user)
        response = view(request)
        self.assertEqual(response.status_code, 403)

    def test_leader_can_approve_metrics(self):
        snapshot = TeacherMetricSnapshot.objects.create(
            teacher=self.teacher,
            cycle=self.cycle,
            pd_hours="10.00",
            training_hours="3.00",
            created_by=self.teacher_user,
            approval_status=TeacherMetricSnapshot.ApprovalStatus.PENDING,
        )
        view = TeacherMetricSnapshotViewSet.as_view({"post": "approve"})
        request = self.factory.post(f"/api/v1/metrics/snapshots/{snapshot.id}/approve/")
        force_authenticate(request, user=self.leader_user)
        response = view(request, pk=snapshot.id)
        self.assertEqual(response.status_code, 200)
        snapshot.refresh_from_db()
        self.assertEqual(snapshot.approval_status, TeacherMetricSnapshot.ApprovalStatus.APPROVED)
        self.assertEqual(snapshot.approved_by_id, self.leader_user.id)
        self.assertIsNotNone(snapshot.approved_at)

    def test_teacher_cannot_approve_metrics(self):
        snapshot = TeacherMetricSnapshot.objects.create(
            teacher=self.teacher,
            cycle=self.cycle,
            pd_hours="10.00",
            training_hours="3.00",
            created_by=self.teacher_user,
            approval_status=TeacherMetricSnapshot.ApprovalStatus.PENDING,
        )
        view = TeacherMetricSnapshotViewSet.as_view({"post": "approve"})
        request = self.factory.post(f"/api/v1/metrics/snapshots/{snapshot.id}/approve/")
        force_authenticate(request, user=self.teacher_user)
        response = view(request, pk=snapshot.id)
        self.assertEqual(response.status_code, 403)
