# Assign deterministic specialties so existing active rows satisfy validation after upgrading.

from django.db import migrations

# Omit “delivered” — floor workers map to upstream stages first.
_PIPELINE_STAGES = (
    "order_received",
    "design_confirmed",
    "cutting",
    "sewing",
    "finishing",
    "quality_check",
    "ready_for_delivery",
)


def forwards(apps, schema_editor):
    Employee = apps.get_model("shop", "Employee")
    qs = Employee.objects.filter(active=True, specialty_stage="").order_by("pk").values_list("pk", flat=True)
    pk_list = list(qs)
    for i, pk in enumerate(pk_list):
        Employee.objects.filter(pk=pk).update(specialty_stage=_PIPELINE_STAGES[i % len(_PIPELINE_STAGES)])


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0007_workflow_overhaul"),
    ]

    operations = [
        migrations.RunPython(forwards, noop_reverse),
    ]
