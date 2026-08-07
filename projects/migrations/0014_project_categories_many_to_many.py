from django.db import migrations, models
from django.db.models import Case, IntegerField, Value, When
import django.db.models.deletion


def populate_category_order_and_project_categories(apps, schema_editor):
    ProjectCategories = apps.get_model("projects", "ProjectCategories")
    Projects = apps.get_model("projects", "Projects")

    category_ids = ProjectCategories.objects.order_by("-created_at", "title", "pk").values_list("pk", flat=True)
    for position, category_id in enumerate(category_ids.iterator(), start=1):
        ProjectCategories.objects.filter(pk=category_id).update(sort_order=position)

    through_model = Projects.categories.through
    relations = (
        through_model(projects_id=project_id, projectcategories_id=category_id)
        for project_id, category_id in Projects.objects.values_list("pk", "category_id").iterator()
        if category_id is not None
    )
    through_model.objects.bulk_create(relations, ignore_conflicts=True)


def restore_first_project_category(apps, schema_editor):
    # This reverse step is intentionally lossy: additional M2M links cannot be
    # represented by the restored single FK.
    Projects = apps.get_model("projects", "Projects")

    for project in Projects.objects.all().iterator():
        first_category_id = (
            project.categories.annotate(
                _sort_order_is_null=Case(
                    When(sort_order__isnull=True, then=Value(1)),
                    default=Value(0),
                    output_field=IntegerField(),
                )
            )
            .order_by("_sort_order_is_null", "sort_order", "title", "pk")
            .values_list("pk", flat=True)
            .first()
        )
        Projects.objects.filter(pk=project.pk).update(category_id=first_category_id)


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0013_projects_sort_order"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectcategories",
            name="sort_order",
            field=models.PositiveIntegerField(blank=True, db_index=True, null=True, verbose_name="Порядок"),
        ),
        migrations.AlterField(
            model_name="projects",
            name="category",
            field=models.ForeignKey(
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="legacy_projects",
                to="projects.projectcategories",
                verbose_name="Категория",
            ),
        ),
        migrations.AddField(
            model_name="projects",
            name="categories",
            field=models.ManyToManyField(
                related_name="projects",
                to="projects.projectcategories",
                verbose_name="Категории",
            ),
        ),
        migrations.RunPython(
            populate_category_order_and_project_categories,
            reverse_code=restore_first_project_category,
        ),
        migrations.RemoveField(
            model_name="projects",
            name="category",
        ),
        migrations.AlterModelOptions(
            name="projectcategories",
            options={
                "ordering": (models.F("sort_order").asc(nulls_last=True), "title", "pk"),
                "verbose_name": "Категория проектов",
                "verbose_name_plural": "Категории проектов",
            },
        ),
    ]
