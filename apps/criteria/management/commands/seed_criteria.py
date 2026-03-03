from django.core.management.base import BaseCommand

from apps.criteria.models import EvaluationCriterion


DEFAULT_CRITERIA = [
    ("domain_knowledge", "Domain Knowledge", 10),
    ("planning_quality", "Planning Quality", 10),
    ("instruction_delivery", "Instruction Delivery", 10),
    ("classroom_management", "Classroom Management", 10),
    ("student_engagement", "Student Engagement", 10),
    ("assessment_use", "Assessment Use", 10),
    ("communication", "Communication", 10),
    ("collaboration", "Collaboration", 10),
    ("professionalism", "Professionalism", 10),
    ("attendance", "Attendance", 5),
    ("timely_reporting", "Timely Reporting", 5),
]


class Command(BaseCommand):
    help = "Seed the fixed 11 evaluation criteria (9x10% + 2x5%)."

    def handle(self, *args, **options):
        if len(DEFAULT_CRITERIA) != 11:
            raise ValueError("Expected 11 criteria")

        total_weight = sum(weight for _, _, weight in DEFAULT_CRITERIA)
        if total_weight != 100:
            raise ValueError("Criteria weights must sum to 100")

        for idx, (key, name, weight) in enumerate(DEFAULT_CRITERIA, start=1):
            EvaluationCriterion.objects.update_or_create(
                key=key,
                defaults={
                    "name": name,
                    "weight_percent": weight,
                    "order": idx,
                    "is_active": True,
                },
            )

        self.stdout.write(self.style.SUCCESS("Criteria seeded successfully."))
