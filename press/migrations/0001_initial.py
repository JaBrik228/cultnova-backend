# Generated manually for the press feed feature.
from django.core.validators import URLValidator
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="PressItem",
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
                ("title", models.CharField(max_length=255, verbose_name="Заголовок")),
                ("description", models.TextField(verbose_name="Описание")),
                (
                    "url",
                    models.URLField(
                        max_length=1024,
                        validators=[URLValidator(schemes=["http", "https"])],
                        verbose_name="Ссылка",
                    ),
                ),
                (
                    "sort_order",
                    models.PositiveIntegerField(
                        default=0,
                        db_index=True,
                        verbose_name="Порядок",
                    ),
                ),
                (
                    "is_published",
                    models.BooleanField(
                        default=False,
                        db_index=True,
                        verbose_name="Опубликовано",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")),
                ("updated_at", models.DateTimeField(auto_now=True, verbose_name="Дата изменения")),
            ],
            options={
                "verbose_name": "Публикация в СМИ",
                "verbose_name_plural": "СМИ о нас",
                "ordering": ("sort_order", "created_at", "pk"),
            },
        ),
    ]

