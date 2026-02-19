from django import forms
from django.conf import settings
from django.contrib import admin
from django.utils.html import format_html, mark_safe

from core.services.vk_cloud_storage import upload_media_to_vk_cloud

from .models import Articles, ArticlesContentBlock


def _trim(value):
    if isinstance(value, str):
        return value.strip()
    return value


def _build_public_article_path(slug: str) -> str:
    return f"/articles/{slug}/"


def _build_public_article_url(slug: str) -> str:
    path = _build_public_article_path(slug)
    base = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
    if base:
        return f"{base}{path}"
    return path


class ArticlesAdminForm(forms.ModelForm):
    upload_image = forms.ImageField(required=False, label="Upload preview image")

    class Meta:
        model = Articles
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        seo_title = _trim(cleaned_data.get("seo_title")) or ""
        seo_description = _trim(cleaned_data.get("seo_description")) or ""
        preview_image_alt = _trim(cleaned_data.get("preview_image_alt")) or ""
        upload_image = cleaned_data.get("upload_image")

        if not seo_title:
            self.add_error("seo_title", "SEO title is required.")
        if not seo_description:
            self.add_error("seo_description", "SEO description is required.")

        has_preview = bool(
            upload_image
            or cleaned_data.get("preview_image")
            or (self.instance and self.instance.preview_image)
        )
        if has_preview and not preview_image_alt:
            self.add_error("preview_image_alt", "Alt text is required when preview image is set.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        image_file = self.cleaned_data.get("upload_image")

        if image_file:
            try:
                instance.preview_image = upload_media_to_vk_cloud(image_file)
            except Exception:
                raise forms.ValidationError("Failed to upload media to VK Cloud.")

        for field_name in (
            "excerpt",
            "preview_image_alt",
            "seo_title",
            "seo_description",
            "seo_keywords",
            "seo_robots",
            "canonical_url",
        ):
            value = self.cleaned_data.get(field_name)
            if isinstance(value, str):
                setattr(instance, field_name, value.strip())

        if commit:
            instance.save()

        return instance


class ContentBlockAdminForm(forms.ModelForm):
    upload_media = forms.FileField(required=False, label="Media")
    upload_first_frame = forms.ImageField(required=False, label="Video first frame")

    class Meta:
        model = ArticlesContentBlock
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        block_type = cleaned_data.get("type")
        text = _trim(cleaned_data.get("text")) or ""
        media_alt = _trim(cleaned_data.get("media_alt")) or ""

        media_file = cleaned_data.get("upload_media")
        current_media_url = self.instance.media if self.instance else None

        frame_file = cleaned_data.get("upload_first_frame")
        current_frame_url = self.instance.first_video_frame if self.instance else None

        if block_type == ArticlesContentBlock.IMAGE:
            if not media_file and not current_media_url:
                raise forms.ValidationError({"upload_media": "Image is required for image block."})
            if text:
                raise forms.ValidationError({"text": "Image block cannot contain text."})
            if not media_alt:
                raise forms.ValidationError({"media_alt": "Alt text is required for image block."})

        elif block_type == ArticlesContentBlock.VIDEO:
            if not media_file and not current_media_url:
                raise forms.ValidationError({"upload_media": "Video is required for video block."})
            if not frame_file and not current_frame_url:
                raise forms.ValidationError({"upload_first_frame": "First frame is required for video block."})
            if text:
                raise forms.ValidationError({"text": "Video block cannot contain text."})

        elif block_type in [ArticlesContentBlock.TEXT, ArticlesContentBlock.HEADING]:
            if not text:
                raise forms.ValidationError({"text": "Text is required for text or heading block."})
            if media_file or current_media_url:
                raise forms.ValidationError({"upload_media": "Text and heading blocks cannot contain media."})
            if media_alt:
                raise forms.ValidationError({"media_alt": "Alt text is only used for image blocks."})

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        upload_media = self.cleaned_data.get("upload_media")
        upload_first_frame = self.cleaned_data.get("upload_first_frame")

        if upload_media:
            try:
                instance.media = upload_media_to_vk_cloud(upload_media)
            except Exception:
                raise forms.ValidationError("Failed to upload media to VK Cloud.")

        if upload_first_frame:
            try:
                instance.first_video_frame = upload_media_to_vk_cloud(upload_first_frame)
            except Exception:
                raise forms.ValidationError("Failed to upload media to VK Cloud.")

        for field_name in ("text", "media_alt", "caption"):
            value = self.cleaned_data.get(field_name)
            if isinstance(value, str):
                setattr(instance, field_name, value.strip())

        if commit:
            instance.save()

        return instance


class ContentBlockInline(admin.StackedInline):
    model = ArticlesContentBlock
    form = ContentBlockAdminForm
    extra = 1
    fields = (
        "type",
        "order",
        "text",
        "upload_media",
        "media",
        "media_alt",
        "caption",
        "upload_first_frame",
        "first_video_frame",
        "image_preview_inline",
    )
    readonly_fields = ("media", "first_video_frame", "image_preview_inline")

    def image_preview_inline(self, obj):
        if obj.first_video_frame:
            return mark_safe(f'<img src="{obj.first_video_frame}" style="max-height: 120px;"/>')
        if obj.media and any(obj.media.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]):
            return mark_safe(f'<img src="{obj.media}" style="max-height: 120px;"/>')
        return "No preview"

    image_preview_inline.short_description = "Preview"


