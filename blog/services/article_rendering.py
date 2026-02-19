import json

from django.conf import settings
from django.utils.html import escape
from django.utils.safestring import mark_safe


def build_public_article_path(slug: str) -> str:
    return f"/articles/{slug}/"


def build_public_article_url(slug: str) -> str:
    path = build_public_article_path(slug)
    base = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
    if base:
        return f"{base}{path}"
    return path


def _normalize_text(value: str) -> str:
    if not value:
        return ""
    return value.strip()


def _build_article_body_and_media(article):
    blocks = article.blocks.all().order_by("order")
    html_parts = []
    media_list = []
    has_video = False

    for block in blocks:
        block_text = _normalize_text(block.text)

        if block.type == "heading":
            if block_text:
                html_parts.append(f'<h3 class="article__subtitle">{escape(block_text)}</h3>')
        elif block.type == "text":
            if block_text:
                paragraphs = block_text.split("\n")
                for paragraph in paragraphs:
                    paragraph = _normalize_text(paragraph)
                    if paragraph:
                        html_parts.append(f"<p>{escape(paragraph)}</p>")
        elif block.type == "image":
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

    return mark_safe("".join(html_parts)), media_list, has_video


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
    body_html, media_list, has_video = _build_article_body_and_media(article)
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

    article.body_html = body_html
    article.media = media_list
    article.has_video = has_video
    article.url = article_url
    article.path = article_path
    article.published_at_display = article.created_at.strftime("%d.%m.%Y")
    article.published_at_iso = article.created_at.isoformat()
    article.updated_at_iso = article.updated_at.isoformat() if article.updated_at else article.created_at.isoformat()

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
