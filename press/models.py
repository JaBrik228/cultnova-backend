from django.core.validators import URLValidator
from django.db import models


HTTP_HTTPS_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


def _trim(value):
    if isinstance(value, str):
        return value.strip()
    return value


class PressItem(models.Model):
    title = models.CharField(max_length=255, verbose_name="Заголовок")
    description = models.TextField(verbose_name="Описание")
    url = models.URLField(
        max_length=1024,
        validators=[HTTP_HTTPS_URL_VALIDATOR],
        verbose_name="Ссылка",
    )
    sort_order = models.PositiveIntegerField(default=0, db_index=True, verbose_name="Порядок")
    is_published = models.BooleanField(default=False, db_index=True, verbose_name="Опубликовано")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата изменения")

    class Meta:
        verbose_name = "Публикация в СМИ"
        verbose_name_plural = "СМИ о нас"
        ordering = ("sort_order", "created_at", "pk")

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.title = _trim(self.title)
        self.description = _trim(self.description)
        self.url = _trim(self.url)
        super().save(*args, **kwargs)