@admin.register(Articles)
class ArticlesAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "is_published", "created_at", "updated_at")
    list_editable = ("is_published",)
    list_filter = ("is_published", "created_at", "updated_at")
    search_fields = ("title", "slug", "seo_title", "seo_description", "excerpt")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ContentBlockInline]
    form = ArticlesAdminForm
    save_on_top = True
    readonly_fields = (
        "preview_image",
        "image_preview_box",
        "article_public_url",
        "seo_snippet_preview",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Content",
            {
                "fields": ("title", "slug", "excerpt", "is_published"),
            },
        ),
        (
            "Preview",
            {
                "fields": (
                    "upload_image",
                    "preview_image_alt",
                    "image_preview_box",
                    "preview_image",
                    "article_public_url",
                ),
            },
        ),
        (
            "SEO",
            {
                "fields": (
                    "seo_title",
                    "seo_description",
                    "seo_keywords",
                    "seo_robots",
                    "canonical_url",
                    "seo_snippet_preview",
                ),
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

    def image_preview_box(self, obj):
        if obj.preview_image:
            return mark_safe(f'<img src="{obj.preview_image}" style="max-height: 200px;"/>')
        return "Image not uploaded"

    image_preview_box.short_description = "Current preview image"

    def article_public_url(self, obj):
        if not obj.pk:
            return "Save article to generate URL."
        url = _build_public_article_url(obj.slug)
        return format_html('<a href="{0}" target="_blank" rel="noopener noreferrer">{0}</a>', url)

    article_public_url.short_description = "Public URL"

    def seo_snippet_preview(self, obj):
        title = (obj.seo_title or obj.title or "").strip() or "SEO title"
        description = (obj.seo_description or obj.excerpt or obj.title or "").strip() or "SEO description"
        if obj.slug:
            url = _build_public_article_url(obj.slug)
        else:
            url = "/articles/<slug>/"
        return format_html(
            '<div style="max-width: 680px;">'
            '<div style="color:#1a0dab;font-size:20px;line-height:1.3;">{}</div>'
            '<div style="color:#006621;font-size:14px;margin:4px 0;">{}</div>'
            '<div style="color:#545454;font-size:14px;">{}</div>'
            "</div>",
            title,
            url,
            description,
        )

    seo_snippet_preview.short_description = "SEO snippet preview"
