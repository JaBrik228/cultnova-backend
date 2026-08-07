from django.db import models

from django.db.models import Count, F, Q
from django.db.models.deletion import ProtectedError

from core.models.base_item import BaseContentBlock, BaseContentItem


class ProjectCategoriesQuerySet(models.QuerySet):
    def ordered(self):
        return self.order_by(F("sort_order").asc(nulls_last=True), "title", "pk")

    def _projects_orphaned_by_delete(self):
        category_ids = list(self.values_list("pk", flat=True))
        if not category_ids:
            return Projects.objects.none()

        return (
            Projects.objects.annotate(
                _categories_being_deleted=Count(
                    "categories",
                    filter=Q(categories__pk__in=category_ids),
                    distinct=True,
                ),
                _remaining_categories=Count(
                    "categories",
                    filter=~Q(categories__pk__in=category_ids),
                    distinct=True,
                ),
            )
            .filter(_categories_being_deleted__gt=0, _remaining_categories=0)
            .order_by("pk")
        )

    def _guard_delete(self):
        orphaned_projects = list(self._projects_orphaned_by_delete())
        if orphaned_projects:
            raise ProtectedError(
                "Нельзя удалить категории: хотя бы один проект останется без категории.",
                orphaned_projects,
            )

    def delete(self):
        self._guard_delete()
        return super().delete()


class ProjectCategories(models.Model):
    title = models.CharField(max_length=100, verbose_name="Название")
    slug = models.SlugField(unique=True, verbose_name="Слаг")
    page_h1 = models.CharField(max_length=255, blank=True, default="", verbose_name="Page H1")
    seo_title = models.CharField(max_length=255, blank=True, default="", verbose_name="SEO title")
    seo_description = models.CharField(max_length=320, blank=True, default="", verbose_name="SEO description")
    seo_keywords = models.CharField(max_length=500, blank=True, default="", verbose_name="SEO keywords")
    seo_robots = models.CharField(max_length=32, blank=True, default="index,follow", verbose_name="SEO robots")
    canonical_url = models.URLField(max_length=1024, blank=True, default="", verbose_name="Canonical URL")
    sort_order = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Порядок",
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")

    objects = ProjectCategoriesQuerySet.as_manager()

    class Meta:
        verbose_name = "Категория проектов"
        verbose_name_plural = "Категории проектов"
        ordering = (F("sort_order").asc(nulls_last=True), "title", "pk")

    def __str__(self):
        return self.title

    def delete(self, using=None, keep_parents=False):
        type(self).objects.filter(pk=self.pk)._guard_delete()
        return super().delete(using=using, keep_parents=keep_parents)


class ProjectsQuerySet(models.QuerySet):
    def create(self, **kwargs):
        legacy_category = kwargs.pop("category", None)
        legacy_category_id = kwargs.pop("category_id", None)
        project = super().create(**kwargs)

        if legacy_category is not None:
            project.categories.add(legacy_category)
        elif legacy_category_id is not None:
            project.categories.add(legacy_category_id)

        return project


class Projects(BaseContentItem):
    title = models.CharField(max_length=100, verbose_name="Название")
    slug = models.SlugField(unique=True, verbose_name="Слаг")
    categories = models.ManyToManyField(
        ProjectCategories,
        related_name="projects",
        verbose_name="Категории",
    )
    customer_name = models.CharField(max_length=300, verbose_name="Заказчик")
    year = models.PositiveIntegerField(verbose_name="Год")
    type = models.CharField(max_length=300, verbose_name="Тип проекта")
    sort_order = models.PositiveIntegerField(
        null=True,
        blank=True,
        db_index=True,
        verbose_name="Порядок",
    )
    body_html = models.TextField(blank=True, default="", verbose_name="Body HTML")
    excerpt = models.TextField(blank=True, default="", verbose_name="Excerpt")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Дата создания")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated at")
    preview_image = models.URLField(max_length=1024, blank=True, null=True)
    preview_image_alt = models.CharField(max_length=255, blank=True, default="", verbose_name="Preview image alt")

    seo_title = models.CharField(max_length=255, default="", verbose_name="SEO title")
    seo_description = models.CharField(max_length=320, default="", verbose_name="SEO description")
    seo_keywords = models.CharField(max_length=500, blank=True, default="", verbose_name="SEO keywords")
    seo_robots = models.CharField(max_length=32, default="index,follow", verbose_name="SEO robots")
    canonical_url = models.URLField(max_length=1024, blank=True, default="", verbose_name="Canonical URL")

    objects = ProjectsQuerySet.as_manager()

    class Meta:
        verbose_name = "Проект"
        verbose_name_plural = "Проекты"
        ordering = ("-created_at",)

    def __str__(self):
        return self.title

    def get_ordered_categories(self):
        prefetched_categories = getattr(self, "ordered_categories", None)
        if prefetched_categories is not None:
            return prefetched_categories
        return list(self.categories.all())


