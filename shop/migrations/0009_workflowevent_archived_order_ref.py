from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0008_employee_active_requires_specialty_data"),
    ]

    operations = [
        migrations.AddField(
            model_name="workflowevent",
            name="archived_order_ref",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="When an order is removed entirely, its reference is logged here once (tombstone row).",
                max_length=36,
            ),
        ),
    ]
