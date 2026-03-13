import json
from urllib.parse import quote

from django.conf import settings
from django.utils import timezone
from django.utils.safestring import mark_safe

from .rich_text import sanitize_article_body_html


def build_public_article_path(slug: str) -> str:
    return f"/articles/{slug}/"


def build_public_article_url(slug: str) -> str:
    path = build_public_article_path(slug)
    base = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
    if base:
        return f"{base}{path}"
    return path


def build_share_links(url: str, title: str):
    encoded_url = quote(url or "", safe="")
    encoded_title = quote(title or "", safe="")
    return [
        {
            "platform": "whatsapp",
            "url": f"https://wa.me/?text={encoded_title}%20{encoded_url}".strip(),
            "aria_label": "Поделиться в WhatsApp",
        },
        {
            "platform": "telegram",
            "url": f"https://t.me/share/url?url={encoded_url}&text={encoded_title}",
            "aria_label": "Поделиться в Telegram",
        },
    ]


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    return value.strip()


def _format_article_date_ru(dt) -> str:
    month_names = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    if timezone.is_aware(dt):
        dt = timezone.localtime(dt)
    return f"{dt.day} {month_names[dt.month - 1]} {dt.year}"


def _build_article_media(article):
    blocks = article.blocks.all().order_by("order")
    media_list = []
    has_video = False

    for block in blocks:
        if block.type == "image":
            if block.media:
                media_list.append(
                    {
                        "kind": "image",
                        "url": block.media,
                        "caption": _normalize_text(getattr(block, "caption", "")),
                        "alt": _normalize_text(getattr(block, "media_alt", "")) or article.title,
                    }
                )
        elif block.type == "video":
            if block.media:
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


def _build_related_articles(article, limit=6):
    related_qs = (
        article.__class__.objects.filter(is_published=True)
        .exclude(slug=article.slug)
        .order_by("-created_at")[:limit]
    )

    related_articles = []
    for related in related_qs:
        title = _normalize_text(related.title)
        excerpt = _normalize_text(related.excerpt) or _normalize_text(related.seo_description) or title
        related_articles.append(
            {
                "slug": related.slug,
                "title": title,
                "url": build_public_article_path(related.slug),
                "preview_image": related.preview_image or "",
                "preview_image_alt": _normalize_text(related.preview_image_alt) or title,
                "excerpt": excerpt,
            }
        )

    return related_articles


def build_article_render_context(article):
    sanitized_body_html = sanitize_article_body_html(getattr(article, "body_html", ""))
    media_list, has_video = _build_article_media(article)
    related_articles = _build_related_articles(article)

    article_path = build_public_article_path(article.slug)
    article_url = build_public_article_url(article.slug)

    seo_title = _normalize_text(article.seo_title) or article.title
    seo_description = _normalize_text(article.seo_description) or _normalize_text(article.excerpt) or article.title
    seo_keywords = _normalize_text(article.seo_keywords)
    seo_robots = _normalize_text(article.seo_robots) or "index,follow"
    canonical_url = _normalize_text(article.canonical_url) or article_url

    og_title = seo_title
    og_description = seo_description
    og_image = article.preview_image or ""
    og_image_alt = _normalize_text(article.preview_image_alt) or article.title

    twitter_card = "summary_large_image" if og_image else "summary"
    twitter_title = og_title
    twitter_description = og_description
    twitter_image = og_image
    twitter_image_alt = og_image_alt

    article.body_html = mark_safe(sanitized_body_html)
    article.media = media_list
    article.has_video = has_video
    article.url = article_url
    article.path = article_path
    article.published_at_display = _format_article_date_ru(article.created_at)
    article.published_at_iso = article.created_at.isoformat()
    article.updated_at_iso = article.updated_at.isoformat() if article.updated_at else article.created_at.isoformat()
    article.share_links = build_share_links(article_url, seo_title)

    article.seo = {
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
        "twitter_title": twitter_title,
        "twitter_description": twitter_description,
        "twitter_image": twitter_image,
        "twitter_image_alt": twitter_image_alt,
    }

    article_json_ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": seo_title,
        "description": seo_description,
        "datePublished": article.published_at_iso,
        "dateModified": article.updated_at_iso,
        "author": {"@type": "Organization", "name": "Cultnova"},
        "mainEntityOfPage": canonical_url,
        "url": article_url,
    }
    if og_image:
        article_json_ld["image"] = og_image
    if seo_keywords:
        article_json_ld["keywords"] = seo_keywords

    return {
        "article": article,
        "related_articles": related_articles,
        "article_json_ld": mark_safe(json.dumps(article_json_ld, ensure_ascii=False)),
    }
