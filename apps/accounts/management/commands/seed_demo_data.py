from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.management import BaseCommand, call_command
from django.db import transaction

from apps.accounts.models import User
from apps.comparisons.services import compare_scores_and_generate_flags
from apps.cycles.models import EvaluationCycle
from apps.evaluations.models import EvaluationItem, ManagerEvaluation, ScoreSummary
from apps.evaluations.services import finalize_evaluation
from apps.flags_cases.models import Case, Flag
from apps.metrics.models import TeacherMetricSnapshot
from apps.objective_scoring.models import ObjectiveScoringPolicy
from apps.objective_scoring.services import compute_objective_score
from apps.schools.models import School
from apps.teachers.models import Teacher
from apps.criteria.models import EvaluationCriterion


class Command(BaseCommand):
    help = (
        "Seed sample demo data (schools, users, teachers, cycles, policy, metrics, evaluations). "
        "All seeded records are prefixed with DEMO for safe separation."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            default="Demo@12345",
            help="Password to assign to all demo users.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        demo_password = options["password"]

        call_command("seed_criteria")

        north_school, _ = School.objects.update_or_create(
            code="DEMO-NORTH",
            defaults={"name": "Demo North School", "is_active": True},
        )
        south_school, _ = School.objects.update_or_create(
            code="DEMO-SOUTH",
            defaults={"name": "Demo South School", "is_active": True},
        )

        admin = self._create_or_update_user(
            username="demo_admin",
            password=demo_password,
            role=User.Role.ADMIN,
            school=None,
            first_name="Demo",
            last_name="Admin",
            is_staff=True,
            is_superuser=True,
        )

        north_leader = self._create_or_update_user(
            username="demo_leader_north",
            password=demo_password,
            role=User.Role.LEADER,
            school=north_school,
            first_name="North",
            last_name="Leader",
            is_staff=True,
            is_superuser=False,
        )

        south_leader = self._create_or_update_user(
            username="demo_leader_south",
            password=demo_password,
            role=User.Role.LEADER,
            school=south_school,
            first_name="South",
            last_name="Leader",
            is_staff=True,
            is_superuser=False,
        )

        t_n1_user = self._create_or_update_user(
            username="demo_teacher_n1",
            password=demo_password,
            role=User.Role.TEACHER,
            school=north_school,
            first_name="Nora",
            last_name="Ahmad",
            is_staff=False,
            is_superuser=False,
        )
        t_n2_user = self._create_or_update_user(
            username="demo_teacher_n2",
            password=demo_password,
            role=User.Role.TEACHER,
            school=north_school,
            first_name="Salem",
            last_name="Omar",
            is_staff=False,
            is_superuser=False,
        )
        t_s1_user = self._create_or_update_user(
            username="demo_teacher_s1",
            password=demo_password,
            role=User.Role.TEACHER,
            school=south_school,
            first_name="Huda",
            last_name="Ali",
            is_staff=False,
            is_superuser=False,
        )
        t_s2_user = self._create_or_update_user(
            username="demo_teacher_s2",
            password=demo_password,
            role=User.Role.TEACHER,
            school=south_school,
            first_name="Rami",
            last_name="Yousef",
            is_staff=False,
            is_superuser=False,
        )

        t_n1, _ = Teacher.objects.update_or_create(
            employee_id="DEMO-T001",
            defaults={"user": t_n1_user, "school": north_school, "is_active": True},
        )
        t_n2, _ = Teacher.objects.update_or_create(
            employee_id="DEMO-T002",
            defaults={"user": t_n2_user, "school": north_school, "is_active": True},
        )
        t_s1, _ = Teacher.objects.update_or_create(
            employee_id="DEMO-T003",
            defaults={"user": t_s1_user, "school": south_school, "is_active": True},
        )
        t_s2, _ = Teacher.objects.update_or_create(
            employee_id="DEMO-T004",
            defaults={"user": t_s2_user, "school": south_school, "is_active": True},
        )

        cycle_north, _ = EvaluationCycle.objects.update_or_create(
            school=north_school,
            name="DEMO 2025-2026",
            defaults={
                "start_date": date(2025, 9, 1),
                "end_date": date(2026, 6, 30),
                "is_active": True,
            },
        )
        cycle_south, _ = EvaluationCycle.objects.update_or_create(
            school=south_school,
            name="DEMO 2025-2026",
            defaults={
                "start_date": date(2025, 9, 1),
                "end_date": date(2026, 6, 30),
                "is_active": True,
            },
        )

        ObjectiveScoringPolicy.objects.update_or_create(
            version="v1.0.0",
            defaults={
                "is_active": True,
                "normalization_method": "CAPPED_LINEAR_V1",
                "pd_weight": Decimal("0.45"),
                "plans_weight": Decimal("0.55"),
                "pd_target_hours": Decimal("20"),
                "pd_max_hours": Decimal("40"),
                "plans_target_count": 100,
                "plans_max_count": 150,
                "effective_from": date(2025, 1, 1),
                "effective_to": None,
            },
        )

        criteria = list(EvaluationCriterion.objects.filter(is_active=True).order_by("order"))
        if len(criteria) != 11:
            raise ValueError("Expected 11 active criteria. Run seed_criteria first.")

        scenarios = [
            {
                "teacher": t_n1,
                "cycle": cycle_north,
                "leader": north_leader,
                "pd_hours": Decimal("20"),
                "plans_count": 100,
                "scores": [5, 5, 4, 4, 4, 4, 4, 4, 4, 4, 4],
            },
            {
                "teacher": t_n2,
                "cycle": cycle_north,
                "leader": north_leader,
                "pd_hours": Decimal("8"),
                "plans_count": 55,
                "scores": [3, 4, 4, 4, 4, 4, 4, 4, 4, 4, 4],
            },
            {
                "teacher": t_s1,
                "cycle": cycle_south,
                "leader": south_leader,
                "pd_hours": Decimal("18"),
                "plans_count": 90,
                "scores": [5, 5, 4, 4, 4, 4, 4, 4, 4, 4, 4],
            },
            {
                "teacher": t_s2,
                "cycle": cycle_south,
                "leader": south_leader,
                "pd_hours": Decimal("35"),
                "plans_count": 140,
                "scores": [3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
            },
        ]

        for scenario in scenarios:
            teacher = scenario["teacher"]
            cycle = scenario["cycle"]
            leader = scenario["leader"]

            TeacherMetricSnapshot.objects.update_or_create(
                teacher=teacher,
                cycle=cycle,
                defaults={
                    "pd_hours": scenario["pd_hours"],
                    "plans_count": scenario["plans_count"],
                    "created_by": leader,
                },
            )

            evaluation, _ = ManagerEvaluation.objects.update_or_create(
                teacher=teacher,
                cycle=cycle,
                defaults={
                    "manager": leader,
                    "status": ManagerEvaluation.Status.DRAFT,
                    "finalized_at": None,
                },
            )

            evaluation.items.all().delete()
            ScoreSummary.objects.filter(evaluation=evaluation).delete()

            for criterion, score in zip(criteria, scenario["scores"], strict=True):
                EvaluationItem.objects.create(
                    evaluation=evaluation,
                    criterion=criterion,
                    score=score,
                )

            finalize_evaluation(evaluation, actor=leader)
            compute_objective_score(teacher=teacher, cycle=cycle, actor=leader)

            Flag.objects.filter(teacher=teacher, cycle=cycle).delete()
            Case.objects.filter(teacher=teacher, cycle=cycle).delete()
            compare_scores_and_generate_flags(teacher=teacher, cycle=cycle, actor=leader)

        self.stdout.write(self.style.SUCCESS("Demo seed completed successfully."))
        self.stdout.write("Demo users (all use the same password):")
        self.stdout.write(f"- demo_admin / {demo_password}")
        self.stdout.write(f"- demo_leader_north / {demo_password}")
        self.stdout.write(f"- demo_leader_south / {demo_password}")
        self.stdout.write(f"- demo_teacher_n1 / {demo_password}")
        self.stdout.write(f"- demo_teacher_n2 / {demo_password}")
        self.stdout.write(f"- demo_teacher_s1 / {demo_password}")
        self.stdout.write(f"- demo_teacher_s2 / {demo_password}")

    def _create_or_update_user(
        self,
        *,
        username: str,
        password: str,
        role: str,
        school,
        first_name: str,
        last_name: str,
        is_staff: bool,
        is_superuser: bool,
    ) -> User:
        user, _ = User.objects.update_or_create(
            username=username,
            defaults={
                "role": role,
                "school": school,
                "first_name": first_name,
                "last_name": last_name,
                "is_staff": is_staff,
                "is_superuser": is_superuser,
                "is_active": True,
                "email": f"{username}@demo.local",
            },
        )
        user.set_password(password)
        user.save(update_fields=["password"])
        return user
