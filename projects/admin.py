import mimetypes
import re

from django import forms
from django.conf import settings
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, reverse
from django.utils.html import format_html, mark_safe

from blog.services.rich_text import (
    build_inline_image_html,
    looks_like_html_fragment,
    normalize_legacy_text_to_html,
    sanitize_rich_body_html,
)
from blog.widgets import JoditWidget
from core.services.vk_cloud_storage import upload_media_to_vk_cloud
from projects.services.project_listing import build_public_project_category_url
from projects.services.project_rendering import build_public_project_url

from .models import ProjectCategories, Projects, ProjectsContentBlock


def _trim(value):
    if isinstance(value, str):
        return value.strip()
    return value


class ProjectCategoriesAdminForm(forms.ModelForm):
    class Meta:
        model = ProjectCategories
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        for field_name in (
            "page_h1",
            "seo_title",
            "seo_description",
            "seo_keywords",
            "seo_robots",
            "canonical_url",
        ):
            value = cleaned_data.get(field_name)
            if isinstance(value, str):
                cleaned_data[field_name] = value.strip()

        if not cleaned_data.get("seo_robots"):
            cleaned_data["seo_robots"] = "index,follow"

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)

        for field_name in (
            "page_h1",
            "seo_title",
            "seo_description",
            "seo_keywords",
            "seo_robots",
            "canonical_url",
        ):
            value = self.cleaned_data.get(field_name)
            if isinstance(value, str):
                setattr(instance, field_name, value.strip())

        if not instance.seo_robots:
            instance.seo_robots = "index,follow"

        if commit:
            instance.save()

        return instance


