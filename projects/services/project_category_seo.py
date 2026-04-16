from __future__ import annotations

from datetime import datetime, timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.utils import timezone

CURRENT_YEAR_TOKEN = "{{current_year}}"
PROJECT_CATEGORY_CURRENT_YEAR_TIMEZONE = ZoneInfo("Europe/Moscow")
PROJECT_CATEGORY_CURRENT_YEAR_FIELDS = (
    "page_h1",
    "seo_title",
    "seo_description",
    "seo_keywords",
)
PROJECT_CATEGORY_CURRENT_YEAR_HELP_TEXT = (
    f"Можно использовать {CURRENT_YEAR_TOKEN}. "
    f'Например: "Проекты музеев {CURRENT_YEAR_TOKEN}". '
    "Текущий год считается по Москве."
)


def _ensure_aware(moment: datetime) -> datetime:
    if timezone.is_naive(moment):
        return moment.replace(tzinfo=dt_timezone.utc)
    return moment


def get_project_category_current_year(*, now: datetime | None = None) -> int:
    current_moment = _ensure_aware(now or timezone.now())
    return current_moment.astimezone(PROJECT_CATEGORY_CURRENT_YEAR_TIMEZONE).year


def resolve_project_category_seo_text(value: str, *, now: datetime | None = None) -> str:
    if not isinstance(value, str) or not value:
        return value or ""
    return value.replace(CURRENT_YEAR_TOKEN, str(get_project_category_current_year(now=now)))


def get_resolved_project_category_seo_fields(category, *, now: datetime | None = None) -> dict[str, str]:
    return {
        field_name: resolve_project_category_seo_text(getattr(category, field_name, "") or "", now=now)
        for field_name in PROJECT_CATEGORY_CURRENT_YEAR_FIELDS
    }
