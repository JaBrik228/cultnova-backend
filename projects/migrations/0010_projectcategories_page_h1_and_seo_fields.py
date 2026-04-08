from django.db import migrations, models


def set_existing_category_robots_to_noindex(apps, schema_editor):
    ProjectCategories = apps.get_model("projects", "ProjectCategories")
    ProjectCategories.objects.all().update(seo_robots="noindex,nofollow")


def reset_existing_category_robots(apps, schema_editor):
    ProjectCategories = apps.get_model("projects", "ProjectCategories")
    ProjectCategories.objects.all().update(seo_robots="index,follow")


class Migration(migrations.Migration):
    dependencies = [
        ("projects", "0009_migrate_project_body_html_and_seo"),
    ]

    operations = [
        migrations.AddField(
            model_name="projectcategories",
            name="page_h1",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="Page H1"),
        ),
        migrations.AddField(
            model_name="projectcategories",
            name="seo_title",
            field=models.CharField(blank=True, default="", max_length=255, verbose_name="SEO title"),
        ),
        migrations.AddField(
            model_name="projectcategories",
            name="seo_description",
            field=models.CharField(blank=True, default="", max_length=320, verbose_name="SEO description"),
        ),
        migrations.AddField(
            model_name="projectcategories",
            name="seo_keywords",
            field=models.CharField(blank=True, default="", max_length=500, verbose_name="SEO keywords"),
        ),
        migrations.AddField(
            model_name="projectcategories",
            name="seo_robots",
            field=models.CharField(
                blank=True,
                default="index,follow",
                max_length=32,
                verbose_name="SEO robots",
            ),
        ),
        migrations.AddField(
            model_name="projectcategories",
            name="canonical_url",
            field=models.URLField(blank=True, default="", max_length=1024, verbose_name="Canonical URL"),
        ),
        migrations.RunPython(
            set_existing_category_robots_to_noindex,
            reverse_code=reset_existing_category_robots,
        ),
    ]
