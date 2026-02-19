from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render

from blog.services.article_rendering import build_article_render_context, build_public_article_path

from .models import Articles


def _sanitize_limit(raw_value, default=10, max_value=100):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default
    return min(max(value, 1), max_value)


def get_articles_list(request):
    page = request.GET.get("page", 1)
    limit = _sanitize_limit(request.GET.get("limit", 10))

    articles_qs = Articles.objects.filter(is_published=True).order_by("-created_at")
    paginator = Paginator(articles_qs, limit)
    articles_page = paginator.get_page(page)

    has_next_page = articles_page.has_next()
    payload = {
        "current_page": articles_page.number,
        "has_next": has_next_page,
        "has_previous": articles_page.has_previous(),
        "next_page": articles_page.next_page_number() if has_next_page else None,
        "data": [],
    }

    for article in articles_page:
        payload["data"].append(
            {
                "id": article.id,
                "slug": article.slug,
                "title": article.title,
                "excerpt": (article.excerpt or article.seo_description or "").strip(),
                "preview_image": article.preview_image or None,
                "preview_image_alt": (article.preview_image_alt or "").strip(),
                "url": build_public_article_path(article.slug),
            }
        )

    return JsonResponse(payload, safe=False)


def get_article_detail(request, slug):
    article = get_object_or_404(Articles, slug=slug, is_published=True)
    context = build_article_render_context(article)
    return render(request, "article_detail.html", context)
