import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from blog.models import Articles
from core.services.html_sitemap import SitemapXmlMissingError, build_html_sitemap
from core.services.sitemap import build_sitemap
from projects.models import ProjectCategories, Projects


class SitemapServiceTests(TestCase):
    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_build_sitemap_merges_static_and_cms_pages_and_skips_noindex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                self._write_html(
                    root / "index.html",
                    '<html><head><meta name="robots" content="index,follow"></head><body>Home</body></html>',
                )

                about_path = root / "about" / "index.html"
                self._write_html(
                    about_path,
                    '<html><head><meta name="robots" content="index, follow"></head><body>About</body></html>',
                )
                static_timestamp = datetime(2026, 1, 27, 12, 30, 15, tzinfo=dt_timezone.utc).timestamp()
                os.utime(about_path, (static_timestamp, static_timestamp))

                self._write_html(
                    root / "hidden" / "index.html",
                    '<html><head><meta name="robots" content="noindex, nofollow"></head><body>Hidden</body></html>',
                )
                self._write_html(root / "404" / "index.html", "<html><body>Missing</body></html>")
                self._write_html(
                    root / "articles" / "stale-entry" / "index.html",
                    '<html><head><meta name="robots" content="index,follow"></head><body>Stale</body></html>',
                )

                category = ProjectCategories.objects.create(title="Museums", slug="museums")

                with self.captureOnCommitCallbacks(execute=True):
                    article = Articles.objects.create(
                        title="Live Article",
                        slug="live-article",
                        body_html="<p>Body</p>",
                        excerpt="Excerpt",
                        seo_title="SEO title",
                        seo_description="SEO description",
                        is_published=True,
                    )
                    project = Projects.objects.create(
                        title="Live Project",
                        slug="live-project",
                        category=category,
                        customer_name="Client",
                        year=2026,
                        type="Installation",
                        body_html="<p>Body</p>",
                        excerpt="Excerpt",
                        seo_title="SEO title",
                        seo_description="SEO description",
                        is_published=True,
                    )

                article_updated_at = timezone.make_aware(datetime(2026, 2, 5, 8, 15, 30))
                project_updated_at = timezone.make_aware(datetime(2026, 2, 6, 9, 45, 0))
                Articles.objects.filter(pk=article.pk).update(updated_at=article_updated_at)
                Projects.objects.filter(pk=project.pk).update(updated_at=project_updated_at)

                result = build_sitemap()

                self.assertEqual(result.output_path, root / "sitemap.xml")
                self.assertEqual(result.url_count, 4)
                self.assertEqual(result.skipped_noindex_count, 1)

                sitemap = result.output_path.read_text(encoding="utf-8")

                self.assertIn("<loc>https://example.com/</loc>", sitemap)
                self.assertIn("<loc>https://example.com/about/</loc>", sitemap)
                self.assertIn("<loc>https://example.com/articles/live-article/</loc>", sitemap)
                self.assertIn("<loc>https://example.com/projects/live-project/</loc>", sitemap)
                self.assertNotIn("https://example.com/hidden/", sitemap)
                self.assertNotIn("https://example.com/404/", sitemap)
                self.assertNotIn("https://example.com/articles/stale-entry/", sitemap)

                self.assertIn("<priority>1.0</priority>", sitemap)
                self.assertIn("<priority>0.8</priority>", sitemap)
                self.assertIn("<priority>0.7</priority>", sitemap)
                self.assertIn(
                    timezone.localtime(datetime.fromtimestamp(static_timestamp, tz=dt_timezone.utc)).isoformat(
                        timespec="seconds"
                    ),
                    sitemap,
                )
                self.assertIn(article_updated_at.isoformat(timespec="seconds"), sitemap)
                self.assertIn(project_updated_at.isoformat(timespec="seconds"), sitemap)

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_rebuild_sitemap_command_reports_output_and_counts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                self._write_html(
                    root / "index.html",
                    '<html><head><meta name="robots" content="index,follow"></head><body>Home</body></html>',
                )

                stdout = StringIO()
                call_command("rebuild_sitemap", stdout=stdout)
                output = stdout.getvalue()

                self.assertIn("Output:", output)
                self.assertIn("URLs: 1", output)
                self.assertIn("skipped noindex: 0", output)
                self.assertTrue((root / "sitemap.xml").exists())

    def _write_html(self, target_path: Path, content: str):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")


