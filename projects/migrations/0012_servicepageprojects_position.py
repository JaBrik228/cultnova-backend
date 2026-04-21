from django.db import migrations, models


SERVICE_PAGE_SLUGS = (
    "service",
    "environment",
    "stand",
    "musium",
    "design",
    "content",
    "app",
)


def set_service_page_project_positions(apps, schema_editor):
    ServicePageProjects = apps.get_model("projects", "ServicePageProjects")
    for position, slug in enumerate(SERVICE_PAGE_SLUGS, start=1):
        ServicePageProjects.objects.update_or_create(
            slug=slug,
            defaults={"position": position},
        )


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0011_servicepageprojects"),
    ]

    operations = [
        migrations.AddField(
            model_name="servicepageprojects",
            name="position",
            field=models.PositiveSmallIntegerField(default=0, editable=False, verbose_name="Порядок"),
        ),
        migrations.AlterModelOptions(
            name="servicepageprojects",
            options={
                "ordering": ("position", "slug"),
                "verbose_name": "Страница проектов на странице услуги",
                "verbose_name_plural": "Страницы проектов на страницах услуг",
            },
        ),
        migrations.RunPython(
            set_service_page_project_positions,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
