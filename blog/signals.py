from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver

from core.services.build_item_html import build_item_detail_static_html, delete_item_detail_static_html

from .models import Articles, ArticlesContentBlock


@receiver(pre_save, sender=Articles)
def article_pre_save_handler(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_slug = None
        instance._previous_is_published = False
        return

    previous = sender.objects.filter(pk=instance.pk).values("slug", "is_published").first()
    if not previous:
        instance._previous_slug = None
        instance._previous_is_published = False
        return

    instance._previous_slug = previous["slug"]
    instance._previous_is_published = previous["is_published"]


@receiver(post_save, sender=Articles)
def article_save_handler(sender, instance, **kwargs):
    previous_slug = getattr(instance, "_previous_slug", None)
    previous_is_published = getattr(instance, "_previous_is_published", False)

    if previous_slug and previous_slug != instance.slug and previous_is_published:
        delete_item_detail_static_html(instance, "articles", slug_override=previous_slug)

    if instance.is_published:
        build_item_detail_static_html(instance, "article_detail.html", "articles")
    else:
        delete_item_detail_static_html(instance, "articles")


@receiver(post_delete, sender=Articles)
def article_delete_handler(sender, instance, **kwargs):
    delete_item_detail_static_html(instance, "articles")


@receiver(post_save, sender=ArticlesContentBlock)
def block_save_handler(sender, instance, **kwargs):
    article = instance.article
    if article.is_published:
        build_item_detail_static_html(article, "article_detail.html", "articles")


@receiver(post_delete, sender=ArticlesContentBlock)
def block_delete_handler(sender, instance, **kwargs):
    try:
        article = instance.article
    except Articles.DoesNotExist:
        return

    if article and article.is_published:
        build_item_detail_static_html(article, "article_detail.html", "articles")
