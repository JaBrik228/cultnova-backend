import os

from django.conf import settings
from django.template.loader import render_to_string

from blog.services.article_rendering import build_article_render_context
from core.models.base_item import BaseContentItem


def _build_article_path(base_gen_root: str, slug: str):
    article_dir = os.path.join(base_gen_root, "articles", str(slug))
    return article_dir, os.path.join(article_dir, "index.html")


def _remove_file_if_exists(file_path: str):
    if os.path.exists(file_path):
        os.remove(file_path)


def _remove_dir_if_empty(dir_path: str):
    if os.path.isdir(dir_path) and not os.listdir(dir_path):
        os.rmdir(dir_path)


def build_item_detail_static_html(instance: BaseContentItem, template_name: str, folder_name: str):
    """
    Generate static HTML and write it into the target directory.
    """
    base_gen_root = settings.GENERATED_HTML_PAGES_PATH

    if folder_name in {"article", "articles"}:
        context = build_article_render_context(instance)
        save_dir, file_path = _build_article_path(base_gen_root, instance.slug)
    else:
        context = {"item": instance}
        save_dir = os.path.join(base_gen_root, folder_name)
        file_path = os.path.join(save_dir, f"{instance.slug}.html")

    html_content = render_to_string(template_name, context)
    os.makedirs(save_dir, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as output:
        output.write(html_content)

    return file_path


def delete_item_detail_static_html(instance: BaseContentItem, folder_name: str, slug_override: str | None = None):
    """Delete previously generated static HTML."""
    base_gen_root = settings.GENERATED_HTML_PAGES_PATH

    if folder_name in {"article", "articles"}:
        active_slug = slug_override or instance.slug
        article_dir, file_path = _build_article_path(base_gen_root, active_slug)

        legacy_slug_file = os.path.join(base_gen_root, "articles", f"{active_slug}.html")
        legacy_id_dir = os.path.join(base_gen_root, "article", str(instance.id))
        legacy_id_file = os.path.join(legacy_id_dir, "index.html")

        _remove_file_if_exists(file_path)
        _remove_file_if_exists(legacy_slug_file)
        _remove_file_if_exists(legacy_id_file)

        _remove_dir_if_empty(article_dir)
        _remove_dir_if_empty(legacy_id_dir)
        _remove_dir_if_empty(os.path.join(base_gen_root, "article"))
        _remove_dir_if_empty(os.path.join(base_gen_root, "articles"))
    else:
        file_path = os.path.join(base_gen_root, folder_name, f"{instance.slug}.html")
        _remove_file_if_exists(file_path)
