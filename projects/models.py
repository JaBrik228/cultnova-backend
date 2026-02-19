from django.db import models
from core.models.base_item import BaseContentItem, BaseContentBlock


class ProjectCategories(models.Model):
    title = models.CharField(max_length=100, verbose_name="Название")
    slug = models.SlugField(unique=True, verbose_name="Слаг")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    class Meta:
        verbose_name = "Категория проктов"
        verbose_name_plural = "Категории проктов"
        ordering = ('-created_at',)

    def __str__(self):
        return self.title


class Projects(BaseContentItem):
    title = models.CharField(max_length=100, verbose_name="Название")
    slug = models.SlugField(unique=True, verbose_name="Слаг")
    category = models.ForeignKey(
        ProjectCategories,
        related_name='projects',
        on_delete=models.CASCADE,
        verbose_name="Категория"
    )
    customer_name = models.CharField(max_length=300, verbose_name="Заказчик")
    year = models.PositiveIntegerField(verbose_name="Год")
    type = models.CharField(max_length=300, verbose_name="Тип проекта")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    preview_image = models.URLField(max_length=1024, blank=True, null=True)

    class Meta:
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"
        ordering = ('-created_at',)

    def __str__(self):
        return self.title


class ProjectsContentBlock(BaseContentBlock):
    TEXT = 'text'
    HEADING = 'heading'
    IMAGE = 'image'
    VIDEO = 'video'

    CONTENT_TYPE_CHOICES = [
        (TEXT, 'Текст'),
        (HEADING, 'Заголовок'),
        (IMAGE, 'Изображение'),
        (VIDEO, "Видео"),
    ]

    project = models.ForeignKey(
        Projects,
        related_name='blocks',
        on_delete=models.CASCADE,
        verbose_name="Проект"
    )
    type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES, verbose_name="Тип")
    order = models.PositiveIntegerField(verbose_name="Место")
    text = models.TextField(null=True, blank=True, verbose_name="Текст")
    media = models.URLField(max_length=1024, blank=True, null=True, verbose_name="Медиа")
    first_video_frame = models.URLField(max_length=1024, blank=True, null=True, verbose_name="Первый кадр видео")

    class Meta:
        verbose_name = "Блок"
        verbose_name_plural = "Блоки"
        ordering = ('order',)

    def __str__(self):
        return self.text
