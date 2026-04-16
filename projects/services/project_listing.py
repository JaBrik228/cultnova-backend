from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit

from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Prefetch, QuerySet
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe

from core.services.build_item_html import (
    get_generated_pages_root,
    sync_frontend_partials_if_configured,
)

from ..models import ProjectCategories, Projects, ProjectsContentBlock
from .project_category_seo import get_resolved_project_category_seo_fields
from .project_rendering import build_public_project_path

PROJECTS_LISTING_PAGE_SIZE = 3
DEFAULT_PUBLIC_CMS_BASE_URL = "https://cms.cultnova.ru"
PROJECTS_HERO_ALT = "Проекты Cultnova"
PROJECTS_HERO_PRELOADS = (
    {
        "href": "/images/projects/projects-mobile-640.webp",
        "media": "(max-width: 500px)",
        "srcset": "/images/projects/projects-mobile-640.webp 640w, /images/projects/projects-mobile-1200.webp 1200w",
        "sizes": "100vw",
        "type": "image/webp",
    },
    {
        "href": "/images/projects/projects-768.webp",
        "media": "(min-width: 501px)",
        "srcset": "/images/projects/projects-768.webp 768w, /images/projects/projects-1170.webp 1170w, /images/projects/projects-1600.webp 1600w",
        "sizes": "(max-width: 1200px) calc(100vw - 48px), 1170px",
        "type": "image/webp",
    },
)
PROJECTS_HERO_SOURCES = (
    {
        "media": "(max-width: 500px)",
        "srcset": "/images/projects/projects-mobile-640.webp 640w, /images/projects/projects-mobile-1200.webp 1200w",
        "sizes": "100vw",
        "type": "image/webp",
    },
    {
        "srcset": "/images/projects/projects-768.webp 768w, /images/projects/projects-1170.webp 1170w, /images/projects/projects-1600.webp 1600w",
        "sizes": "(max-width: 1200px) calc(100vw - 48px), 1170px",
        "type": "image/webp",
    },
)


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    return value.strip()


def _build_public_url(path: str) -> str:
    normalized_path = _normalize_text(path)
    if not normalized_path:
        return ""

    if urlsplit(normalized_path).scheme:
        return normalized_path

    base_url = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
    if not base_url:
        return normalized_path

    if normalized_path.startswith("/"):
        return f"{base_url}{normalized_path}"

    return f"{base_url}/{normalized_path}"


def _get_public_cms_base_url() -> str:
    return getattr(settings, "CMS_PUBLIC_BASE_URL", DEFAULT_PUBLIC_CMS_BASE_URL).rstrip("/")


def build_public_projects_path() -> str:
    return "/projects/"


def build_public_projects_url() -> str:
    return _build_public_url(build_public_projects_path())


def build_public_project_category_path(slug: str) -> str:
    return f"/projects/category/{slug}/"


def build_public_project_category_url(slug: str) -> str:
    return _build_public_url(build_public_project_category_path(slug))


def build_public_projects_api_url(category_slug: str | None = None) -> str:
    base_url = _get_public_cms_base_url()
    if category_slug:
        return f"{base_url}/api/projects/category/{category_slug}/"
    return f"{base_url}/api/projects/"


def get_published_projects_queryset(
    *,
    category_slug: str | None = None,
    include_images: bool = False,
) -> QuerySet[Projects]:
    queryset = (
        Projects.objects.select_related("category")
        .filter(is_published=True)
        .exclude(seo_robots__icontains="noindex")
        .order_by("-created_at")
    )

    if category_slug:
        queryset = queryset.filter(category__slug=category_slug)

    if include_images:
        queryset = queryset.prefetch_related(
            Prefetch(
                "blocks",
                queryset=(
                    ProjectsContentBlock.objects.filter(
                        type=ProjectsContentBlock.IMAGE,
                        media__isnull=False,
                    )
                    .exclude(media="")
                    .order_by("order")
                ),
                to_attr="image_blocks",
            )
        )

    return queryset


def _build_project_images(project: Projects) -> list[dict[str, str]]:
    image_blocks = getattr(project, "image_blocks", None)
    if image_blocks is None:
        image_blocks = (
            project.blocks.filter(
                type=ProjectsContentBlock.IMAGE,
                media__isnull=False,
            )
            .exclude(media="")
            .order_by("order")
        )

    project_title = _normalize_text(project.title) or project.title
    images = []

    for block in image_blocks:
        if not block.media:
            continue

        images.append(
            {
                "url": block.media,
                "alt": _normalize_text(block.media_alt) or project_title,
            }
        )

    return images


