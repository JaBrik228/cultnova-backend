from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

from django.conf import settings
from django.template.loader import render_to_string

from core.services.build_item_html import get_generated_pages_root
from core.services.sitemap import SITEMAP_FILENAME

logger = logging.getLogger(__name__)

SITEMAP_PAGE_PATH = "/sitemap/"
SITEMAP_PAGE_OUTPUT_PATH = ("sitemap", "index.html")
SITEMAP_XML_NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

LEGACY_CREATE_PATHS = frozenset(
    {
        "/museum/",
        "/musium/",
        "/stand/",
        "/design/",
        "/content/",
        "/app/",
        "/service/",
        "/environment/",
    }
)
LEGACY_INFO_PATHS = frozenset({"/about/", "/faq/", "/contact/"})
LEGACY_LEGAL_PATHS = frozenset(
    {
        "/terms/",
        "/use-cookies/",
        "/privacy-policy/",
        "/personal-data/",
        "/personal-data-policy/",
    }
)


@dataclass(frozen=True)
class HtmlSitemapLink:
    path: str
    url: str
    title: str
    lastmod: str | None = None
    priority: str | None = None


@dataclass(frozen=True)
class HtmlSitemapSection:
    key: str
    title: str
    links: tuple[HtmlSitemapLink, ...]


@dataclass(frozen=True)
class HtmlSitemapBuildResult:
    output_path: Path
    section_count: int
    url_count: int


@dataclass(frozen=True)
class _SectionDefinition:
    key: str
    title: str


SECTION_DEFINITIONS = (
    _SectionDefinition(key="main", title="Основные страницы"),
    _SectionDefinition(key="articles", title="Статьи"),
    _SectionDefinition(key="projects", title="Проекты"),
    _SectionDefinition(key="create", title="Мы создаём"),
    _SectionDefinition(key="info", title="Информация"),
    _SectionDefinition(key="legal", title="Юридическая информация"),
)


class SitemapXmlMissingError(FileNotFoundError):
    pass


class _PageMetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._inside_title = False
        self._title_parts: list[str] = []
        self.robots_content = ""

    @property
    def title(self) -> str:
        return "".join(self._title_parts).strip()

    def handle_starttag(self, tag, attrs):
        tag_name = tag.lower()
        if tag_name == "title":
            self._inside_title = True
            return

        if tag_name != "meta":
            return

        normalized_attrs = {}
        for key, value in attrs:
            if key:
                normalized_attrs[key.lower()] = value or ""

        if normalized_attrs.get("name", "").strip().lower() != "robots":
            return

        self.robots_content = normalized_attrs.get("content", "").strip()

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._inside_title = False

    def handle_data(self, data):
        if self._inside_title:
            self._title_parts.append(data)


