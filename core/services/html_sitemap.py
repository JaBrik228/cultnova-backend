from __future__ import annotations

import logging
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from core.services.build_item_html import get_generated_pages_root
from core.services.sitemap import SITEMAP_FILENAME

logger = logging.getLogger(__name__)

SITEMAP_PAGE_PATH = "/sitemap/"
SITEMAP_XML_NAMESPACE = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


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
class _SectionRule:
    key: str
    title: str
    prefixes: tuple[str, ...]
    legacy_paths: frozenset[str] = frozenset()


SECTION_RULES = (
    _SectionRule(
        key="main",
        title="Основные страницы",
        prefixes=("/",),
    ),
    _SectionRule(
        key="create",
        title="Мы создаём",
        prefixes=("/create/",),
        legacy_paths=frozenset(
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
        ),
    ),
    _SectionRule(
        key="info",
        title="Информация",
        prefixes=("/info/",),
        legacy_paths=frozenset(
            {
                "/about/",
                "/faq/",
                "/contact/",
            }
        ),
    ),
    _SectionRule(
        key="legal",
        title="Юридическая информация",
        prefixes=("/legal/",),
        legacy_paths=frozenset(
            {
                "/terms/",
                "/use-cookies/",
                "/privacy-policy/",
                "/personal-data/",
                "/personal-data-policy/",
            }
        ),
    ),
    _SectionRule(
        key="projects",
        title="Проекты",
        prefixes=("/projects/",),
    ),
    _SectionRule(
        key="blog",
        title="Блог",
        prefixes=("/articles/", "/blog/"),
    ),
)


class SitemapXmlMissingError(FileNotFoundError):
    pass


class _TitleParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._inside_title = False
        self._parts: list[str] = []

    @property
    def title(self) -> str:
        return "".join(self._parts).strip()

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "title":
            self._inside_title = True

    def handle_endtag(self, tag):
        if tag.lower() == "title":
            self._inside_title = False

    def handle_data(self, data):
        if self._inside_title:
            self._parts.append(data)


def build_html_sitemap() -> tuple[HtmlSitemapSection, ...]:
    generated_root = get_generated_pages_root()
    xml_path = generated_root / SITEMAP_FILENAME
    if not xml_path.exists():
        raise SitemapXmlMissingError(f"Sitemap XML not found at {xml_path}")

    tree = ET.parse(xml_path)
    root = tree.getroot()

    section_buckets = {rule.key: [] for rule in SECTION_RULES}
    for link in _iter_sitemap_links(root, generated_root):
        section_buckets[_resolve_section_key(link.path)].append(link)

    sections = []
    for rule in SECTION_RULES:
        links = tuple(sorted(section_buckets[rule.key], key=_link_sort_key))
        if links:
            sections.append(HtmlSitemapSection(key=rule.key, title=rule.title, links=links))

    return tuple(sections)


def _iter_sitemap_links(root: ET.Element, generated_root: Path):
    for url_node in root.findall("sm:url", SITEMAP_XML_NAMESPACE):
        loc = (url_node.findtext("sm:loc", default="", namespaces=SITEMAP_XML_NAMESPACE) or "").strip()
        if not loc:
            continue

        public_path = _extract_public_path(loc)
        if not public_path or public_path == SITEMAP_PAGE_PATH:
            continue

        title = "ГЛАВНАЯ СТРАНИЦА" if public_path == "/" else _read_title_for_path(generated_root, public_path)
        yield HtmlSitemapLink(
            path=public_path,
            url=loc,
            title=title or _fallback_title_from_path(public_path),
            lastmod=(url_node.findtext("sm:lastmod", default="", namespaces=SITEMAP_XML_NAMESPACE) or "").strip() or None,
            priority=(url_node.findtext("sm:priority", default="", namespaces=SITEMAP_XML_NAMESPACE) or "").strip() or None,
        )


def _extract_public_path(loc: str) -> str:
    parsed = urlsplit(loc)
    path = (parsed.path or "/").strip() or "/"
    if not path.startswith("/"):
        path = f"/{path}"
    if path != "/" and not path.endswith("/"):
        path = f"{path}/"
    return path


def _read_title_for_path(generated_root: Path, public_path: str) -> str:
    html_path = _public_path_to_html_path(generated_root, public_path)
    if not html_path.exists():
        logger.warning("HTML sitemap title source is missing for path %s: %s", public_path, html_path)
        return ""

    parser = _TitleParser()
    parser.feed(html_path.read_text(encoding="utf-8", errors="ignore"))
    return _normalize_title(parser.title)


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
        return "Главная страница"

    return public_path.strip("/").split("/")[-1]


def _resolve_section_key(public_path: str) -> str:
    if public_path == "/":
        return "main"

    for rule in SECTION_RULES[1:]:
        if public_path in rule.legacy_paths:
            return rule.key
        if any(public_path.startswith(prefix) for prefix in rule.prefixes):
            return rule.key

    return "main"


def _link_sort_key(item: HtmlSitemapLink):
    return (item.path != "/", item.title.casefold(), item.path)
