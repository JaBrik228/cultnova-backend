from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from core.services.build_item_html import build_item_detail_static_html, delete_item_detail_static_html
from core.services.sitemap import build_sitemap

from .models import Projects, ProjectsContentBlock


def _schedule_project_rebuild(instance, previous_slug=None, previous_is_published=False):
    def callback():
        if previous_slug and previous_slug != instance.slug and previous_is_published:
            delete_item_detail_static_html(instance, "projects", slug_override=previous_slug)

        if instance.is_published:
            build_item_detail_static_html(instance, "project_detail.html", "projects")
        else:
            delete_item_detail_static_html(instance, "projects")

        build_sitemap()

    transaction.on_commit(callback)


def _schedule_project_rebuild_by_id(project_id: int):
    def callback():
        project = Projects.objects.filter(pk=project_id).first()
        if not project:
            build_sitemap()
            return

        if project.is_published:
            build_item_detail_static_html(project, "project_detail.html", "projects")
        else:
            delete_item_detail_static_html(project, "projects")

        build_sitemap()

    transaction.on_commit(callback)


@receiver(pre_save, sender=Projects)
def project_pre_save_handler(sender, instance, **kwargs):
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


@receiver(post_save, sender=Projects)
def project_save_handler(sender, instance, **kwargs):
    _schedule_project_rebuild(
        instance,
        previous_slug=getattr(instance, "_previous_slug", None),
        previous_is_published=getattr(instance, "_previous_is_published", False),
    )


@receiver(post_delete, sender=Projects)
def project_delete_handler(sender, instance, **kwargs):
    _schedule_project_rebuild(instance)


@receiver(post_save, sender=ProjectsContentBlock)
def project_block_save_handler(sender, instance, **kwargs):
    project_id = instance.project_id
    Projects.objects.filter(pk=project_id).update(updated_at=timezone.now())
    _schedule_project_rebuild_by_id(project_id)


@receiver(post_delete, sender=ProjectsContentBlock)
def project_block_delete_handler(sender, instance, **kwargs):
    project_id = instance.project_id
    if not project_id:
        transaction.on_commit(build_sitemap)
        return

    Projects.objects.filter(pk=project_id).update(updated_at=timezone.now())
    _schedule_project_rebuild_by_id(project_id)