def build_html_sitemap() -> tuple[HtmlSitemapSection, ...]:
    generated_root = get_generated_pages_root()
    xml_path = generated_root / SITEMAP_FILENAME
    if not xml_path.exists():
        raise SitemapXmlMissingError(f"Sitemap XML not found at {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    buckets = {definition.key: [] for definition in SECTION_DEFINITIONS}
    for link in _iter_sitemap_links(root, generated_root):
        buckets[_resolve_section_key(link.path)].append(link)

    sections = []
    for definition in SECTION_DEFINITIONS:
        links = tuple(buckets[definition.key])
        if links:
            sections.append(
                HtmlSitemapSection(
                    key=definition.key,
                    title=definition.title,
                    links=links,
                )
            )

    return tuple(sections)


def build_static_html_sitemap_page() -> HtmlSitemapBuildResult:
    generated_root = get_generated_pages_root()
    sections = build_html_sitemap()
    canonical_url = _build_public_url(SITEMAP_PAGE_PATH)
    html = render_to_string(
        "sitemap_page.html",
        {
            "sections": sections,
            "canonical_url": canonical_url,
        },
    )

    output_path = generated_root.joinpath(*SITEMAP_PAGE_OUTPUT_PATH)
    _write_text_atomically(output_path, html)

    return HtmlSitemapBuildResult(
        output_path=output_path,
        section_count=len(sections),
        url_count=sum(len(section.links) for section in sections),
    )


def _iter_sitemap_links(root: ET.Element, generated_root: Path):
    for url_node in root.findall("sm:url", SITEMAP_XML_NAMESPACE):
        loc = (url_node.findtext("sm:loc", default="", namespaces=SITEMAP_XML_NAMESPACE) or "").strip()
        if not loc:
            continue

        public_path = _extract_public_path(loc)
        if not public_path or public_path == SITEMAP_PAGE_PATH:
            continue

        page_meta = _read_page_meta(generated_root, public_path)
        if page_meta and _is_noindex(page_meta.robots_content):
            continue

        title = "ГЛАВНАЯ СТРАНИЦА" if public_path == "/" else _normalize_title(page_meta.title if page_meta else "")
        yield HtmlSitemapLink(
            path=public_path,
            url=loc,
            title=title or _fallback_title_from_path(public_path),
            lastmod=(url_node.findtext("sm:lastmod", default="", namespaces=SITEMAP_XML_NAMESPACE) or "").strip() or None,
            priority=(url_node.findtext("sm:priority", default="", namespaces=SITEMAP_XML_NAMESPACE) or "").strip() or None,
        )


def _read_page_meta(generated_root: Path, public_path: str) -> _PageMetaParser | None:
    html_path = _public_path_to_html_path(generated_root, public_path)
    if not html_path.exists():
        logger.warning("HTML sitemap source is missing for path %s: %s", public_path, html_path)
        return None

    parser = _PageMetaParser()
    parser.feed(html_path.read_text(encoding="utf-8", errors="ignore"))
    return parser


def _extract_public_path(loc: str) -> str:
    parsed = urlsplit(loc)
    path = (parsed.path or "/").strip() or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if path != "/" and not path.endswith("/"):
        path = f"{path}/"
    return path


def _public_path_to_html_path(generated_root: Path, public_path: str) -> Path:
    if public_path == "/":
        return generated_root / "index.html"

    return generated_root.joinpath(*public_path.strip("/").split("/"), "index.html")


def _normalize_title(title: str) -> str:
    normalized = title.strip()
    if normalized.endswith("| Cultnova"):
        normalized = normalized[: -len("| Cultnova")].strip()
    return normalized


def _fallback_title_from_path(public_path: str) -> str:
    if public_path == "/":
        return "ГЛАВНАЯ СТРАНИЦА"

    return public_path.strip("/").split("/")[-1]


def _resolve_section_key(public_path: str) -> str:
    if public_path == "/":
        return "main"

    if _is_article_detail_path(public_path):
        return "articles"

    if _is_project_detail_path(public_path):
        return "projects"

    if public_path.startswith("/create/") or public_path in LEGACY_CREATE_PATHS:
        return "create"

    if public_path.startswith("/info/") or public_path in LEGACY_INFO_PATHS:
        return "info"

    if public_path.startswith("/legal/") or public_path in LEGACY_LEGAL_PATHS:
        return "legal"

    return "main"


def _is_article_detail_path(public_path: str) -> bool:
    return public_path.count("/") == 3 and public_path.startswith("/articles/")


def _is_project_detail_path(public_path: str) -> bool:
    return public_path.count("/") == 3 and public_path.startswith("/projects/")


def _is_noindex(robots_content: str) -> bool:
    normalized = robots_content.lower()
    return "noindex" in normalized


def _build_public_url(public_path: str) -> str:
    base = (settings.SITE_PUBLIC_BASE_URL or "").rstrip("/")
    if not base:
        return public_path
    return f"{base}{public_path}"


def _write_text_atomically(target_path: Path, content: str):
    target_path.parent.mkdir(parents=True, exist_ok=True)

    with NamedTemporaryFile("w", encoding="utf-8", dir=target_path.parent, delete=False) as temp_file:
        temp_file.write(content)
        temp_path = Path(temp_file.name)

    temp_path.replace(target_path)
    os.chmod(target_path, 0o644)
