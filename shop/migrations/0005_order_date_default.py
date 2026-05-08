# Generated manually: restore AlterField after accidental deletion.

import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0004_garment_primary_material"),
    ]

    operations = [
        migrations.AlterField(
            model_name="order",
            name="order_date",
            field=models.DateField(default=django.utils.timezone.localdate),
        ),
    ]
