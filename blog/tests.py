from datetime import datetime
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from blog.models import Articles, ArticlesContentBlock
from blog.services.article_rendering import _format_article_date_ru, build_article_render_context
from blog.services.rich_text import (
    normalize_legacy_text_to_html,
    sanitize_article_body_html,
    validate_lead_block_structure,
)


class RichTextServiceTests(TestCase):
    def test_normalize_legacy_text_to_html(self):
        html = normalize_legacy_text_to_html("First line\nSecond line\n\nThird line")
        self.assertEqual(html, "<p>First line<br>Second line</p><p>Third line</p>")

    def test_sanitize_article_body_html_preserves_table_and_cleans_dangerous_markup(self):
        html = sanitize_article_body_html(
            """
            <p class="article__lead another">Lead</p>
            <table><thead><tr><th colspan="2">Head</th></tr></thead>
            <tbody><tr><td rowspan="2">A</td><td>B</td></tr></tbody></table>
            <script>alert(1)</script>
            <figure><img src="https://example.com/image.jpg" alt="Example"></figure>
            """
        )

        self.assertIn('<p class="article__lead">Lead</p>', html)
        self.assertIn("<table>", html)
        self.assertIn('colspan="2"', html)
        self.assertIn('rowspan="2"', html)
        self.assertNotIn("<script>", html)
        self.assertIn('loading="lazy"', html)
        self.assertIn('decoding="async"', html)

    def test_validate_lead_block_structure_rejects_invalid_layout(self):
        with self.assertRaisesMessage(ValueError, "Lead paragraph must be the first content block"):
            validate_lead_block_structure("<p>Body</p><p class=\"article__lead\">Lead</p>")

        with self.assertRaisesMessage(ValueError, "Only one lead paragraph is allowed"):
            validate_lead_block_structure(
                '<p class="article__lead">Lead</p><p class="article__lead">Lead 2</p>'
            )


class ArticleRenderingTests(TestCase):
    def test_format_article_date_ru_uses_russian_month_names_without_leading_zero(self):
        january = timezone.make_aware(datetime(2026, 1, 5, 15, 0))
        november = timezone.make_aware(datetime(2026, 11, 20, 15, 0))

        self.assertEqual(_format_article_date_ru(january), "5 января 2026")
        self.assertEqual(_format_article_date_ru(november), "20 ноября 2026")

    def test_build_article_render_context_formats_published_date_like_figma(self):
        article = Articles.objects.create(
            title="Article",
            slug="dated-article",
            body_html="<p>Body</p>",
            excerpt="Excerpt",
            seo_title="SEO Title",
            seo_description="SEO Description",
        )
        created_at = timezone.make_aware(datetime(2026, 1, 20, 10, 30))
        Articles.objects.filter(pk=article.pk).update(created_at=created_at)
        article.refresh_from_db()

        context = build_article_render_context(article)

        self.assertEqual(context["article"].published_at_display, "20 января 2026")
        self.assertEqual(context["article"].published_at_iso, article.created_at.isoformat())

    def test_build_article_render_context_uses_body_html_and_sidebar_media_only(self):
        article = Articles.objects.create(
            title="Article",
            slug="article",
            body_html='<p class="article__lead">Lead</p><h2>Section</h2><script>alert(1)</script><p>Body</p>',
            excerpt="Excerpt",
            seo_title="SEO Title",
            seo_description="SEO Description",
            preview_image_alt="Preview alt",
        )
        ArticlesContentBlock.objects.create(
            article=article,
            type=ArticlesContentBlock.IMAGE,
            order=1,
            media="https://example.com/image.jpg",
            media_alt="Image alt",
            caption="Image caption",
        )
        ArticlesContentBlock.objects.create(
            article=article,
            type=ArticlesContentBlock.VIDEO,
            order=2,
            media="https://example.com/video.mp4",
            first_video_frame="https://example.com/video.jpg",
            caption="Video caption",
        )
        ArticlesContentBlock.objects.create(
            article=article,
            type="text",
            order=3,
            text="Legacy block should not render",
        )

        context = build_article_render_context(article)
        rendered_article = context["article"]

        self.assertIn('<p class="article__lead">Lead</p>', rendered_article.body_html)
        self.assertIn("<h2>Section</h2>", rendered_article.body_html)
        self.assertNotIn("<script>", rendered_article.body_html)
        self.assertNotIn("Legacy block should not render", rendered_article.body_html)
        self.assertEqual(len(rendered_article.media), 2)
        self.assertEqual(rendered_article.media[0]["kind"], "image")
        self.assertEqual(rendered_article.media[1]["kind"], "video")
        self.assertTrue(rendered_article.has_video)