class ServicePageProjects(models.Model):
    PROJECT_FIELDS = ("project_1", "project_2", "project_3")
    SERVICE_PAGE_CHOICES = (
        ("service", "Техническое сопровождение и обслуживание"),
        ("environment", "Доступная среда"),
        ("stand", "Застройка выставок"),
        ("musium", "Музеи и интерактивные пространства"),
        ("design", "Архитектурное проектирование и дизайн"),
        ("content", "Контент и анимация"),
        ("app", "Разработка приложений и ПО"),
    )

    slug = models.SlugField(
        unique=True,
        choices=SERVICE_PAGE_CHOICES,
        verbose_name="Страница услуги",
    )
    position = models.PositiveSmallIntegerField(default=0, editable=False, verbose_name="Порядок")
    project_1 = models.ForeignKey(
        Projects,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Проект 1",
    )
    project_2 = models.ForeignKey(
        Projects,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Проект 2",
    )
    project_3 = models.ForeignKey(
        Projects,
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name="+",
        verbose_name="Проект 3",
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated at")

    class Meta:
        verbose_name = "Страница проектов на странице услуги"
        verbose_name_plural = "Страницы проектов на страницах услуг"
        ordering = ("position", "slug")

    @property
    def title(self):
        return dict(self.SERVICE_PAGE_CHOICES).get(self.slug, self.slug)

    @classmethod
    def ensure_default_pages(cls):
        existing_pages = {
            page.slug: page
            for page in cls.objects.filter(slug__in=[slug for slug, _title in cls.SERVICE_PAGE_CHOICES])
        }

        for position, (slug, _title) in enumerate(cls.SERVICE_PAGE_CHOICES, start=1):
            page = existing_pages.get(slug)
            if page is None:
                cls.objects.create(slug=slug, position=position)
            elif page.position != position:
                cls.objects.filter(pk=page.pk).update(position=position)

    def __str__(self):
        return self.title


class ProjectsContentBlock(BaseContentBlock):
    TEXT = "text"
    HEADING = "heading"
    IMAGE = "image"
    VIDEO = "video"

    CONTENT_TYPE_CHOICES = [
        (TEXT, "Текст"),
        (HEADING, "Заголовок"),
        (IMAGE, "Изображение"),
        (VIDEO, "Видео"),
    ]

    project = models.ForeignKey(
        Projects,
        related_name="blocks",
        on_delete=models.CASCADE,
        verbose_name="Проект",
    )
    type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES, verbose_name="Тип")
    order = models.PositiveIntegerField(verbose_name="Место")
    text = models.TextField(null=True, blank=True, verbose_name="Текст")
    media = models.URLField(max_length=1024, blank=True, null=True, verbose_name="Медиа")
    media_alt = models.CharField(max_length=255, blank=True, default="", verbose_name="Media alt")
    caption = models.CharField(max_length=255, blank=True, default="", verbose_name="Caption")
    first_video_frame = models.URLField(max_length=1024, blank=True, null=True, verbose_name="Первый кадр видео")

    class Meta:
        verbose_name = "Блок"
        verbose_name_plural = "Блоки"
        ordering = ("order",)

    def __str__(self):
        return f"{self.type} ({self.order})"
