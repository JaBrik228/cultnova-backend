from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from core.services.build_item_html import build_item_detail_static_html, delete_item_detail_static_html
from core.services.sitemap import build_public_sitemaps

from .models import Articles, ArticlesContentBlock


def _schedule_article_rebuild(instance, previous_slug=None, previous_is_published=False):
    def callback():
        if previous_slug and previous_slug != instance.slug and previous_is_published:
            delete_item_detail_static_html(instance, "articles", slug_override=previous_slug)

        if instance.is_published:
            build_item_detail_static_html(instance, "article_detail.html", "articles")
        else:
            delete_item_detail_static_html(instance, "articles")

        build_public_sitemaps()

    transaction.on_commit(callback)


def _schedule_article_rebuild_by_id(article_id: int):
    def callback():
        article = Articles.objects.filter(pk=article_id).first()
        if not article:
            build_public_sitemaps()
            return

        if article.is_published:
            build_item_detail_static_html(article, "article_detail.html", "articles")
        else:
            delete_item_detail_static_html(article, "articles")

        build_public_sitemaps()

    transaction.on_commit(callback)


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
    _schedule_article_rebuild(
        instance,
        previous_slug=getattr(instance, "_previous_slug", None),
        previous_is_published=getattr(instance, "_previous_is_published", False),
    )


@receiver(post_delete, sender=Articles)
def article_delete_handler(sender, instance, **kwargs):
    _schedule_article_rebuild(instance)


@receiver(post_save, sender=ArticlesContentBlock)
def block_save_handler(sender, instance, **kwargs):
    article_id = instance.article_id
    Articles.objects.filter(pk=article_id).update(updated_at=timezone.now())
    _schedule_article_rebuild_by_id(article_id)


@receiver(post_delete, sender=ArticlesContentBlock)
def block_delete_handler(sender, instance, **kwargs):
    article_id = instance.article_id
    if not article_id:
        transaction.on_commit(build_public_sitemaps)
        return

    Articles.objects.filter(pk=article_id).update(updated_at=timezone.now())
    _schedule_article_rebuild_by_id(article_id)
