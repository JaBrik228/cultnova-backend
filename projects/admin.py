from django import forms
from django.contrib import admin
from django.utils.html import mark_safe
from .models import ProjectCategories, Projects, ProjectsContentBlock
from core.services.vk_cloud_storage import upload_media_to_vk_cloud


class ProjectsAdminFrom(forms.ModelForm):
    upload_image = forms.ImageField(
        required=False,
        label="Превью",
    )

    class Meta:
        model = Projects
        fields = '__all__'

    def save(self, commit=True):
        instance = super().save(commit=False)
        image_file = self.cleaned_data.get('upload_image')

        if image_file:
            try:
                file_url = upload_media_to_vk_cloud(image_file)
                instance.preview_image = file_url
            except Exception:
                raise forms.ValidationError("Не удалось загрузить медиа на Vk cloud")

        if commit:
            instance.save()

        return instance


class ContentBlockAdminForm(forms.ModelForm):
    upload_media = forms.FileField(
        required=False,
        label="Медиа"
    )
    upload_first_frame = forms.ImageField(
        required=False,
        label="Первый кадр видео"
    )

    def clean(self):
        cleaned_data = super().clean()
        block_type = cleaned_data.get('type')
        text = cleaned_data.get('text')

        media_file = cleaned_data.get('upload_media')
        current_media_url = self.instance.media if self.instance else None

        frame_file = cleaned_data.get('upload_first_frame')
        current_frame_url = self.instance.first_video_frame if self.instance else None

        if block_type == ProjectsContentBlock.IMAGE:
            if not media_file and not current_media_url:
                raise forms.ValidationError({'upload_media': "Нужно загрузить изображение"})
            if text:
                raise forms.ValidationError({'text': "Для изображения нельзя добавляет текст"})

        elif block_type == ProjectsContentBlock.VIDEO:
            if not media_file and not current_media_url:
                raise forms.ValidationError({'upload_media': "Нужно загрузить видео"})
            if not frame_file and not current_frame_url:
                raise forms.ValidationError({'upload_first_frame': "Нужен первый кадр видео"})
            if text:
                raise forms.ValidationError({'text': "Для видео нельзя добавлять текст"})

        elif block_type in [ProjectsContentBlock.TEXT, ProjectsContentBlock.HEADING]:
            if not text:
                raise forms.ValidationError({'text': "Введите текст"})
            if media_file or current_media_url:
                raise forms.ValidationError({'upload_media': "Для текстового блока нельзя загружать медиа"})

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        upload_media = self.cleaned_data.get('upload_media')
        upload_first_frame = self.cleaned_data.get('upload_first_frame')

        if upload_media:
            try:
                file_url = upload_media_to_vk_cloud(upload_media)
                instance.media = file_url
            except Exception:
                raise forms.ValidationError("Не удалось загрузить медиа на Vk cloud")

        if upload_first_frame:
            try:
                file_url = upload_media_to_vk_cloud(upload_first_frame)
                instance.first_video_frame = file_url
            except Exception:
                raise forms.ValidationError("Не удалось загрузить медиа на Vk cloud")

        if commit:
            instance.save()

        return instance


class ContentBlockInline(admin.TabularInline):
    model = ProjectsContentBlock
    form = ContentBlockAdminForm
    extra = 1

    fields = (
        'type', 'order', 'text', 'upload_media', 'media',
        'upload_first_frame', 'image_preview_inline', 'first_video_frame'
    )
    readonly_fields = ('media', 'first_video_frame', 'image_preview_inline')

    def image_preview_inline(self, obj):
        if obj.first_video_frame:
            return mark_safe(f'<img src="{obj.first_video_frame}" style="max-height: 50px;"/>')
        if obj.media and any(obj.media.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.webp']):
            return mark_safe(f'<img src="{obj.media}" style="max-height: 50px;"/>')
        return "Нет превью"

    image_preview_inline.short_description = "Превью"


@admin.register(ProjectCategories)
class ProjectCategoriesAdmin(admin.ModelAdmin):
    list_display = ('title', 'created_at')
    search_fields = ('title',)
    prepopulated_fields = {'slug': ('title',)}


@admin.register(Projects)
class ProjectsAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'created_at')
    search_fields = ('title',)
    prepopulated_fields = {'slug': ('title',)}
    form = ProjectsAdminFrom
    inlines = [ContentBlockInline]
    readonly_fields = ('preview_image', 'image_preview_box')
    fields = (
        'title', 'slug', 'category', 'customer_name', 'year', 'type',
        'upload_image',
        'image_preview_box',
        'preview_image'
    )

    def show_preview(self, obj):
        if obj.preview_image:
            return mark_safe(f'<img src="{obj.preview_image}" width="50" height="50" />')
        return "-"

    show_preview.short_description = "Превью"

    def image_preview_box(self, obj):
        if obj.preview_image:
            return mark_safe(f'<img src="{obj.preview_image}" style="max-height: 200px;"/>')
        return "Изображение не загружено"

    image_preview_box.short_description = "Текущее изображение"
