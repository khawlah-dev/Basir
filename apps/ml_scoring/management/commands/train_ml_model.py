"""Management command to train ML scoring models.

Usage:
    python manage.py train_ml_model --algorithm xgboost
    python manage.py train_ml_model --algorithm random_forest
"""

from django.core.management.base import BaseCommand

from apps.ml_scoring.training import train_and_evaluate


class Command(BaseCommand):
    help = "Train an ML model (XGBoost or Random Forest) for teacher score prediction"

    def add_arguments(self, parser):
        parser.add_argument(
            "--algorithm",
            type=str,
            choices=["xgboost", "random_forest"],
            default="xgboost",
            help="Algorithm to use: xgboost (default) or random_forest",
        )
        parser.add_argument(
            "--test-size",
            type=float,
            default=0.2,
            help="Fraction of data to use for testing (default: 0.2)",
        )

    def handle(self, *args, **options):
        algorithm = options["algorithm"]
        test_size = options["test_size"]

        self.stdout.write(f"\n{'='*60}")
        self.stdout.write(f"  Training ML Model: {algorithm.upper()}")
        self.stdout.write(f"{'='*60}\n")

        try:
            record = train_and_evaluate(
                algorithm=algorithm,
                test_size=test_size,
            )
        except ValueError as exc:
            self.stderr.write(self.style.ERROR(f"\nError: {exc}"))
            return

        metrics = record.metrics_json
        self.stdout.write(self.style.SUCCESS(f"\n✅ Model trained successfully!"))
        self.stdout.write(f"\n  Version:       {record.version}")
        self.stdout.write(f"  Algorithm:     {record.algorithm}")
        self.stdout.write(f"  Samples:       {record.sample_count}")
        self.stdout.write(f"  Model file:    {record.model_path}")
        self.stdout.write(f"\n  📊 Metrics:")
        self.stdout.write(f"     MAE:  {metrics.get('mae', 'N/A')}")
        self.stdout.write(f"     RMSE: {metrics.get('rmse', 'N/A')}")
        self.stdout.write(f"     R²:   {metrics.get('r2', 'N/A')}")
        self.stdout.write(f"\n{'='*60}\n")
