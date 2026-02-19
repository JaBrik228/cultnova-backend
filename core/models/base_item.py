from django.db import models


class BaseContentItem(models.Model):
    """Абстрактная модель для Статей, Проектов и т.д."""
    title = models.CharField(max_length=255, verbose_name='Название')
    slug = models.SlugField(unique=True, verbose_name='Слаг')
    preview_image = models.URLField(max_length=1024, blank=True, null=True, verbose_name='Превью')
    is_published = models.BooleanField(default=False, verbose_name='Опубликовано')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Дата создания')

    class Meta:
        abstract = True


class BaseContentBlock(models.Model):
    """Абстрактная модель для блоков контента"""
    TEXT = 'text'
    HEADING = 'heading'
    IMAGE = 'image'
    VIDEO = 'video'

    CONTENT_TYPE_CHOICES = [
        (TEXT, 'Текст'),
        (HEADING, 'Заголовок'),
        (IMAGE, 'Изображение'),
        (VIDEO, 'Видео')
    ]

    type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES, verbose_name='Тип')
    order = models.PositiveIntegerField(verbose_name='Место')
    text = models.TextField(blank=True, null=True, verbose_name='Текст')
    media = models.URLField(max_length=1024, blank=True, null=True, verbose_name="Медиа")
    first_video_frame = models.URLField(max_length=1024, blank=True, null=True, verbose_name="Первый кадр")

    class Meta:
        abstract = True
        ordering = ('order',)