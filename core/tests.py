import os
import tempfile
from datetime import datetime, timezone as dt_timezone
from io import StringIO
from pathlib import Path

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.utils import timezone

from blog.models import Articles
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
