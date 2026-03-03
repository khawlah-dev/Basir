# Teacher Evaluation MVP (Django + DRF)

This MVP computes:
- Manager weighted score (11 fixed criteria)
- **Partial Objective Score** from **only** `pd_hours` and `plans_count`
- Deviation classification and neutral flags/cases for human review

## Scope disclaimer
The objective score in this MVP is intentionally **partial**. It does not measure all criteria and does not evaluate evidence quality.

## Apps
- `apps.accounts` (JWT + RBAC)
- `apps.schools`
- `apps.teachers`
- `apps.cycles`
- `apps.criteria`
- `apps.metrics`
- `apps.evaluations`
- `apps.objective_scoring`
- `apps.comparisons`
- `apps.flags_cases`
- `apps.audit`

## Policy
`ObjectiveScoringPolicy` (versioned) includes:
- `pd_weight`, `plans_weight` (must sum to `1.00`)
- `pd_target_hours`, `pd_max_hours`
- `plans_target_count`, `plans_max_count`
- method: `CAPPED_LINEAR_V1`

## Deviation Levels
- `ABS(deviation) <= 5` => `NORMAL`
- `5 < ABS(deviation) <= 10` => `REVIEW`
- `ABS(deviation) > 10` => `HIGH_RISK`

## Setup
1. Create virtual environment and install deps from `requirements.txt`.
2. Configure database env vars for PostgreSQL (`DB_ENGINE=django.db.backends.postgresql`, etc.).
3. Run migrations.
4. Seed criteria:
   - `python manage.py seed_criteria`
5. (Optional) Seed full demo fixtures:
   - `python manage.py seed_demo_data`
   - Default demo password: `Demo@12345`

## API Base
- `/api/v1/auth/token/`
- `/api/v1/metrics/snapshots/`
- `/api/v1/evaluations/`
- `/api/v1/objective-scores/`
- `/api/v1/comparisons/`
- `/api/v1/flags/`
- `/api/v1/cases/`

## Web UI
- `/login/` session login page
- `/` role-based dashboard
- `/metrics/` metric snapshots form/list
- `/objective-scores/` objective totals (partial-score disclaimer shown)
- `/evaluations/` create/edit/finalize manager evaluations (leader/admin)
- `/comparisons/` manager vs objective comparison results
- `/flags/` and `/cases/` review workflow (leader/admin)

## Demo Users
After running `seed_demo_data`, these users are available:
- `demo_admin`
- `demo_leader_north`
- `demo_leader_south`
- `demo_teacher_n1`
- `demo_teacher_n2`
- `demo_teacher_s1`
- `demo_teacher_s2`
