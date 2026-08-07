from django.db.models import Prefetch

from projects.models import ProjectCategories, Projects


def get_ordered_project_categories_prefetch(
    relation: str = "categories",
    *,
    to_attr: str = "ordered_categories",
) -> Prefetch:
    return Prefetch(
        relation,
        queryset=ProjectCategories.objects.ordered(),
        to_attr=to_attr,
    )


def build_project_categories_payload(project: Projects) -> list[dict[str, object]]:
    return [
        {
            "id": category.id,
            "title": category.title,
            "slug": category.slug,
            "sort_order": category.sort_order,
        }
        for category in project.get_ordered_categories()
    ]