def build_project_card_payload(
    project: Projects,
    *,
    include_images: bool = False,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": project.id,
        "title": project.title,
        "slug": project.slug,
        "customer_name": project.customer_name,
        "year": project.year,
        "type": project.type,
        "category_title": _normalize_text(getattr(project.category, "title", "")),
        "preview": project.preview_image or None,
        "preview_image_alt": _normalize_text(project.preview_image_alt),
        "excerpt": _normalize_text(project.excerpt) or _normalize_text(project.seo_description),
        "url": build_public_project_path(project.slug),
    }

    if include_images:
        payload["images"] = _build_project_images(project)

    return payload


def build_paginated_projects_payload(
    projects_page,
    *,
    page_key: str = "current_page",
    include_images: bool = False,
) -> dict[str, object]:
    has_next_page = projects_page.has_next()

    return {
        page_key: projects_page.number,
        "has_next": has_next_page,
        "has_previous": projects_page.has_previous(),
        "next_page": projects_page.next_page_number() if has_next_page else None,
        "data": [
            build_project_card_payload(project, include_images=include_images)
            for project in projects_page
        ],
    }


def _build_projects_collection_json_ld(
    *,
    title: str,
    description: str,
    canonical_url: str,
    hero_image: str,
    breadcrumbs: list[dict[str, str]],
    projects: list[dict[str, object]],
) -> str:
    site_url = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
    if not site_url:
        parsed_canonical = urlsplit(canonical_url)
        if parsed_canonical.scheme and parsed_canonical.netloc:
            site_url = f"{parsed_canonical.scheme}://{parsed_canonical.netloc}"
        else:
            site_url = canonical_url.rstrip("/")
    organization_id = f"{site_url}/#organization"
    website_id = f"{site_url}/#website"
    webpage_id = f"{canonical_url}#webpage"
    breadcrumbs_id = f"{canonical_url}#breadcrumbs"
    item_list_id = f"{canonical_url}#item-list"

    breadcrumb_items = []
    for position, breadcrumb in enumerate(breadcrumbs, start=1):
        breadcrumb_title = _normalize_text(breadcrumb.get("title", ""))
        breadcrumb_url = _build_public_url(breadcrumb.get("url", ""))

        if not breadcrumb_title or not breadcrumb_url:
            continue

        breadcrumb_items.append(
            {
                "@type": "ListItem",
                "position": position,
                "name": breadcrumb_title,
                "item": breadcrumb_url,
            }
        )

    item_list_elements = []
    for position, project in enumerate(projects, start=1):
        slug = _normalize_text(str(project.get("slug") or ""))
        project_title = _normalize_text(str(project.get("title") or ""))
        project_url = _build_public_url(build_public_project_path(slug))

        if not slug or not project_title or not project_url:
            continue

        item = {
            "@type": "CreativeWork",
            "@id": project_url,
            "name": project_title,
            "url": project_url,
        }

        description_value = _normalize_text(str(project.get("excerpt") or ""))
        if description_value:
            item["description"] = description_value

        preview_image = _normalize_text(str(project.get("preview") or ""))
        if preview_image:
            item["image"] = preview_image

        item_list_elements.append(
            {
                "@type": "ListItem",
                "position": position,
                "item": item,
            }
        )

    page_node: dict[str, object] = {
        "@type": ["WebPage", "CollectionPage"],
        "@id": webpage_id,
        "name": title,
        "description": description,
        "url": canonical_url,
        "mainEntityOfPage": canonical_url,
        "inLanguage": "ru-RU",
        "isPartOf": {
            "@id": website_id,
        },
        "about": {
            "@id": organization_id,
        },
        "publisher": {
            "@id": organization_id,
        },
        "primaryImageOfPage": {
            "@type": "ImageObject",
            "url": _build_public_url(hero_image),
        },
        "breadcrumb": {
            "@id": breadcrumbs_id,
        },
    }

    payload_graph: list[dict[str, object]] = [
        {
            "@type": "Organization",
            "@id": organization_id,
            "name": "Cultnova",
            "alternateName": "cultivating innovation",
            "url": _build_public_url("/"),
            "description": "Cultnova проектирует музеи, выставки и интерактивные пространства.",
            "email": "info@cultnova.ru",
            "telephone": "+7 (921) 894-67-34",
            "sameAs": [
                "https://www.linkedin.com/company/106256344",
            ],
            "logo": {
                "@type": "ImageObject",
                "@id": f"{site_url}/#logo",
                "url": "https://cultnova-media.hb.ru-msk.vkcloud-storage.ru/site-icons/logo.svg",
                "contentUrl": "https://cultnova-media.hb.ru-msk.vkcloud-storage.ru/site-icons/logo.svg",
                "thumbnailUrl": "https://cultnova-media.hb.ru-msk.vkcloud-storage.ru/site-icons/favicon.svg",
                "caption": "Cultnova",
            },
            "address": {
                "@type": "PostalAddress",
                "postalCode": "195267",
                "addressCountry": "RU",
                "addressRegion": "Санкт-Петербург",
                "addressLocality": "Санкт-Петербург",
                "streetAddress": "Суздальский пр-кт, 105к1",
            },
            "contactPoint": [
                {
                    "@type": "ContactPoint",
                    "contactType": "customer support",
                    "telephone": "+7 (921) 894-67-34",
                    "email": "info@cultnova.ru",
                    "availableLanguage": ["Russian"],
                    "areaServed": "RU",
                    "hoursAvailable": {
                        "@type": "OpeningHoursSpecification",
                        "dayOfWeek": [
                            "https://schema.org/Monday",
                            "https://schema.org/Tuesday",
                            "https://schema.org/Wednesday",
                            "https://schema.org/Thursday",
                            "https://schema.org/Friday",
                        ],
                        "opens": "09:00",
                        "closes": "18:00",
                    },
                }
            ],
        },
        {
            "@type": "WebSite",
            "@id": website_id,
            "url": _build_public_url("/"),
            "name": "Cultnova",
            "alternateName": "cultivating innovation",
            "inLanguage": "ru-RU",
            "publisher": {
                "@id": organization_id,
            },
        },
        page_node,
        {
            "@type": "BreadcrumbList",
            "@id": breadcrumbs_id,
            "itemListElement": breadcrumb_items,
        },
    ]

    if item_list_elements:
        payload_graph.append(
            {
                "@type": "ItemList",
                "@id": item_list_id,
                "itemListOrder": "https://schema.org/ItemListOrderDescending",
                "numberOfItems": len(item_list_elements),
                "itemListElement": item_list_elements,
            }
        )
        page_node["mainEntity"] = {
            "@id": item_list_id,
        }

    payload = {
        "@context": "https://schema.org",
        "@graph": payload_graph,
    }
    return mark_safe(json.dumps(payload, ensure_ascii=False))


