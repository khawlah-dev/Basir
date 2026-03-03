from django.test import TestCase

from apps.accounts.models import User
from apps.accounts.permissions import can_access_teacher
from apps.schools.models import School
from apps.teachers.models import Teacher


class PermissionScopeTests(TestCase):
    def setUp(self):
        self.school1 = School.objects.create(code="S1", name="School 1")
        self.school2 = School.objects.create(code="S2", name="School 2")

        self.admin = User.objects.create_user(username="admin", password="x", role=User.Role.ADMIN)
        self.leader1 = User.objects.create_user(username="leader1", password="x", role=User.Role.LEADER, school=self.school1)
        self.leader2 = User.objects.create_user(username="leader2", password="x", role=User.Role.LEADER, school=self.school2)

        self.teacher_user = User.objects.create_user(username="teacher", password="x", role=User.Role.TEACHER, school=self.school1)
        self.teacher = Teacher.objects.create(user=self.teacher_user, school=self.school1, employee_id="EMP1")

        self.other_teacher_user = User.objects.create_user(username="teacher2", password="x", role=User.Role.TEACHER, school=self.school1)
        self.other_teacher = Teacher.objects.create(user=self.other_teacher_user, school=self.school1, employee_id="EMP2")

    def test_can_access_teacher_rbac(self):
        self.assertTrue(can_access_teacher(user=self.admin, teacher=self.teacher))
        self.assertTrue(can_access_teacher(user=self.leader1, teacher=self.teacher))
        self.assertFalse(can_access_teacher(user=self.leader2, teacher=self.teacher))
        self.assertTrue(can_access_teacher(user=self.teacher_user, teacher=self.teacher))
        self.assertFalse(can_access_teacher(user=self.teacher_user, teacher=self.other_teacher))
