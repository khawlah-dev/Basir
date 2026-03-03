from decimal import Decimal

from django.test import SimpleTestCase

from apps.comparisons.models import ComparisonResult
from apps.comparisons.services import classify_deviation


class ComparisonClassificationTests(SimpleTestCase):
    def test_deviation_classification(self):
        self.assertEqual(classify_deviation(Decimal("0")), ComparisonResult.DeviationLevel.NORMAL)
        self.assertEqual(classify_deviation(Decimal("5")), ComparisonResult.DeviationLevel.NORMAL)
        self.assertEqual(classify_deviation(Decimal("5.01")), ComparisonResult.DeviationLevel.REVIEW)
        self.assertEqual(classify_deviation(Decimal("10")), ComparisonResult.DeviationLevel.REVIEW)
        self.assertEqual(classify_deviation(Decimal("10.01")), ComparisonResult.DeviationLevel.HIGH_RISK)
