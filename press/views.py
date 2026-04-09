from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import PressItem


def _sanitize_limit(raw_value, default=10, max_value=100):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        return default

    return min(max(value, 1), max_value)


@require_GET
def get_press_feed(request):
    page = request.GET.get("page", 1)
    limit = _sanitize_limit(request.GET.get("limit", 10))

    items_qs = PressItem.objects.filter(is_published=True).order_by(
        "sort_order",
        "created_at",
        "pk",
    )
    paginator = Paginator(items_qs, limit)
    items_page = paginator.get_page(page)
    has_next_page = items_page.has_next()

    payload = {
        "current_page": items_page.number,
        "has_next": has_next_page,
        "has_previous": items_page.has_previous(),
        "next_page": items_page.next_page_number() if has_next_page else None,
        "data": [
            {
                "title": item.title,
                "description": item.description,
                "url": item.url,
            }
            for item in items_page
        ],
    }

    return JsonResponse(payload)
