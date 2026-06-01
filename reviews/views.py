from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .models import HomeReview


@require_GET
def get_home_reviews(request):
    reviews_qs = HomeReview.objects.filter(is_published=True).order_by(
        "sort_order",
        "created_at",
        "pk",
    )

    payload = {
        "data": [
            {
                "id": review.pk,
                "name": review.name,
                "position": review.position,
                "text": review.text,
                "image_url": review.image_url,
                "image_alt": review.image_alt,
            }
            for review in reviews_qs
        ]
    }

    return JsonResponse(payload)

