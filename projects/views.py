from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from projects.services.project_listing import (
    build_paginated_projects_payload,
    build_projects_listing_context,
    get_published_projects_queryset,
)
from projects.services.project_rendering import build_project_render_context

from .models import ProjectCategories, Projects, ProjectsContentBlock


def _sanitize_limit(raw_value, default=10, max_value=100):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return min(max(value, 1), max_value)


def get_all_categories(request):
    categories = ProjectCategories.objects.all()

    payload = []
    for category in categories:
        payload.append(
            {
                "id": category.id,
                "title": category.title,
                "slug": category.slug,
                "created_at": category.created_at,
            }
        )

    return JsonResponse(payload, safe=False)


def get_projects_list(request):
    context = build_projects_listing_context()
    return render(request, "projects_listing.html", context)


def get_projects_category_list(request, slug):
    category = get_object_or_404(ProjectCategories, slug=slug)
    context = build_projects_listing_context(active_category=category)
    return render(request, "projects_listing.html", context)


def get_all_projects(request):
    page = request.GET.get("page", 1)
    limit = _sanitize_limit(request.GET.get("limit", 10))

    projects_qs = get_published_projects_queryset(include_images=True)
    paginator = Paginator(projects_qs, limit)
    projects_page = paginator.get_page(page)

    payload = build_paginated_projects_payload(
        projects_page,
        page_key="current_page",
        include_images=True,
    )

    return JsonResponse(payload, safe=False)


def get_projects_by_category(request, slug):
    page = request.GET.get("page", 1)
    limit = _sanitize_limit(request.GET.get("limit", 10))

    projects_qs = get_published_projects_queryset(category_slug=slug)
    paginator = Paginator(projects_qs, limit)
    projects_page = paginator.get_page(page)

    payload = build_paginated_projects_payload(
        projects_page,
        page_key="page",
    )

    return JsonResponse(payload, safe=False)


def get_projects_details(request, slug):
    project = get_object_or_404(Projects, slug=slug, is_published=True)

    data = []
    for block in project.blocks.all().order_by("order"):
        block_object_data = {
            "type": block.type,
        }

        if block.type == ProjectsContentBlock.IMAGE:
            block_object_data["content"] = block.media if block.media else None
            block_object_data["media_alt"] = (block.media_alt or "").strip()
            block_object_data["caption"] = (block.caption or "").strip()
        elif block.type == ProjectsContentBlock.VIDEO:
            block_object_data["content"] = block.media if block.media else None
            block_object_data["first_video_frame"] = block.first_video_frame if block.first_video_frame else None
            block_object_data["caption"] = (block.caption or "").strip()
        elif block.type in {ProjectsContentBlock.TEXT, ProjectsContentBlock.HEADING}:
            block_object_data["content"] = block.text

        data.append(block_object_data)

    return JsonResponse(data, safe=False)


def get_project_detail_full(request, slug):
    project = get_object_or_404(Projects, slug=slug, is_published=True)

    context = build_project_render_context(project)
    rendered_project = context["project"]

    payload = {
        "id": rendered_project.id,
        "slug": rendered_project.slug,
        "title": rendered_project.title,
        "category": {
            "id": rendered_project.category_id,
            "title": rendered_project.category.title,
            "slug": rendered_project.category.slug,
        },
        "customer_name": rendered_project.customer_name,
        "year": rendered_project.year,
        "type": rendered_project.type,
        "excerpt": rendered_project.excerpt,
        "body_html": str(rendered_project.body_html),
        "preview_image": rendered_project.preview_image,
        "preview_image_alt": rendered_project.preview_image_alt,
        "seo": rendered_project.seo,
        "url": rendered_project.url,
        "path": rendered_project.path,
        "media": rendered_project.media,
        "share_links": rendered_project.share_links,
    }

    return JsonResponse(payload, safe=False)


def get_project_detail(request, slug):
    project = get_object_or_404(Projects, slug=slug, is_published=True)
    context = build_project_render_context(project)
    return render(request, "project_detail.html", context)