class MigrationTestCase(TransactionTestCase):
    migrate_from = None
    migrate_to = None
    databases = {"default"}

    def setUp(self):
        super().setUp()
        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_from])
        self.old_apps = self.executor.loader.project_state([self.migrate_from]).apps
        self.set_up_before_migration(self.old_apps)

        self.executor = MigrationExecutor(connection)
        self.executor.migrate([self.migrate_to])
        self.apps = self.executor.loader.project_state([self.migrate_to]).apps

    def set_up_before_migration(self, apps):
        pass


class ArticleBodyMigrationTests(MigrationTestCase):
    migrate_from = ("blog", "0010_articles_body_html")
    migrate_to = ("blog", "0011_migrate_article_body_html")

    def set_up_before_migration(self, apps):
        Articles = apps.get_model("blog", "Articles")
        ArticlesContentBlock = apps.get_model("blog", "ArticlesContentBlock")

        article = Articles.objects.create(
            title="Migrated article",
            slug="migrated-article",
            body_html="",
            excerpt="Excerpt",
            seo_title="SEO title",
            seo_description="SEO description",
        )
        self.article_id = article.id

        ArticlesContentBlock.objects.create(article_id=article.id, type="text", order=1, text="First line\n\nSecond line")
        ArticlesContentBlock.objects.create(
            article_id=article.id,
            type="text",
            order=2,
            text="<h2>Section</h2><script>alert(1)</script><p>Body</p>",
        )
        ArticlesContentBlock.objects.create(article_id=article.id, type="heading", order=3, text="Legacy heading")
        ArticlesContentBlock.objects.create(
            article_id=article.id,
            type="image",
            order=4,
            media="https://example.com/side.jpg",
            media_alt="Sidebar alt",
            caption="Sidebar caption",
        )

    def test_text_blocks_are_merged_into_body_html_and_legacy_blocks_are_removed(self):
        Articles = self.apps.get_model("blog", "Articles")
        ArticlesContentBlock = self.apps.get_model("blog", "ArticlesContentBlock")

        article = Articles.objects.get(pk=self.article_id)
        self.assertIn("<p>First line</p><p>Second line</p>", article.body_html)
        self.assertIn("<h2>Section</h2>", article.body_html)
        self.assertNotIn("<script>", article.body_html)
        self.assertFalse(ArticlesContentBlock.objects.filter(type="text").exists())
        self.assertFalse(ArticlesContentBlock.objects.filter(type="heading").exists())
        self.assertEqual(ArticlesContentBlock.objects.filter(type="image").count(), 1)


class InlineImageUploadAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.url = reverse("admin:blog_articles_inline_image_upload")

    def test_upload_requires_staff_authentication(self):
        response = self.client.post(self.url)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/backend-admin/login/", response.url)

    def test_upload_validates_required_alt(self):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            data={
                "file": SimpleUploadedFile("test.png", b"file", content_type="image/png"),
                "alt": "",
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertJSONEqual(response.content, {"success": False, "error": "Alt text is required."})

    @patch("blog.admin.upload_media_to_vk_cloud", return_value="https://cdn.example.com/articles/inline/image.png")
    def test_upload_returns_ready_html_fragment(self, upload_mock):
        self.client.force_login(self.user)
        response = self.client.post(
            self.url,
            data={
                "file": SimpleUploadedFile("test.png", b"file", content_type="image/png"),
                "alt": "Inline alt",
                "caption": "Inline caption",
            },
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["success"])
        self.assertEqual(payload["url"], "https://cdn.example.com/articles/inline/image.png")
        self.assertIn("<figure>", payload["html"])
        self.assertIn('alt="Inline alt"', payload["html"])
        self.assertIn("<figcaption>Inline caption</figcaption>", payload["html"])
        self.assertIn('loading="lazy"', payload["html"])
        upload_mock.assert_called_once()