def build_projects_listing_context(
    *,
    active_category: ProjectCategories | None = None,
    page_size: int = PROJECTS_LISTING_PAGE_SIZE,
) -> dict[str, object]:
    categories = list(ProjectCategories.objects.order_by("-created_at", "title"))
    projects_page = Paginator(
        get_published_projects_queryset(
            category_slug=active_category.slug if active_category else None,
            include_images=False,
        ),
        page_size,
    ).get_page(1)
    projects = [build_project_card_payload(project) for project in projects_page.object_list]

    if active_category is None:
        page_title = "Проекты"
        page_description = "Проекты компании Cultnova."
        page_url = build_public_projects_url()
        page_canonical = page_url
        page_keywords = ""
        page_robots = "index,follow"
        page_heading = "Проекты"
        page_path = build_public_projects_path()
        api_endpoint = build_public_projects_api_url()
        empty_title = "Пока нет опубликованных проектов."
        empty_copy = "Когда в портфолио появятся новые кейсы, они будут показаны на этой странице."
        breadcrumbs = [
            {"title": "Главная", "url": "/"},
            {"title": "Проекты", "url": build_public_projects_path()},
        ]
    else:
        category_seo_fields = get_resolved_project_category_seo_fields(active_category)
        page_title = _normalize_text(category_seo_fields["seo_title"]) or f"{active_category.title} | Проекты"
        page_description = _normalize_text(category_seo_fields["seo_description"]) or (
            f"Проекты Cultnova в категории «{active_category.title}»."
        )
        page_keywords = _normalize_text(category_seo_fields["seo_keywords"])
        page_robots = _normalize_text(active_category.seo_robots) or "index,follow"
        page_url = build_public_project_category_url(active_category.slug)
        page_canonical = _normalize_text(active_category.canonical_url) or page_url
        page_heading = _normalize_text(category_seo_fields["page_h1"]) or "Проекты"
        page_path = build_public_project_category_path(active_category.slug)
        api_endpoint = build_public_projects_api_url(active_category.slug)
        empty_title = f"В категории «{active_category.title}» пока нет опубликованных проектов."
        empty_copy = "Как только в этой категории появятся новые кейсы, они будут показаны на странице."
        breadcrumbs = [
            {"title": "Главная", "url": "/"},
            {"title": "Проекты", "url": build_public_projects_path()},
            {"title": active_category.title, "url": build_public_project_category_path(active_category.slug)},
        ]

    category_links = [
        {
            "title": "Все",
            "url": build_public_projects_path(),
            "is_active": active_category is None,
        }
    ]
    category_links.extend(
        {
            "title": category.title,
            "url": build_public_project_category_path(category.slug),
            "is_active": active_category is not None and category.pk == active_category.pk,
        }
        for category in categories
    )

    has_next_page = projects_page.has_next()
    initial_feed = {
        "endpoint": api_endpoint,
        "page_size": page_size,
        "current_page": projects_page.number,
        "next_page": projects_page.next_page_number() if has_next_page else "",
        "has_next": has_next_page,
    }

    page_image = projects[0]["preview"] if projects else "/images/projects/projects.png"

    return {
        "page": {
            "title": page_title,
            "description": page_description,
            "keywords": page_keywords,
            "url": page_canonical,
            "path": page_path,
            "canonical": page_canonical,
            "robots": page_robots,
            "heading": page_heading,
            "active_category_title": active_category.title if active_category else "",
            "hero_image": "/images/projects/projects-1170.webp",
            "hero_preloads": list(PROJECTS_HERO_PRELOADS),
            "hero_sources": list(PROJECTS_HERO_SOURCES),
            "hero_fallback_srcset": PROJECTS_HERO_SOURCES[1]["srcset"],
            "hero_sizes": "(max-width: 1200px) calc(100vw - 48px), 1170px",
            "hero_image_alt": PROJECTS_HERO_ALT,
            "share_image": page_image or "",
        },
        "breadcrumbs": breadcrumbs,
        "categories": category_links,
        "projects": projects,
        "projects_feed": initial_feed,
        "empty_state": {
            "title": empty_title,
            "copy": empty_copy,
        },
        "collection_json_ld": _build_projects_collection_json_ld(
            title=page_title,
            description=page_description,
            canonical_url=page_canonical,
            hero_image="/images/projects/projects-1170.webp",
            breadcrumbs=breadcrumbs,
            projects=projects,
        ),
    }