class HtmlSitemapServiceTests(TestCase):
    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_build_html_sitemap_reads_titles_and_groups_new_and_legacy_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                self._write_sitemap_xml(
                    root / "sitemap.xml",
                    [
                        "https://example.com/",
                        "https://example.com/create/museum-spaces/",
                        "https://example.com/museum/",
                        "https://example.com/info/about-company/",
                        "https://example.com/about/",
                        "https://example.com/legal/privacy-policy/",
                        "https://example.com/privacy-policy/",
                        "https://example.com/projects/live-project/",
                        "https://example.com/articles/live-article/",
                        "https://example.com/misc-page/",
                        "https://example.com/sitemap/",
                    ],
                )
                self._write_titled_page(root / "index.html", "Любой title | Cultnova")
                self._write_titled_page(root / "create" / "museum-spaces" / "index.html", "Создание музеев | Cultnova")
                self._write_titled_page(root / "museum" / "index.html", "Музеи и пространства | Cultnova")
                self._write_titled_page(root / "info" / "about-company" / "index.html", "О компании | Cultnova")
                self._write_titled_page(root / "about" / "index.html", "О компании старая | Cultnova")
                self._write_titled_page(root / "legal" / "privacy-policy" / "index.html", "Политика конфиденциальности")
                self._write_titled_page(root / "privacy-policy" / "index.html", "Старая политика | Cultnova")
                self._write_titled_page(root / "projects" / "live-project" / "index.html", "Проект Alpha | Cultnova")
                self._write_titled_page(root / "articles" / "live-article" / "index.html", "Статья Beta | Cultnova")
                self._write_html(root / "misc-page" / "index.html", "<html><head></head><body>Misc</body></html>")

                sections = build_html_sitemap()

                section_map = {section.key: section for section in sections}
                self.assertEqual(section_map["create"].title, "Мы создаём")
                self.assertEqual(
                    [link.title for link in section_map["create"].links],
                    ["Музеи и пространства", "Создание музеев"],
                )
                self.assertEqual([link.path for link in section_map["info"].links], ["/info/about-company/", "/about/"])
                self.assertEqual([link.path for link in section_map["legal"].links], ["/legal/privacy-policy/", "/privacy-policy/"])
                self.assertEqual([link.title for link in section_map["projects"].links], ["Проект Alpha"])
                self.assertEqual([link.title for link in section_map["blog"].links], ["Статья Beta"])
                self.assertEqual([link.path for link in section_map["main"].links], ["/", "/misc-page/"])
                self.assertEqual(section_map["main"].links[0].title, "ГЛАВНАЯ СТРАНИЦА")
                self.assertEqual(section_map["main"].links[1].title, "misc-page")

                all_paths = [link.path for section in sections for link in section.links]
                self.assertNotIn("/sitemap/", all_paths)

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_build_html_sitemap_raises_when_xml_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                with self.assertRaises(SitemapXmlMissingError):
                    build_html_sitemap()

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_build_html_sitemap_bubbles_up_invalid_xml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                (root / "sitemap.xml").write_text("<urlset>", encoding="utf-8")

                with self.assertRaises(ET.ParseError):
                    build_html_sitemap()

    def _write_sitemap_xml(self, target_path: Path, locations: list[str]):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for loc in locations:
            lines.extend(["  <url>", f"    <loc>{loc}</loc>", "  </url>"])
        lines.append("</urlset>")
        target_path.write_text("\n".join(lines), encoding="utf-8")

    def _write_titled_page(self, target_path: Path, title: str):
        self._write_html(target_path, f"<html><head><title>{title}</title></head><body>Page</body></html>")

    def _write_html(self, target_path: Path, content: str):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")


class SitemapPageViewTests(TestCase):
    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_sitemap_page_renders_sections_from_sitemap_xml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                self._write_sitemap_xml(
                    root / "sitemap.xml",
                    [
                        "https://example.com/",
                        "https://example.com/create/museum-spaces/",
                        "https://example.com/projects/live-project/",
                        "https://example.com/sitemap/",
                    ],
                )
                self._write_titled_page(root / "index.html", "Любой title | Cultnova")
                self._write_titled_page(root / "create" / "museum-spaces" / "index.html", "Создание музеев | Cultnova")
                self._write_titled_page(root / "projects" / "live-project" / "index.html", "Проект Alpha | Cultnova")

                response = self.client.get(reverse("core:sitemap_page"))

                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "Карта сайта")
                self.assertContains(response, "ГЛАВНАЯ СТРАНИЦА")
                self.assertContains(response, "Мы создаём")
                self.assertContains(response, "Создание музеев")
                self.assertContains(response, "Проект Alpha")
                self.assertNotContains(response, 'href="/sitemap/" class="sitemap__link"')

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_sitemap_page_returns_404_when_sitemap_xml_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                response = self.client.get(reverse("core:sitemap_page"))
                self.assertEqual(response.status_code, 404)

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_sitemap_page_returns_500_for_invalid_xml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                (root / "sitemap.xml").write_text("<urlset>", encoding="utf-8")

                response = self.client.get(reverse("core:sitemap_page"))
                self.assertEqual(response.status_code, 500)

    def _write_sitemap_xml(self, target_path: Path, locations: list[str]):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]
        for loc in locations:
            lines.extend(["  <url>", f"    <loc>{loc}</loc>", "  </url>"])
        lines.append("</urlset>")
        target_path.write_text("\n".join(lines), encoding="utf-8")

    def _write_titled_page(self, target_path: Path, title: str):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(
            f"<html><head><title>{title}</title></head><body>Page</body></html>",
            encoding="utf-8",
        )
