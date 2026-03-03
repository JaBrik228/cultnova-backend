from django import forms


class JoditWidget(forms.Textarea):
    template_name = "django/forms/widgets/textarea.html"

    class Media:
        css = {
            "all": (
                "vendor/jodit/es2021/jodit.min.css",
                "blog/admin/article_richtext.css",
            )
        }
        js = (
            "vendor/jodit/es2021/jodit.min.js",
            "blog/admin/article_richtext.js",
        )

    def __init__(self, attrs=None):
        merged_attrs = {
            "class": "vLargeTextField jodit-body-editor",
            "data-editor-role": "article-body-html",
        }
        if attrs:
            merged_attrs.update(attrs)
        super().__init__(attrs=merged_attrs)