def _write_text_atomically(target_path: Path, content: str) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile("w", encoding="utf-8", dir=target_path.parent, delete=False) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)

    temp_path.replace(target_path)
    os.chmod(target_path, 0o644)


def _get_projects_listing_output_path() -> Path:
    return get_generated_pages_root() / "projects" / "index.html"


def _get_project_category_output_path(slug: str) -> Path:
    return get_generated_pages_root() / "projects" / "category" / slug / "index.html"


def build_projects_listing_static_html(
    *,
    active_category: ProjectCategories | None = None,
    sync_partials: bool = True,
) -> Path:
    if sync_partials:
        sync_frontend_partials_if_configured()

    context = build_projects_listing_context(active_category=active_category)
    html_content = render_to_string("projects_listing.html", context)
    output_path = (
        _get_project_category_output_path(active_category.slug)
        if active_category is not None
        else _get_projects_listing_output_path()
    )
    _write_text_atomically(output_path, html_content)
    return output_path


def delete_project_category_listing_static_html(slug: str) -> None:
    output_path = _get_project_category_output_path(slug)
    category_dir = output_path.parent
    category_root = category_dir.parent

    if output_path.exists():
        output_path.unlink()

    if category_dir.exists() and not any(category_dir.iterdir()):
        category_dir.rmdir()

    if category_root.exists() and not any(category_root.iterdir()):
        category_root.rmdir()


def prune_stale_project_category_listing_pages(valid_slugs: list[str] | set[str]) -> None:
    category_root = get_generated_pages_root() / "projects" / "category"
    if not category_root.exists():
        return

    valid_slug_set = {slug for slug in valid_slugs if slug}
    for path in category_root.iterdir():
        if not path.is_dir():
            continue
        if path.name in valid_slug_set:
            continue
        shutil.rmtree(path, ignore_errors=True)

    if category_root.exists() and not any(category_root.iterdir()):
        category_root.rmdir()


def rebuild_projects_listing_static_html(
    *,
    category_slugs: list[str] | set[str] | tuple[str, ...] | None = None,
    stale_category_slugs: list[str] | set[str] | tuple[str, ...] = (),
    prune_stale: bool = False,
) -> list[Path]:
    sync_frontend_partials_if_configured()

    written_paths = [build_projects_listing_static_html(sync_partials=False)]

    if category_slugs is None:
        categories = list(ProjectCategories.objects.order_by("-created_at", "title"))
        for category in categories:
            written_paths.append(
                build_projects_listing_static_html(
                    active_category=category,
                    sync_partials=False,
                )
            )

        if prune_stale:
            prune_stale_project_category_listing_pages({category.slug for category in categories})

        return written_paths

    normalized_category_slugs = sorted({slug for slug in category_slugs if slug})
    for slug in normalized_category_slugs:
        category = ProjectCategories.objects.filter(slug=slug).first()
        if category is None:
            delete_project_category_listing_static_html(slug)
            continue

        written_paths.append(
            build_projects_listing_static_html(
                active_category=category,
                sync_partials=False,
            )
        )

    for slug in {slug for slug in stale_category_slugs if slug}:
        if ProjectCategories.objects.filter(slug=slug).exists():
            continue
        delete_project_category_listing_static_html(slug)

    return written_paths