class ProjectsAdminForm(forms.ModelForm):
    upload_image = forms.ImageField(required=False, label="Upload preview image")

    class Meta:
        model = Projects
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "body_html" in self.fields:
            self.fields["body_html"].widget = JoditWidget(
                attrs={
                    "data-inline-image-upload-url": getattr(self, "inline_image_upload_url", ""),
                }
            )

    def clean(self):
        cleaned_data = super().clean()

        body_html = cleaned_data.get("body_html") or ""
        seo_title = _trim(cleaned_data.get("seo_title")) or ""
        seo_description = _trim(cleaned_data.get("seo_description")) or ""
        preview_image_alt = _trim(cleaned_data.get("preview_image_alt")) or ""
        upload_image = cleaned_data.get("upload_image")

        if not body_html.strip():
            self.add_error("body_html", "Project body is required.")
        else:
            body_source = body_html if looks_like_html_fragment(body_html) else normalize_legacy_text_to_html(body_html)
            if re.search(r"<\s*h1(?:\s|>)", body_source, re.IGNORECASE):
                self.add_error("body_html", "H1 is not allowed inside project body.")
            else:
                cleaned_data["body_html"] = sanitize_rich_body_html(body_html)

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
            except Exception as exc:
                raise forms.ValidationError("Failed to upload media to VK Cloud.") from exc

        for field_name in (
            "body_html",
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
        model = ProjectsContentBlock
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        block_type = cleaned_data.get("type")
        media_alt = _trim(cleaned_data.get("media_alt")) or ""

        media_file = cleaned_data.get("upload_media")
        current_media_url = self.instance.media if self.instance else None

        frame_file = cleaned_data.get("upload_first_frame")
        current_frame_url = self.instance.first_video_frame if self.instance else None

        if block_type not in {ProjectsContentBlock.IMAGE, ProjectsContentBlock.VIDEO}:
            raise forms.ValidationError({"type": "Only image and video gallery blocks are allowed."})

        if block_type == ProjectsContentBlock.IMAGE:
            if not media_file and not current_media_url:
                raise forms.ValidationError({"upload_media": "Image is required for image block."})
            if not media_alt:
                raise forms.ValidationError({"media_alt": "Alt text is required for image block."})

        elif block_type == ProjectsContentBlock.VIDEO:
            if not media_file and not current_media_url:
                raise forms.ValidationError({"upload_media": "Video is required for video block."})
            if not frame_file and not current_frame_url:
                raise forms.ValidationError({"upload_first_frame": "First frame is required for video block."})

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        upload_media = self.cleaned_data.get("upload_media")
        upload_first_frame = self.cleaned_data.get("upload_first_frame")
        block_type = self.cleaned_data.get("type")

        if upload_media:
            try:
                instance.media = upload_media_to_vk_cloud(upload_media)
            except Exception as exc:
                raise forms.ValidationError("Failed to upload media to VK Cloud.") from exc

        if upload_first_frame:
            try:
                instance.first_video_frame = upload_media_to_vk_cloud(upload_first_frame)
            except Exception as exc:
                raise forms.ValidationError("Failed to upload media to VK Cloud.") from exc

        instance.text = ""

        if block_type == ProjectsContentBlock.IMAGE:
            instance.first_video_frame = None
        if block_type == ProjectsContentBlock.VIDEO:
            instance.media_alt = ""

        for field_name in ("media_alt", "caption"):
            value = self.cleaned_data.get(field_name)
            if isinstance(value, str):
                setattr(instance, field_name, value.strip())

        if commit:
            instance.save()

        return instance


class ContentBlockInline(admin.StackedInline):
    model = ProjectsContentBlock
    form = ContentBlockAdminForm
    extra = 1
    verbose_name_plural = "Project media"
    fields = (
        "type",
        "order",
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


@admin.register(ProjectCategories)
class ProjectCategoriesAdmin(admin.ModelAdmin):
    form = ProjectCategoriesAdminForm
    save_on_top = True
    list_display = ("title", "slug", "created_at")
    search_fields = ("title", "slug", "seo_title", "seo_description")
    prepopulated_fields = {"slug": ("title",)}
    readonly_fields = ("category_public_url", "seo_snippet_preview", "created_at")
    fieldsets = (
        (
            "Content",
            {
                "fields": ("title", "slug"),
            },
        ),
        (
            "SEO",
            {
                "fields": (
                    "page_h1",
                    "seo_title",
                    "seo_description",
                    "seo_keywords",
                    "seo_robots",
                    "canonical_url",
                    "category_public_url",
                    "seo_snippet_preview",
                ),
            },
        ),
        (
            "System",
            {
                "fields": ("created_at",),
                "classes": ("collapse",),
            },
        ),
    )

    def category_public_url(self, obj):
        if not obj.pk:
            return "Save category to generate URL."
        url = build_public_project_category_url(obj.slug)
        return format_html('<a href="{0}" target="_blank" rel="noopener noreferrer">{0}</a>', url)

    category_public_url.short_description = "Public URL"

    def seo_snippet_preview(self, obj):
        category_title = (getattr(obj, "title", "") or "").strip()
        title = ((obj.seo_title or "").strip() or f"{category_title} | Проекты" or "SEO title")
        description = (
            (obj.seo_description or "").strip()
            or (f"Проекты Cultnova в категории «{category_title}»." if category_title else "")
            or "SEO description"
        )

        if obj.pk and obj.slug:
            url = (obj.canonical_url or "").strip() or build_public_project_category_url(obj.slug)
        else:
            base = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
            url = f"{base}/projects/category/<slug>/" if base else "/projects/category/<slug>/"

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


@admin.register(Projects)
class ProjectsAdmin(admin.ModelAdmin):
    list_display = ("title", "slug", "category", "is_published", "created_at", "updated_at")
    list_editable = ("is_published",)
    list_filter = ("category", "is_published", "created_at", "updated_at")
    search_fields = ("title", "slug", "customer_name", "seo_title", "seo_description", "excerpt")
    prepopulated_fields = {"slug": ("title",)}
    inlines = [ContentBlockInline]
    form = ProjectsAdminForm
    save_on_top = True
    readonly_fields = (
        "preview_image",
        "image_preview_box",
        "project_public_url",
        "seo_snippet_preview",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        (
            "Content",
            {
                "fields": (
                    "title",
                    "slug",
                    "category",
                    "customer_name",
                    "year",
                    "type",
                    "body_html",
                    "excerpt",
                    "is_published",
                ),
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
                    "project_public_url",
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

    def get_form(self, request, obj=None, change=False, **kwargs):
        form = super().get_form(request, obj, change, **kwargs)
        form.inline_image_upload_url = reverse("admin:projects_projects_inline_image_upload")
        return form

    def get_urls(self):
        custom_urls = [
            path(
                "inline-image-upload/",
                self.admin_site.admin_view(self.inline_image_upload_view),
                name="projects_projects_inline_image_upload",
            ),
        ]
        return custom_urls + super().get_urls()

    def inline_image_upload_view(self, request):
        if request.method != "POST":
            return JsonResponse({"success": False, "error": "POST method is required."}, status=405)

        uploaded_file = request.FILES.get("file")
        alt = (request.POST.get("alt") or "").strip()
        caption = (request.POST.get("caption") or "").strip()

        if not uploaded_file:
            return JsonResponse({"success": False, "error": "Image file is required."}, status=400)

        if not alt:
            return JsonResponse({"success": False, "error": "Alt text is required."}, status=400)

        if uploaded_file.size > 10 * 1024 * 1024:
            return JsonResponse({"success": False, "error": "Image size must not exceed 10 MB."}, status=400)

        allowed_content_types = {"image/jpeg", "image/png", "image/webp"}
        guessed_content_type, _ = mimetypes.guess_type(uploaded_file.name)
        content_type = (uploaded_file.content_type or guessed_content_type or "").lower()

        if content_type not in allowed_content_types:
            return JsonResponse(
                {"success": False, "error": "Only JPG, PNG and WEBP images are supported."},
                status=400,
            )

        try:
            file_url = upload_media_to_vk_cloud(uploaded_file, folder="projects/inline")
        except Exception:
            return JsonResponse({"success": False, "error": "Failed to upload image to VK Cloud."}, status=500)

        html = build_inline_image_html(file_url, alt, caption)
        return JsonResponse({"success": True, "url": file_url, "html": html})

    def image_preview_box(self, obj):
        if obj.preview_image:
            return mark_safe(f'<img src="{obj.preview_image}" style="max-height: 200px;"/>')
        return "Image not uploaded"

    image_preview_box.short_description = "Current preview image"

    def project_public_url(self, obj):
        if not obj.pk:
            return "Save project to generate URL."
        url = build_public_project_url(obj.slug)
        return format_html('<a href="{0}" target="_blank" rel="noopener noreferrer">{0}</a>', url)

    project_public_url.short_description = "Public URL"

    def seo_snippet_preview(self, obj):
        title = (obj.seo_title or obj.title or "").strip() or "SEO title"
        description = (obj.seo_description or obj.excerpt or obj.title or "").strip() or "SEO description"
        if obj.slug:
            url = build_public_project_url(obj.slug)
        else:
            base = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
            url = f"{base}/projects/<slug>/" if base else "/projects/<slug>/"

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
