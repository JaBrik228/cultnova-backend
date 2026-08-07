from django.db import connections, transaction
from django.db.models.signals import m2m_changed, post_delete, post_migrate, post_save, pre_delete, pre_save
from django.dispatch import receiver
from django.utils import timezone

from core.services.build_item_html import build_item_detail_static_html, delete_item_detail_static_html
from core.services.sitemap import build_public_sitemaps

from .models import ProjectCategories, Projects, ProjectsContentBlock, ServicePageProjects
from .services.project_categories import get_ordered_project_categories_prefetch
from .services.project_listing import rebuild_projects_listing_static_html


def _category_slugs_for_project(project_id: int | None) -> set[str]:
    if not project_id:
        return set()
    return set(
        ProjectCategories.objects.filter(projects__pk=project_id).values_list("slug", flat=True)
    )


def _schedule_project_rebuild(
    instance,
    *,
    previous_slug=None,
    previous_is_published=False,
    previous_category_slugs=(),
    force_delete=False,
):
    project_id = instance.pk

    def callback():
        project = (
            Projects.objects.prefetch_related(get_ordered_project_categories_prefetch())
            .filter(pk=project_id)
            .first()
        )
        current_category_slugs = _category_slugs_for_project(project_id)
        category_slugs = set(previous_category_slugs) | current_category_slugs

        if previous_slug and previous_slug != instance.slug and previous_is_published:
            delete_item_detail_static_html(instance, "projects", slug_override=previous_slug)

        if force_delete or project is None or not project.is_published:
            delete_item_detail_static_html(instance, "projects")
        else:
            build_item_detail_static_html(project, "project_detail.html", "projects")

        rebuild_projects_listing_static_html(category_slugs=category_slugs)
        build_public_sitemaps()

    transaction.on_commit(callback)


def _schedule_membership_rebuild(*, project_ids, category_ids, category_slugs):
    normalized_project_ids = {project_id for project_id in project_ids if project_id}
    normalized_category_ids = {category_id for category_id in category_ids if category_id}
    normalized_category_slugs = {slug for slug in category_slugs if slug}

    def callback():
        affected_project_ids = set(normalized_project_ids)
        if normalized_category_ids:
            affected_project_ids.update(
                Projects.objects.filter(
                    is_published=True,
                    categories__pk__in=normalized_category_ids,
                ).values_list("pk", flat=True)
            )

        affected_projects = list(
            Projects.objects.filter(pk__in=affected_project_ids, is_published=True)
            .prefetch_related(get_ordered_project_categories_prefetch())
            .distinct()
        )
        for project in affected_projects:
            build_item_detail_static_html(project, "project_detail.html", "projects")

        current_slugs = set(
            ProjectCategories.objects.filter(pk__in=normalized_category_ids).values_list("slug", flat=True)
        )
        rebuild_projects_listing_static_html(
            category_slugs=normalized_category_slugs | current_slugs,
        )
        build_public_sitemaps()

    transaction.on_commit(callback)


def _schedule_all_project_pages_rebuild(*, stale_category_slugs=()):
    stale_category_slugs = {slug for slug in stale_category_slugs if slug}

    def callback():
        projects = (
            Projects.objects.filter(is_published=True)
            .prefetch_related(get_ordered_project_categories_prefetch())
            .order_by("pk")
        )
        for project in projects:
            build_item_detail_static_html(project, "project_detail.html", "projects")

        rebuild_projects_listing_static_html(
            stale_category_slugs=stale_category_slugs,
            prune_stale=True,
        )
        build_public_sitemaps()

    transaction.on_commit(callback)


def _schedule_project_rebuild_by_id(project_id: int):
    def callback():
        project = (
            Projects.objects.prefetch_related(get_ordered_project_categories_prefetch())
            .filter(pk=project_id)
            .first()
        )
        if not project:
            build_public_sitemaps()
            return

        if project.is_published:
            build_item_detail_static_html(project, "project_detail.html", "projects")
        else:
            delete_item_detail_static_html(project, "projects")

        rebuild_projects_listing_static_html(category_slugs=_category_slugs_for_project(project_id))
        build_public_sitemaps()

    transaction.on_commit(callback)


