from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static
from rest_framework.routers import DefaultRouter

from apps.metrics.views import TeacherMetricSnapshotViewSet
from apps.evaluations.views import ManagerEvaluationViewSet, TeacherEvidenceViewSet
from apps.objective_scoring.views import ObjectiveScoreViewSet
from apps.comparisons.views import ComparisonResultViewSet
from apps.flags_cases.views import FlagViewSet, CaseViewSet

router = DefaultRouter()
router.register("metrics/snapshots", TeacherMetricSnapshotViewSet, basename="metric-snapshot")
router.register("evaluations", ManagerEvaluationViewSet, basename="evaluation")
router.register("evidences", TeacherEvidenceViewSet, basename="evidence")
router.register("objective-scores", ObjectiveScoreViewSet, basename="objective-score")
router.register("comparisons", ComparisonResultViewSet, basename="comparison")
router.register("flags", FlagViewSet, basename="flag")
router.register("cases", CaseViewSet, basename="case")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("apps.ui.urls")),
    path("api/v1/auth/", include("apps.accounts.urls")),
    path("api/v1/", include(router.urls)),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
