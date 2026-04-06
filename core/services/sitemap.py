from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from xml.sax.saxutils import escape

from django.conf import settings
from django.utils import timezone

from blog.models import Articles
from blog.services.article_rendering import build_public_article_path
from core.services.build_item_html import get_generated_pages_root
from projects.models import Projects
from projects.services.project_rendering import build_public_project_path

SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"
SITEMAP_FILENAME = "sitemap.xml"
CMS_DETAIL_FOLDERS = {"articles", "projects"}


@dataclass(frozen=True)
class SitemapEntry:
    public_path: str
    loc: str
    lastmod: str
    changefreq: str
    priority: str


@dataclass(frozen=True)
class SitemapBuildResult:
    output_path: Path
    url_count: int
    skipped_noindex_count: int


@dataclass(frozen=True)
class PublicSitemapsBuildResult:
    xml_result: SitemapBuildResult
    html_result: HtmlSitemapBuildResult


class _RobotsMetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.has_noindex = False

    def handle_starttag(self, tag, attrs):
        if self.has_noindex or tag.lower() != "meta":
            return

        normalized_attrs = {}
        for key, value in attrs:
            if key:
                normalized_attrs[key.lower()] = value or ""

        if normalized_attrs.get("name", "").strip().lower() != "robots":
            return

        if "noindex" in normalized_attrs.get("content", "").lower():
            self.has_noindex = True


def build_sitemap() -> SitemapBuildResult:
    generated_root = get_generated_pages_root()
    generated_root.mkdir(parents=True, exist_ok=True)

    cms_lastmods = _build_cms_lastmod_map()
    entries = []
    skipped_noindex_count = 0

    for html_path in _iter_public_html_files(generated_root):
        relative_path = html_path.relative_to(generated_root)

        if _is_noindex_page(html_path):
            skipped_noindex_count += 1
            continue

        public_path = _build_public_path(relative_path)
        if _is_cms_detail_page(relative_path):
            lastmod = cms_lastmods.get(public_path)
            if not lastmod:
                # Skip stale generated files for unpublished or deleted CMS items.
                continue

            entries.append(
                SitemapEntry(
                    public_path=public_path,
                    loc=_build_public_url(public_path),
                    lastmod=lastmod,
                    changefreq="weekly",
                    priority="0.7",
                )
            )
            continue

        entries.append(
            SitemapEntry(
                public_path=public_path,
                loc=_build_public_url(public_path),
                lastmod=_format_lastmod(_path_mtime(html_path)),
                changefreq="weekly",
                priority=_build_priority(public_path),
            )
        )

    entries.sort(key=lambda entry: (entry.public_path != "/", entry.public_path))

    output_path = generated_root / SITEMAP_FILENAME
    _write_text_atomically(output_path, _render_sitemap(entries))

    return SitemapBuildResult(
        output_path=output_path,
        url_count=len(entries),
        skipped_noindex_count=skipped_noindex_count,
    )


def build_public_sitemaps() -> PublicSitemapsBuildResult:
    from core.services.html_sitemap import build_static_html_sitemap_page

    xml_result = build_sitemap()
    html_result = build_static_html_sitemap_page()
    return PublicSitemapsBuildResult(
        xml_result=xml_result,
        html_result=html_result,
    )


def _iter_public_html_files(generated_root: Path):
    for html_path in generated_root.rglob("index.html"):
        if not html_path.is_file():
            continue

        relative_path = html_path.relative_to(generated_root)
        if relative_path.parts and relative_path.parts[0] == "404":
            continue

        yield html_path


def _is_noindex_page(html_path: Path) -> bool:
    parser = _RobotsMetaParser()
    parser.feed(html_path.read_text(encoding="utf-8", errors="ignore"))
    return parser.has_noindex


def _is_cms_detail_page(relative_path: Path) -> bool:
    parts = relative_path.parts
    if len(parts) != 3:
        return False
    return parts[0] in CMS_DETAIL_FOLDERS and parts[-1] == "index.html"


def _build_public_path(relative_path: Path) -> str:
    if relative_path.parts == ("index.html",):
        return "/"

    return "/" + "/".join(relative_path.parts[:-1]) + "/"


def _build_public_url(public_path: str) -> str:
    base = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        return public_path
    return f"{base}{public_path}"


def _build_priority(public_path: str) -> str:
    if public_path == "/":
        return "1.0"
    return "0.8"


def _build_cms_lastmod_map() -> dict[str, str]:
    lastmods = {}

    for article in Articles.objects.filter(is_published=True).only("slug", "created_at", "updated_at"):
        lastmods[build_public_article_path(article.slug)] = _format_lastmod(article.updated_at or article.created_at)

    for project in Projects.objects.filter(is_published=True).only("slug", "created_at", "updated_at"):
        lastmods[build_public_project_path(project.slug)] = _format_lastmod(project.updated_at or project.created_at)

    return lastmods


def _path_mtime(html_path: Path) -> datetime:
    return datetime.fromtimestamp(html_path.stat().st_mtime, tz=dt_timezone.utc)


def _format_lastmod(value: datetime) -> str:
    if timezone.is_naive(value):
        value = timezone.make_aware(value, dt_timezone.utc)
    return timezone.localtime(value).isoformat(timespec="seconds")


def _render_sitemap(entries: list[SitemapEntry]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<urlset xmlns="{SITEMAP_NAMESPACE}">',
    ]

    for entry in entries:
        lines.extend(
            [
                "  <url>",
                f"    <loc>{escape(entry.loc)}</loc>",
                f"    <lastmod>{escape(entry.lastmod)}</lastmod>",
                f"    <changefreq>{escape(entry.changefreq)}</changefreq>",
                f"    <priority>{escape(entry.priority)}</priority>",
                "  </url>",
            ]
        )

    lines.append("</urlset>")
    return "\n".join(lines) + "\n"


def _write_text_atomically(target_path: Path, content: str):
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile("w", encoding="utf-8", dir=target_path.parent, delete=False) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)

    temp_path.replace(target_path)
    os.chmod(target_path, 0o644)
