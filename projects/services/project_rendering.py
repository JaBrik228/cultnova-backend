import json

from django.conf import settings
from django.utils.safestring import mark_safe

from blog.services.article_rendering import build_share_links
from blog.services.rich_text import sanitize_rich_body_html


def build_public_project_path(slug: str) -> str:
    return f"/projects/{slug}/"


def build_public_project_url(slug: str) -> str:
    path = build_public_project_path(slug)
    base = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
    if base:
        return f"{base}{path}"
    return path


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    return value.strip()


def _build_project_media(project):
    media_list = []
    has_video = False

    for block in project.blocks.all().order_by("order"):
        if block.type == "image" and block.media:
            media_list.append(
                {
                    "kind": "image",
                    "url": block.media,
                    "caption": _normalize_text(getattr(block, "caption", "")),
                    "alt": _normalize_text(getattr(block, "media_alt", "")) or project.title,
                }
            )
        elif block.type == "video" and block.media:
            has_video = True
            media_list.append(
                {
                    "kind": "video",
                    "poster": block.first_video_frame,
                    "sources": [{"url": block.media, "type": "video/mp4"}],
                    "caption": _normalize_text(getattr(block, "caption", "")),
                }
            )

    return media_list, has_video


def _split_feature_media(media_list):
    if not media_list:
        return None, []

    feature_media = None
    for item in media_list:
        if item.get("kind") == "video":
            feature_media = item
            break

    if feature_media is None:
        feature_media = media_list[0]

    gallery = [item for item in media_list if item is not feature_media]
    return feature_media, gallery


def _build_related_projects(project, limit=6):
    same_category = (
        project.__class__.objects.filter(is_published=True, category_id=project.category_id)
        .exclude(pk=project.pk)
        .order_by("-created_at")
    )

    payload = []
    for item in same_category[:limit]:
        title = _normalize_text(item.title)
        excerpt = _normalize_text(item.excerpt) or _normalize_text(item.seo_description) or title
        payload.append(
            {
                "slug": item.slug,
                "title": title,
                "url": build_public_project_path(item.slug),
                "category_title": _normalize_text(getattr(item.category, "title", "")),
                "preview_image": item.preview_image or "",
                "preview_image_alt": _normalize_text(item.preview_image_alt) or title,
                "excerpt": excerpt,
            }
        )

    return payload


def build_project_render_context(project):
    sanitized_body_html = sanitize_rich_body_html(getattr(project, "body_html", ""))
    media_list, has_video = _build_project_media(project)
    feature_media, gallery_media = _split_feature_media(media_list)
    related_projects = _build_related_projects(project)

    project_path = build_public_project_path(project.slug)
    project_url = build_public_project_url(project.slug)

    seo_title = _normalize_text(project.seo_title) or project.title
    seo_description = _normalize_text(project.seo_description) or _normalize_text(project.excerpt) or project.title
    seo_keywords = _normalize_text(project.seo_keywords)
    seo_robots = _normalize_text(project.seo_robots) or "index,follow"
    canonical_url = _normalize_text(project.canonical_url) or project_url

    og_title = seo_title
    og_description = seo_description
    og_image = project.preview_image or ""
    og_image_alt = _normalize_text(project.preview_image_alt) or project.title

    twitter_card = "summary_large_image" if og_image else "summary"

    project.body_html = mark_safe(sanitized_body_html)
    project.media = media_list
    project.feature_media = feature_media
    project.gallery_media = gallery_media
    project.has_video = has_video
    project.url = project_url
    project.path = project_path
    project.share_links = build_share_links(project_url, seo_title)

    project.seo = {
        "title": seo_title,
        "description": seo_description,
        "keywords": seo_keywords,
        "robots": seo_robots,
        "canonical": canonical_url,
        "og_title": og_title,
        "og_description": og_description,
        "og_image": og_image,
        "og_image_alt": og_image_alt,
        "twitter_card": twitter_card,
        "twitter_title": og_title,
        "twitter_description": og_description,
        "twitter_image": og_image,
        "twitter_image_alt": og_image_alt,
    }

    project_json_ld = {
        "@context": "https://schema.org",
        "@type": "CreativeWork",
        "name": seo_title,
        "description": seo_description,
        "url": project_url,
        "mainEntityOfPage": canonical_url,
        "creator": {"@type": "Organization", "name": "Cultnova"},
        "keywords": seo_keywords,
    }

    if og_image:
        project_json_ld["image"] = og_image

    if getattr(project, "created_at", None):
        project_json_ld["dateCreated"] = project.created_at.isoformat()
    if getattr(project, "updated_at", None):
        project_json_ld["dateModified"] = project.updated_at.isoformat()

    return {
        "project": project,
        "related_projects": related_projects,
        "project_json_ld": mark_safe(json.dumps(project_json_ld, ensure_ascii=False)),
    }