@receiver(pre_save, sender=Projects)
def project_pre_save_handler(sender, instance, **kwargs):
    if not instance.pk:
        instance._previous_slug = None
        instance._previous_is_published = False
        instance._previous_category_slugs = set()
        return

    previous = sender.objects.filter(pk=instance.pk).values("slug", "is_published").first()
    if not previous:
        instance._previous_slug = None
        instance._previous_is_published = False
        instance._previous_category_slugs = set()
        return

    instance._previous_slug = previous["slug"]
    instance._previous_is_published = previous["is_published"]
    instance._previous_category_slugs = _category_slugs_for_project(instance.pk)


@receiver(post_save, sender=Projects)
def project_save_handler(sender, instance, **kwargs):
    _schedule_project_rebuild(
        instance,
        previous_slug=getattr(instance, "_previous_slug", None),
        previous_is_published=getattr(instance, "_previous_is_published", False),
        previous_category_slugs=getattr(instance, "_previous_category_slugs", set()),
    )


@receiver(pre_delete, sender=Projects)
def project_pre_delete_handler(sender, instance, **kwargs):
    instance._category_slugs_before_delete = _category_slugs_for_project(instance.pk)


@receiver(post_delete, sender=Projects)
def project_delete_handler(sender, instance, **kwargs):
    _schedule_project_rebuild(
        instance,
        previous_slug=instance.slug,
        previous_is_published=instance.is_published,
        previous_category_slugs=getattr(instance, "_category_slugs_before_delete", set()),
        force_delete=True,
    )


@receiver(m2m_changed, sender=Projects.categories.through)
def project_categories_changed_handler(sender, instance, action, reverse, pk_set, **kwargs):
    if action.startswith("pre_"):
        if reverse:
            if action == "pre_clear":
                instance._m2m_project_ids = set(instance.projects.values_list("pk", flat=True))
            else:
                instance._m2m_project_ids = set(pk_set or ())
            instance._m2m_category_ids = {instance.pk}
            instance._m2m_category_slugs = {instance.slug}
        else:
            instance._m2m_project_ids = {instance.pk}
            instance._m2m_category_ids = set(instance.categories.values_list("pk", flat=True))
            instance._m2m_category_slugs = set(instance.categories.values_list("slug", flat=True))
            instance._m2m_category_ids.update(pk_set or ())
        return

    if not action.startswith("post_"):
        return

    project_ids = set(getattr(instance, "_m2m_project_ids", set()))
    category_ids = set(getattr(instance, "_m2m_category_ids", set()))
    category_slugs = set(getattr(instance, "_m2m_category_slugs", set()))

    if reverse:
        project_ids.update(pk_set or ())
        category_ids.add(instance.pk)
        category_slugs.add(instance.slug)
    else:
        project_ids.add(instance.pk)
        category_ids.update(instance.categories.values_list("pk", flat=True))
        category_slugs.update(instance.categories.values_list("slug", flat=True))
        category_ids.update(pk_set or ())

    Projects.objects.filter(pk__in=project_ids).update(updated_at=timezone.now())
    _schedule_membership_rebuild(
        project_ids=project_ids,
        category_ids=category_ids,
        category_slugs=category_slugs,
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


@receiver(pre_save, sender=ProjectCategories)
def project_category_pre_save_handler(sender, instance, **kwargs):
    instance._previous_slug = (
        sender.objects.filter(pk=instance.pk).values_list("slug", flat=True).first()
        if instance.pk
        else None
    )


@receiver(post_save, sender=ProjectCategories)
def project_category_save_handler(sender, instance, **kwargs):
    previous_slug = getattr(instance, "_previous_slug", None)
    stale_slugs = {previous_slug} if previous_slug and previous_slug != instance.slug else set()
    _schedule_all_project_pages_rebuild(stale_category_slugs=stale_slugs)


@receiver(post_delete, sender=ProjectCategories)
def project_category_delete_handler(sender, instance, **kwargs):
    _schedule_all_project_pages_rebuild(stale_category_slugs={instance.slug})


@receiver(post_migrate)
def service_page_projects_post_migrate_handler(sender, **kwargs):
    if sender.name != "projects":
        return

    db_alias = kwargs.get("using") or "default"
    connection = connections[db_alias]
    if ServicePageProjects._meta.db_table not in connection.introspection.table_names():
        return

    with connection.cursor() as cursor:
        columns = connection.introspection.get_table_description(cursor, ServicePageProjects._meta.db_table)
    if "position" not in {column.name for column in columns}:
        return

    ServicePageProjects.ensure_default_pages()
