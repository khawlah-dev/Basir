from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from apps.criteria.models import EvaluationCriterion
from apps.cycles.models import EvaluationCycle
from apps.evaluations.models import EvaluationItem, ManagerEvaluation
from apps.flags_cases.models import Case
from apps.metrics.models import TeacherMetricSnapshot
from apps.teachers.models import Teacher


class MetricSnapshotForm(forms.ModelForm):
    class Meta:
        model = TeacherMetricSnapshot
        fields = ["teacher", "cycle", "pd_hours", "plans_count"]
        labels = {
            "teacher": "المعلم",
            "cycle": "دورة التقييم",
            "pd_hours": "ساعات التطوير المهني",
            "plans_count": "عدد التحضيرات/الخطط",
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)

        teacher_qs = Teacher.objects.select_related("user", "school")
        cycle_qs = EvaluationCycle.objects.select_related("school")

        role = getattr(self.user, "role", None)
        if role == self.user.Role.TEACHER:
            teacher_qs = teacher_qs.filter(user=self.user)
            cycle_qs = cycle_qs.filter(school=self.user.school)
        elif role == self.user.Role.LEADER:
            teacher_qs = teacher_qs.filter(school=self.user.school)
            cycle_qs = cycle_qs.filter(school=self.user.school)

        self.fields["teacher"].queryset = teacher_qs
        self.fields["cycle"].queryset = cycle_qs

    def clean(self):
        cleaned = super().clean()
        teacher = cleaned.get("teacher")
        cycle = cleaned.get("cycle")
        if teacher and cycle and teacher.school_id != cycle.school_id:
            raise ValidationError("يجب أن ينتمي المعلم ودورة التقييم إلى نفس المدرسة.")
        return cleaned


class EvaluationCreateForm(forms.ModelForm):
    class Meta:
        model = ManagerEvaluation
        fields = ["teacher", "cycle"]
        labels = {
            "teacher": "المعلم",
            "cycle": "دورة التقييم",
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        teacher_qs = Teacher.objects.select_related("user", "school")
        cycle_qs = EvaluationCycle.objects.select_related("school")
        if self.user.role == self.user.Role.LEADER:
            teacher_qs = teacher_qs.filter(school=self.user.school)
            cycle_qs = cycle_qs.filter(school=self.user.school)
        self.fields["teacher"].queryset = teacher_qs
        self.fields["cycle"].queryset = cycle_qs

    def clean(self):
        cleaned = super().clean()
        teacher = cleaned.get("teacher")
        cycle = cleaned.get("cycle")
        if not teacher or not cycle:
            return cleaned
        if teacher.school_id != cycle.school_id:
            raise ValidationError("يجب أن ينتمي المعلم ودورة التقييم إلى نفس المدرسة.")
        if ManagerEvaluation.objects.filter(teacher=teacher, cycle=cycle).exists():
            raise ValidationError("يوجد تقييم مسبق لهذا المعلم في نفس دورة التقييم.")
        return cleaned


class EvaluationItemsForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.evaluation = kwargs.pop("evaluation")
        super().__init__(*args, **kwargs)

        existing = {
            item.criterion_id: item.score
            for item in self.evaluation.items.select_related("criterion").all()
        }
        for criterion in EvaluationCriterion.objects.filter(is_active=True).order_by("order"):
            field_name = f"criterion_{criterion.id}"
            self.fields[field_name] = forms.IntegerField(
                min_value=1,
                max_value=5,
                required=True,
                initial=existing.get(criterion.id),
                label=f"{criterion.order}. {criterion.name} (الوزن {criterion.weight_percent}%)",
            )

    def save(self):
        for field_name, value in self.cleaned_data.items():
            criterion_id = int(field_name.split("_", 1)[1])
            EvaluationItem.objects.update_or_create(
                evaluation=self.evaluation,
                criterion_id=criterion_id,
                defaults={"score": value},
            )


class CaseCloseForm(forms.ModelForm):
    class Meta:
        model = Case
        fields = ["decision_note"]
        labels = {
            "decision_note": "ملاحظة القرار",
        }
        widgets = {
            "decision_note": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_decision_note(self):
        text = self.cleaned_data["decision_note"].strip()
        if not text:
            raise ValidationError("ملاحظة القرار مطلوبة.")
        return text
