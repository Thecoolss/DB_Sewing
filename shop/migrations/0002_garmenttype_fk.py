from django.db import migrations, models
import django.db.models.deletion


def migrate_garment_types(apps, schema_editor):
    Garment = apps.get_model("shop", "Garment")
    GarmentType = apps.get_model("shop", "GarmentType")

    for garment in Garment.objects.all():
        value = (garment.garment_type or "").strip() or "Unspecified"
        garment_type, _ = GarmentType.objects.get_or_create(name=value)
        garment.garment_type_fk_id = garment_type.id
        garment.save(update_fields=["garment_type_fk"])


class Migration(migrations.Migration):
    dependencies = [
        ("shop", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="GarmentType",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("name", models.CharField(max_length=100, unique=True)),
                ("description", models.CharField(blank=True, max_length=255)),
                ("active", models.BooleanField(default=True)),
            ],
            options={"ordering": ["name"]},
        ),
        migrations.AddField(
            model_name="garment",
            name="garment_type_fk",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="garments",
                to="shop.garmenttype",
            ),
        ),
        migrations.RunPython(migrate_garment_types, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="garment",
            name="garment_type",
        ),
        migrations.RenameField(
            model_name="garment",
            old_name="garment_type_fk",
            new_name="garment_type",
        ),
        migrations.AlterField(
            model_name="garment",
            name="garment_type",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="garments",
                to="shop.garmenttype",
            ),
        ),
    ]
