from __future__ import annotations

from django import forms
from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.criteria.models import EvaluationCriterion
from apps.cycles.models import EvaluationCycle
from apps.evaluations.models import EvaluationItem, ManagerEvaluation, TeacherEvidence
from apps.flags_cases.models import Case
from apps.metrics.models import TeacherMetricSnapshot
from apps.schools.models import School
from apps.teachers.models import Teacher


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        single_file_clean = super().clean
        if isinstance(data, (list, tuple)):
            if not data:
                return []
            return [single_file_clean(item, initial) for item in data]
        if data:
            return [single_file_clean(data, initial)]
        return []


class MetricSnapshotForm(forms.ModelForm):
    class Meta:
        model = TeacherMetricSnapshot
        fields = ["teacher", "cycle", "pd_hours", "plans_count"]
        labels = {
            "teacher": "المعلم",
            "cycle": "الفصل الدراسي",
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
            raise ValidationError("يجب أن ينتمي المعلم والفصل الدراسي إلى نفس المدرسة.")
        return cleaned


class EvaluationCreateForm(forms.ModelForm):
    class Meta:
        model = ManagerEvaluation
        fields = ["teacher", "cycle"]
        labels = {
            "teacher": "المعلم",
            "cycle": "الفصل الدراسي",
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
        # Use custom Arabic validation message and avoid duplicate DB-level unique message.
        self._validate_unique = False
        teacher = cleaned.get("teacher")
        cycle = cleaned.get("cycle")
        if not teacher or not cycle:
            return cleaned
        if teacher.school_id != cycle.school_id:
            raise ValidationError("يجب أن ينتمي المعلم والفصل الدراسي إلى نفس المدرسة.")
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


class TeacherEvidenceForm(forms.ModelForm):
    attachments = MultipleFileField(
        required=True,
        label="المرفقات (صور/ملفات/فيديو)",
        help_text="يمكن رفع أكثر من ملف. الصيغ المدعومة: صور، PDF، Office، وفيديو.",
    )

    class Meta:
        model = TeacherEvidence
        fields = ["criterion", "evidence_text"]
        labels = {
            "criterion": "عنصر التقييم",
            "evidence_text": "وصف الشاهد",
        }
        widgets = {
            "evidence_text": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        self.teacher = kwargs.pop("teacher")
        super().__init__(*args, **kwargs)
        self.fields["criterion"].queryset = EvaluationCriterion.objects.filter(is_active=True).order_by("order")
        self.fields["attachments"].widget.attrs.update(
            {
                "multiple": True,
                "accept": ".jpg,.jpeg,.png,.gif,.webp,.pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.mp4,.mov,.avi,.mkv,.webm,.m4v",
            }
        )

    def clean(self):
        cleaned = super().clean()
        criterion = cleaned.get("criterion")
        if criterion and not criterion.is_active:
            raise ValidationError("لا يمكن إضافة شاهد لعنصر تقييم غير نشط.")
        return cleaned


class TeacherCreateForm(forms.Form):
    username = forms.CharField(max_length=150, label="اسم المستخدم")
    password = forms.CharField(widget=forms.PasswordInput, label="كلمة المرور")
    first_name = forms.CharField(max_length=150, required=False, label="الاسم الأول")
    last_name = forms.CharField(max_length=150, required=False, label="اسم العائلة")
    email = forms.EmailField(required=False, label="البريد الإلكتروني")
    school = forms.ModelChoiceField(queryset=School.objects.none(), label="المدرسة")
    employee_id = forms.CharField(max_length=50, label="الرقم الوظيفي")

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        if self.user.role == self.user.Role.ADMIN:
            self.fields["school"].queryset = School.objects.filter(is_active=True).order_by("name")
        else:
            self.fields["school"].queryset = School.objects.filter(id=self.user.school_id, is_active=True)

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError("اسم المستخدم مستخدم مسبقًا.")
        return username

    def clean_employee_id(self):
        employee_id = self.cleaned_data["employee_id"].strip()
        if Teacher.objects.filter(employee_id=employee_id).exists():
            raise ValidationError("الرقم الوظيفي مستخدم مسبقًا.")
        return employee_id

    def clean(self):
        cleaned = super().clean()
        school = cleaned.get("school")
        if self.user.role == self.user.Role.LEADER and school and school.id != self.user.school_id:
            raise ValidationError("القائد يمكنه إضافة معلمين لمدرسته فقط.")
        return cleaned


class SemesterCreateForm(forms.ModelForm):
    class Meta:
        model = EvaluationCycle
        fields = ["school", "name", "start_date", "end_date", "is_active"]
        labels = {
            "school": "المدرسة",
            "name": "اسم الفصل الدراسي",
            "start_date": "تاريخ البداية",
            "end_date": "تاريخ النهاية",
            "is_active": "نشط",
        }
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        self.user = kwargs.pop("user")
        super().__init__(*args, **kwargs)
        if self.user.role == self.user.Role.ADMIN:
            self.fields["school"].queryset = School.objects.filter(is_active=True).order_by("name")
        else:
            self.fields["school"].queryset = School.objects.filter(id=self.user.school_id, is_active=True)

    def clean(self):
        cleaned = super().clean()
        school = cleaned.get("school")
        start_date = cleaned.get("start_date")
        end_date = cleaned.get("end_date")
        if self.user.role == self.user.Role.LEADER and school and school.id != self.user.school_id:
            raise ValidationError("القائد يمكنه إضافة فصول لمدرسته فقط.")
        if start_date and end_date and end_date < start_date:
            raise ValidationError("تاريخ النهاية يجب أن يكون بعد تاريخ البداية.")
        return cleaned
