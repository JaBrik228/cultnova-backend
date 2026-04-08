from django import forms
from django.contrib import admin

from .models import PressItem


def _trim(value):
    if isinstance(value, str):
        return value.strip()
    return value


class PressItemAdminForm(forms.ModelForm):
    class Meta:
        model = PressItem
        fields = "__all__"

    def clean_title(self):
        return _trim(self.cleaned_data.get("title"))

    def clean_description(self):
        return _trim(self.cleaned_data.get("description"))

    def clean_url(self):
        return _trim(self.cleaned_data.get("url"))


@admin.register(PressItem)
class PressItemAdmin(admin.ModelAdmin):
    form = PressItemAdminForm
    save_on_top = True
    list_display = ("title", "sort_order", "is_published", "created_at", "updated_at")
    list_display_links = ("title",)
    list_editable = ("sort_order", "is_published")
    list_filter = ("is_published", "created_at", "updated_at")
    search_fields = ("title", "description", "url")
    ordering = ("sort_order", "created_at", "pk")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Content",
            {
                "fields": ("title", "description", "url", "sort_order", "is_published"),
            },
        ),
        (
            "System",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

