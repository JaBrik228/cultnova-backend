from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from core.services.build_item_html import build_item_detail_static_html, delete_item_detail_static_html
from core.services.sitemap import build_public_sitemaps

from .models import ProjectCategories, Projects, ProjectsContentBlock
from .services.project_listing import rebuild_projects_listing_static_html


def _resolve_category_slug(category_id: int | None) -> str | None:
    if not category_id:
        return None
    return ProjectCategories.objects.filter(pk=category_id).values_list("slug", flat=True).first()


def _schedule_listing_rebuild(*, category_slugs=None, prune_stale=False):
    def callback():
        rebuild_projects_listing_static_html(
            category_slugs=category_slugs,
            prune_stale=prune_stale,
        )
        build_public_sitemaps()

    transaction.on_commit(callback)


def _schedule_project_rebuild(
    instance,
    *,
    previous_slug=None,
    previous_is_published=False,
    previous_category_slug=None,
    force_delete=False,
):
    current_category_slug = _resolve_category_slug(instance.category_id)
    category_slugs = {
        slug
        for slug in (current_category_slug, previous_category_slug)
        if slug
    }

    def callback():
        if previous_slug and previous_slug != instance.slug and previous_is_published:
            delete_item_detail_static_html(instance, "projects", slug_override=previous_slug)

        if force_delete or not instance.is_published:
            delete_item_detail_static_html(instance, "projects")
        else:
            build_item_detail_static_html(instance, "project_detail.html", "projects")

        rebuild_projects_listing_static_html(category_slugs=category_slugs)
        build_public_sitemaps()

    transaction.on_commit(callback)


def _schedule_project_rebuild_by_id(project_id: int):
    def callback():
        project = Projects.objects.select_related("category").filter(pk=project_id).first()
        if not project:
            build_public_sitemaps()
            return

        if project.is_published:
            build_item_detail_static_html(project, "project_detail.html", "projects")
        else:
            delete_item_detail_static_html(project, "projects")

        category_slugs = {_resolve_category_slug(project.category_id)} if project.category_id else set()
        rebuild_projects_listing_static_html(category_slugs=category_slugs)
        build_public_sitemaps()

    transaction.on_commit(callback)


@receiver(pre_save, sender=Projects)
def project_pre_save_handler(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_slug = None
        instance._previous_is_published = False
        instance._previous_category_slug = None
        return

    previous = sender.objects.filter(pk=instance.pk).values("slug", "is_published", "category__slug").first()
    if not previous:
        instance._previous_slug = None
        instance._previous_is_published = False
        instance._previous_category_slug = None
        return

    instance._previous_slug = previous["slug"]
    instance._previous_is_published = previous["is_published"]
    instance._previous_category_slug = previous["category__slug"]


@receiver(post_save, sender=Projects)
def project_save_handler(sender, instance, **kwargs):
    _schedule_project_rebuild(
        instance,
        previous_slug=getattr(instance, "_previous_slug", None),
        previous_is_published=getattr(instance, "_previous_is_published", False),
        previous_category_slug=getattr(instance, "_previous_category_slug", None),
    )


@receiver(post_delete, sender=Projects)
def project_delete_handler(sender, instance, **kwargs):
    _schedule_project_rebuild(
        instance,
        previous_slug=instance.slug,
        previous_is_published=instance.is_published,
        previous_category_slug=_resolve_category_slug(instance.category_id),
        force_delete=True,
    )


@receiver(post_save, sender=ProjectsContentBlock)
def project_block_save_handler(sender, instance, **kwargs):
    project_id = instance.project_id
    Projects.objects.filter(pk=project_id).update(updated_at=timezone.now())
    _schedule_project_rebuild_by_id(project_id)


@receiver(post_delete, sender=ProjectsContentBlock)
def project_block_delete_handler(sender, instance, **kwargs):
    project_id = instance.project_id
    if not project_id:
        transaction.on_commit(build_public_sitemaps)
        return

    Projects.objects.filter(pk=project_id).update(updated_at=timezone.now())
    _schedule_project_rebuild_by_id(project_id)


@receiver(post_save, sender=ProjectCategories)
def project_category_save_handler(sender, instance, **kwargs):
    _schedule_listing_rebuild(prune_stale=True)


@receiver(post_delete, sender=ProjectCategories)
def project_category_delete_handler(sender, instance, **kwargs):
    _schedule_listing_rebuild(prune_stale=True)
