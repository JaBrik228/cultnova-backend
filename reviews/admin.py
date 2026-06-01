import mimetypes

from django import forms
from django.contrib import admin
from django.utils.safestring import mark_safe

from core.services.vk_cloud_storage import upload_media_to_vk_cloud

from .models import HomeReview


def _trim(value):
    if isinstance(value, str):
        return value.strip()
    return value


class HomeReviewAdminForm(forms.ModelForm):
    upload_image = forms.FileField(required=False, label="Загрузить изображение")

    class Meta:
        model = HomeReview
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["image_url"].required = False
        self.fields["image_alt"].required = False

    def clean(self):
        cleaned_data = super().clean()

        upload_image = cleaned_data.get("upload_image")
        image_url = _trim(cleaned_data.get("image_url")) or ""
        image_alt = _trim(cleaned_data.get("image_alt")) or ""

        if upload_image:
            allowed_content_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
            guessed_content_type, _ = mimetypes.guess_type(upload_image.name)
            content_type = (getattr(upload_image, "content_type", "") or guessed_content_type or "").lower()

            if content_type not in allowed_content_types:
                self.add_error("upload_image", "Поддерживаются только JPG, PNG, WEBP и GIF.")

        if not image_url and not upload_image and not getattr(self.instance, "image_url", ""):
            self.add_error("image_url", "Укажите ссылку на изображение или загрузите файл.")

        if (image_url or upload_image or getattr(self.instance, "image_url", "")) and not image_alt:
            self.add_error("image_alt", "Alt text обязателен для изображения.")

        for field_name in ("name", "position", "text"):
            value = _trim(cleaned_data.get(field_name)) or ""
            if not value:
                self.add_error(field_name, "Это поле обязательно.")
            else:
                cleaned_data[field_name] = value

        cleaned_data["image_url"] = image_url
        cleaned_data["image_alt"] = image_alt
        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        image_file = self.cleaned_data.get("upload_image")

        if image_file:
            try:
                instance.image_url = upload_media_to_vk_cloud(image_file, folder="reviews/home")
            except Exception as exc:
                raise forms.ValidationError("Не удалось загрузить изображение в VK Cloud.") from exc
            self.cleaned_data["image_url"] = instance.image_url

        for field_name in ("name", "position", "text", "image_url", "image_alt"):
            value = self.cleaned_data.get(field_name)
            if isinstance(value, str):
                setattr(instance, field_name, value.strip())

        if commit:
            instance.save()

        return instance


@admin.register(HomeReview)
class HomeReviewAdmin(admin.ModelAdmin):
    form = HomeReviewAdminForm
    save_on_top = True
    list_display = ("name", "position", "sort_order", "is_published", "created_at", "updated_at")
    list_display_links = ("name",)
    list_editable = ("sort_order", "is_published")
    list_filter = ("is_published", "created_at", "updated_at")
    search_fields = ("name", "position", "text", "image_url")
    ordering = ("sort_order", "created_at", "pk")
    readonly_fields = ("image_preview_box", "created_at", "updated_at")
    fieldsets = (
        (
            "Контент",
            {
                "fields": (
                    "name",
                    "position",
                    "text",
                    "upload_image",
                    "image_url",
                    "image_alt",
                    "image_preview_box",
                    "sort_order",
                    "is_published",
                ),
            },
        ),
        (
            "Система",
            {
                "fields": ("created_at", "updated_at"),
                "classes": ("collapse",),
            },
        ),
    )

    def image_preview_box(self, obj):
        if obj.image_url:
            return mark_safe(f'<img src="{obj.image_url}" style="max-height: 200px;"/>')
        return "Изображение не загружено"

    image_preview_box.short_description = "Текущее изображение"
