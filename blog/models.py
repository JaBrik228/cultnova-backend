from django.db import models

from core.models.base_item import BaseContentBlock, BaseContentItem


class Articles(BaseContentItem):
    title = models.CharField(max_length=255, verbose_name="\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435")
    slug = models.SlugField(unique=True)
    excerpt = models.TextField(blank=True, default="", verbose_name="Excerpt")
    preview_image = models.URLField(
        max_length=1024,
        blank=True,
        null=True,
        verbose_name="\u041f\u0440\u0435\u0432\u044c\u044e \u0438\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435",
    )
    preview_image_alt = models.CharField(max_length=255, blank=True, default="", verbose_name="Preview image alt")
    is_published = models.BooleanField(default=False, verbose_name="\u041e\u043f\u0443\u0431\u043b\u0438\u043a\u043e\u0432\u0430\u043d\u043e")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="\u0414\u0430\u0442\u0430 \u0441\u043e\u0437\u0434\u0430\u043d\u0438\u044f")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Updated at")

    seo_title = models.CharField(max_length=255, default="", verbose_name="SEO title")
    seo_description = models.CharField(max_length=320, default="", verbose_name="SEO description")
    seo_keywords = models.CharField(max_length=500, blank=True, default="", verbose_name="SEO keywords")
    seo_robots = models.CharField(max_length=32, default="index,follow", verbose_name="SEO robots")
    canonical_url = models.URLField(max_length=1024, blank=True, default="", verbose_name="Canonical URL")

    class Meta:
        verbose_name = "\u0421\u0442\u0430\u0442\u044c\u044f"
        verbose_name_plural = "\u0421\u0442\u0430\u0442\u044c\u0438"
        ordering = ("-created_at",)

    def __str__(self):
        return self.title


class ArticlesContentBlock(BaseContentBlock):
    TEXT = "text"
    HEADING = "heading"
    IMAGE = "image"
    VIDEO = "video"

    CONTENT_TYPE_CHOICES = [
        (TEXT, "\u0422\u0435\u043a\u0441\u0442"),
        (HEADING, "\u0417\u0430\u0433\u043e\u043b\u043e\u0432\u043e\u043a"),
        (IMAGE, "\u0418\u0437\u043e\u0431\u0440\u0430\u0436\u0435\u043d\u0438\u0435"),
        (VIDEO, "\u0412\u0438\u0434\u0435\u043e"),
    ]

    article = models.ForeignKey(
        Articles,
        related_name="blocks",
        on_delete=models.CASCADE,
        verbose_name="\u0421\u0442\u0430\u0442\u044c\u044f",
    )
    type = models.CharField(max_length=20, choices=CONTENT_TYPE_CHOICES, verbose_name="\u0422\u0438\u043f")
    order = models.PositiveIntegerField(verbose_name="\u041c\u0435\u0441\u0442\u043e")
    text = models.TextField(blank=True, null=True, verbose_name="\u0422\u0435\u043a\u0441\u0442")
    media = models.URLField(max_length=1024, blank=True, null=True, verbose_name="\u041c\u0435\u0434\u0438\u0430")
    media_alt = models.CharField(max_length=255, blank=True, default="", verbose_name="Media alt")
    caption = models.CharField(max_length=255, blank=True, default="", verbose_name="Caption")
    first_video_frame = models.URLField(
        max_length=1024,
        blank=True,
        null=True,
        verbose_name="\u041f\u0435\u0440\u0432\u044b\u0439 \u043a\u0430\u0434\u0440 \u0432\u0438\u0434\u0435\u043e",
    )

    class Meta:
        ordering = ("order",)
        verbose_name = "\u0411\u043b\u043e\u043a"
        verbose_name_plural = "\u0411\u043b\u043e\u043a\u0438"

    def __str__(self):
        return f"{self.type} ({self.order})"
