from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = "ui"

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", auth_views.LoginView.as_view(template_name="registration/login.html"), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("ping/", views.PingView.as_view(), name="ping"),
    path("metrics/", views.metrics_page, name="metrics"),
    path("evidences/", views.evidences_page, name="evidences"),
    path("evidences/admin/", views.evidences_admin_page, name="evidences-admin"),
    path("evidences/<int:evidence_id>/delete/", views.evidence_delete, name="evidence-delete"),
    path("objective-scores/", views.objective_scores_page, name="objective-scores"),
    path(
        "objective-scores/recompute/<int:teacher_id>/<int:cycle_id>/",
        views.objective_recompute,
        name="objective-recompute",
    ),
    path("evaluations/", views.evaluations_page, name="evaluations"),
    path("evaluations/start/<int:teacher_id>/", views.evaluation_start, name="evaluation-start"),
    path("evaluations/<int:evaluation_id>/items/", views.evaluation_items_page, name="evaluation-items"),
    path("evaluations/<int:evaluation_id>/finalize/", views.evaluation_finalize, name="evaluation-finalize"),
    path("comparisons/", views.comparisons_page, name="comparisons"),
    path("flags/", views.flags_page, name="flags"),
    path("cases/", views.cases_page, name="cases"),
    path("teachers/manage/", views.teachers_manage_page, name="teachers-manage"),
    path("semesters/manage/", views.semesters_manage_page, name="semesters-manage"),
    path("cases/<int:case_id>/close/", views.case_close_page, name="case-close"),
    path("profile/", views.profile_page, name="profile"),
]
