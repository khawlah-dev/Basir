from django.core.management.base import BaseCommand

from apps.criteria.models import EvaluationCriterion


DEFAULT_CRITERIA = [
    ("domain_knowledge", "أداء الواجبات الوظيفية", 10),
    ("planning_quality", "التفاعل مع المجتمع المهني", 10),
    ("instruction_delivery", "التفاعل مع أولياء الأمور", 10),
    ("classroom_management", "التنويع في استراتيجيات التدريس", 10),
    ("student_engagement", "تحسين نتائج المتعلمين", 10),
    ("assessment_use", "إعداد وتنفيذ خطة التعلم", 10),
    ("communication", "توظيف تقنيات ووسائل التعلم المناسبة", 10),
    ("collaboration", "تهيئة بيئة تعليمية", 10),
    ("professionalism", "الإدارة الصفية", 10),
    ("attendance", "تحليل نتائج المتعلمين وتشخيص مستوياتهم", 5),
    ("timely_reporting", "تنوع أساليب التقويم", 5),
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
