from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import PressItem


@require_GET
def get_press_feed(request):
    items = PressItem.objects.filter(is_published=True).order_by("sort_order", "created_at", "pk")

    payload = [
        {
            "title": item.title,
            "description": item.description,
            "url": item.url,
        }
        for item in items
    ]

    return JsonResponse({"data": payload})

