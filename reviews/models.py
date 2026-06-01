from django.core.validators import URLValidator
from django.db import models


HTTP_HTTPS_URL_VALIDATOR = URLValidator(schemes=["http", "https"])


def _trim(value):
    if isinstance(value, str):
        return value.strip()
    return value


class HomeReview(models.Model):
    name = models.CharField(max_length=255, verbose_name="Имя")
    position = models.CharField(max_length=500, verbose_name="Должность")
    text = models.TextField(verbose_name="Текст отзыва")
    image_url = models.URLField(
        max_length=1024,
        validators=[HTTP_HTTPS_URL_VALIDATOR],
        verbose_name="Ссылка на изображение",
    )
    image_alt = models.CharField(max_length=255, verbose_name="Alt изображения")
    sort_order = models.PositiveIntegerField(default=0, db_index=True, verbose_name="Порядок")
    is_published = models.BooleanField(default=False, db_index=True, verbose_name="Опубликовано")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Дата изменения")

    class Meta:
        verbose_name = "Отзыв на главной"
        verbose_name_plural = "Отзывы на главной"
        ordering = ("sort_order", "created_at", "pk")

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        self.name = _trim(self.name)
        self.position = _trim(self.position)
        self.text = _trim(self.text)
        self.image_url = _trim(self.image_url)
        self.image_alt = _trim(self.image_alt)
        super().save(*args, **kwargs)

