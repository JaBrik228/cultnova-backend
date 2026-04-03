import json
import os
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from blog.models import Articles
from core.services.frontend_partials_sync import sync_frontend_partials
from core.services.html_sitemap import (
    SitemapXmlMissingError,
    build_html_sitemap,
    build_static_html_sitemap_page,
)
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
    def test_rebuild_sitemap_command_reports_xml_and_html_outputs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                self._write_html(
                    root / "index.html",
                    '<html><head><meta name="robots" content="index,follow"></head><title>Главная</title><body>Home</body></html>',
                )

                stdout = StringIO()
                call_command("rebuild_sitemap", stdout=stdout)
                output = stdout.getvalue()

                self.assertIn("XML:", output)
                self.assertIn("HTML:", output)
                self.assertIn("URLs: 1", output)
                self.assertIn("sections: 1", output)
                self.assertIn("skipped noindex: 0", output)
                self.assertTrue((root / "sitemap.xml").exists())
                self.assertTrue((root / "sitemap" / "index.html").exists())

    def _write_html(self, target_path: Path, content: str):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")


class HtmlSitemapServiceTests(SimpleTestCase):
    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_build_html_sitemap_groups_detail_pages_and_skips_noindex(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                self._write_sitemap_xml(
                    root / "sitemap.xml",
                    [
                        "https://example.com/",
                        "https://example.com/blog/",
                        "https://example.com/articles/live-article/",
                        "https://example.com/projects/",
                        "https://example.com/projects/live-project/",
                        "https://example.com/create/museum-spaces/",
                        "https://example.com/museum/",
                        "https://example.com/info/about-company/",
                        "https://example.com/about/",
                        "https://example.com/legal/privacy-policy/",
                        "https://example.com/privacy-policy/",
                        "https://example.com/noindex-page/",
                        "https://example.com/sitemap/",
                    ],
                )
                self._write_titled_page(
                    root / "index.html",
                    "Любой title | Cultnova",
                    robots="index,follow",
                )
                self._write_titled_page(root / "blog" / "index.html", "Блог | Cultnova", robots="index,follow")
                self._write_titled_page(
                    root / "articles" / "live-article" / "index.html",
                    "Статья Beta | Cultnova",
                    robots="index,follow",
                )
                self._write_titled_page(root / "projects" / "index.html", "Проекты | Cultnova", robots="index,follow")
                self._write_titled_page(
                    root / "projects" / "live-project" / "index.html",
                    "Проект Alpha | Cultnova",
                    robots="index,follow",
                )
                self._write_titled_page(
                    root / "create" / "museum-spaces" / "index.html",
                    "Создание музеев | Cultnova",
                    robots="index,follow",
                )
                self._write_titled_page(root / "museum" / "index.html", "Музеи и пространства | Cultnova", robots="index,follow")
                self._write_titled_page(root / "info" / "about-company" / "index.html", "О компании | Cultnova", robots="index,follow")
                self._write_titled_page(root / "about" / "index.html", "О компании старая | Cultnova", robots="index,follow")
                self._write_titled_page(
                    root / "legal" / "privacy-policy" / "index.html",
                    "Политика конфиденциальности",
                    robots="index,follow",
                )
                self._write_titled_page(
                    root / "privacy-policy" / "index.html",
                    "Старая политика | Cultnova",
                    robots="index,follow",
                )
                self._write_titled_page(
                    root / "noindex-page" / "index.html",
                    "Скрытая страница | Cultnova",
                    robots="noindex, nofollow",
                )

                sections = build_html_sitemap()
                section_map = {section.key: section for section in sections}

                self.assertEqual([link.path for link in section_map["main"].links], ["/", "/blog/", "/projects/"])
                self.assertEqual(section_map["main"].links[0].title, "ГЛАВНАЯ СТРАНИЦА")
                self.assertEqual([link.title for link in section_map["articles"].links], ["Статья Beta"])
                self.assertEqual([link.title for link in section_map["projects"].links], ["Проект Alpha"])
                self.assertEqual(
                    [link.title for link in section_map["create"].links],
                    ["Создание музеев", "Музеи и пространства"],
                )
                self.assertEqual([link.path for link in section_map["info"].links], ["/info/about-company/", "/about/"])
                self.assertEqual([link.path for link in section_map["legal"].links], ["/legal/privacy-policy/", "/privacy-policy/"])

                all_paths = [link.path for section in sections for link in section.links]
                self.assertNotIn("/sitemap/", all_paths)
                self.assertNotIn("/noindex-page/", all_paths)

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

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_build_static_html_sitemap_page_writes_public_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                root = Path(temp_dir)
                self._write_sitemap_xml(
                    root / "sitemap.xml",
                    [
                        "https://example.com/",
                        "https://example.com/articles/live-article/",
                    ],
                )
                self._write_titled_page(root / "index.html", "Главная | Cultnova", robots="index,follow")
                self._write_titled_page(
                    root / "articles" / "live-article" / "index.html",
                    "Статья Beta | Cultnova",
                    robots="index,follow",
                )

                result = build_static_html_sitemap_page()

                self.assertEqual(result.output_path, root / "sitemap" / "index.html")
                self.assertEqual(result.section_count, 2)
                self.assertEqual(result.url_count, 2)

                html = result.output_path.read_text(encoding="utf-8")
                self.assertIn('data-page="sitemap"', html)
                self.assertIn("ГЛАВНАЯ СТРАНИЦА", html)
                self.assertIn("Статьи", html)
                self.assertIn("/articles/live-article/", html)
                self.assertIn("https://example.com/sitemap/", html)

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

    def _write_titled_page(self, target_path: Path, title: str, robots: str):
        self._write_html(
            target_path,
            (
                "<html><head>"
                f'<meta name="robots" content="{robots}">'
                f"<title>{title}</title>"
                "</head><body>Page</body></html>"
            ),
        )

    def _write_html(self, target_path: Path, content: str):
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(content, encoding="utf-8")


class FrontendPartialSyncTests(SimpleTestCase):
    def test_sync_frontend_partials_prefers_newer_repo_sources(self):
        with tempfile.TemporaryDirectory() as backend_dir, tempfile.TemporaryDirectory() as frontend_dir:
            backend_root = Path(backend_dir)
            frontend_root = Path(frontend_dir)

            self._write_partial_sources(
                frontend_root,
                {
                    "src/partials/header.html": '<header><a href="{{ROOT}}create/museum/">Header</a></header>',
                    "src/partials/footer.html": '<footer><a href="{{ROOT}}info/contact/">Footer</a></footer>',
                    "src/partials/popup.html": '<div><a href="{{ROOT}}legal/privacy-policy/">Popup</a></div>',
                    "src/partials/call-back.html": '<div><a href="{{ROOT}}legal/personal-data/">Callback</a></div>',
                },
            )
            self._write_export_bundle(
                frontend_root / "deploy_artifacts" / "backend-partials",
                generated_at="2026-03-01T00:00:00Z",
                files={
                    "header.html": "<header>stale export</header>",
                    "footer.html": "<footer>stale export</footer>",
                    "popup.html": "<div>stale export</div>",
                    "callback_popup.html": "<div>stale export</div>",
                },
            )

            source_mtime = datetime(2026, 4, 3, 12, 0, 0, tzinfo=dt_timezone.utc).timestamp()
            for file_path in (frontend_root / "src" / "partials").glob("*.html"):
                os.utime(file_path, (source_mtime, source_mtime))

            result = sync_frontend_partials(backend_root, frontend_repo_path=frontend_root, strict=True)

            self.assertIsNotNone(result)
            self.assertEqual(result.source_kind, "repo")
            header = (backend_root / "templates" / "partials" / "header.html").read_text(encoding="utf-8")
            self.assertIn("source: src/partials/header.html", header)
            self.assertIn('href="/create/museum/"', header)
            self.assertNotIn("{{ROOT}}", header)

    def test_sync_frontend_partials_uses_export_bundle_when_repo_is_unavailable(self):
        with tempfile.TemporaryDirectory() as backend_dir, tempfile.TemporaryDirectory() as export_dir:
            backend_root = Path(backend_dir)
            export_root = Path(export_dir)
            self._write_export_bundle(
                export_root,
                generated_at="2026-04-03T09:30:00Z",
                files={
                    "header.html": "<header>export header</header>",
                    "footer.html": "<footer>export footer</footer>",
                    "popup.html": "<div>export popup</div>",
                    "callback_popup.html": "<div>export callback</div>",
                },
            )

            result = sync_frontend_partials(backend_root, frontend_export_dir=export_root, strict=True)

            self.assertIsNotNone(result)
            self.assertEqual(result.source_kind, "export")
            footer = (backend_root / "templates" / "partials" / "footer.html").read_text(encoding="utf-8")
            self.assertIn("source: src/partials/footer.html", footer)
            self.assertIn("export footer", footer)

    def test_sync_frontend_partials_strict_raises_when_source_missing(self):
        with tempfile.TemporaryDirectory() as backend_dir:
            with self.assertRaises(FileNotFoundError):
                sync_frontend_partials(Path(backend_dir), strict=True)

    def _write_partial_sources(self, frontend_root: Path, files: dict[str, str]):
        for relative_path, content in files.items():
            target_path = frontend_root / relative_path
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(content, encoding="utf-8")

    def _write_export_bundle(self, export_root: Path, generated_at: str, files: dict[str, str]):
        export_root.mkdir(parents=True, exist_ok=True)
        manifest_files = []
        for target_name, content in files.items():
            (export_root / target_name).write_text(f"{content}\n", encoding="utf-8")
            source_name = "src/partials/call-back.html" if target_name == "callback_popup.html" else f"src/partials/{target_name}"
            manifest_files.append({"source": source_name, "target": target_name})

        manifest = {
            "version": 1,
            "generatedAt": generated_at,
            "files": manifest_files,
        }
        (export_root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
