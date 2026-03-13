import tempfile
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from projects.models import ProjectCategories, Projects, ProjectsContentBlock
from projects.services.project_rendering import build_project_render_context


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


class ProjectBodyMigrationTests(MigrationTestCase):
    migrate_from = ("projects", "0008_alter_projectcategories_options_projects_body_html_and_more")
    migrate_to = ("projects", "0009_migrate_project_body_html_and_seo")

    def set_up_before_migration(self, apps):
        ProjectCategories = apps.get_model("projects", "ProjectCategories")
        Projects = apps.get_model("projects", "Projects")
        ProjectsContentBlock = apps.get_model("projects", "ProjectsContentBlock")

        category = ProjectCategories.objects.create(title="Museums", slug="museums")
        project = Projects.objects.create(
            title="Migration Project",
            slug="migration-project",
            category_id=category.id,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="",
            seo_title="",
            seo_description="",
            preview_image="https://example.com/preview.jpg",
            preview_image_alt="",
        )
        self.project_id = project.id

        ProjectsContentBlock.objects.create(project_id=project.id, type="text", order=1, text="First line")
        ProjectsContentBlock.objects.create(project_id=project.id, type="heading", order=2, text="Second line")
        ProjectsContentBlock.objects.create(
            project_id=project.id,
            type="image",
            order=3,
            media="https://example.com/image.jpg",
            media_alt="",
        )

    def test_legacy_text_blocks_are_migrated_and_cleaned(self):
        Projects = self.apps.get_model("projects", "Projects")
        ProjectsContentBlock = self.apps.get_model("projects", "ProjectsContentBlock")

        project = Projects.objects.get(pk=self.project_id)

        self.assertIn("First line", project.body_html)
        self.assertIn("Second line", project.body_html)
        self.assertFalse(ProjectsContentBlock.objects.filter(type="text").exists())
        self.assertFalse(ProjectsContentBlock.objects.filter(type="heading").exists())

        image_block = ProjectsContentBlock.objects.get(type="image")
        self.assertTrue(image_block.media_alt)
        self.assertTrue(project.seo_title)
        self.assertTrue(project.seo_description)
        self.assertTrue(project.preview_image_alt)


class ProjectRenderingTests(TestCase):
    def setUp(self):
        self.category = ProjectCategories.objects.create(title="Museums", slug="museums")

    def test_build_project_render_context_builds_feature_media_related_and_seo(self):
        project = Projects.objects.create(
            title="Main Project",
            slug="main-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Installation",
            body_html="<p>Body</p>",
            excerpt="Excerpt",
            preview_image="https://example.com/preview.jpg",
            preview_image_alt="Preview alt",
            seo_title="SEO title",
            seo_description="SEO description",
            is_published=True,
        )

        ProjectsContentBlock.objects.create(
            project=project,
            type=ProjectsContentBlock.IMAGE,
            order=1,
            media="https://example.com/image.jpg",
            media_alt="Image alt",
            caption="Image caption",
        )
        ProjectsContentBlock.objects.create(
            project=project,
            type=ProjectsContentBlock.VIDEO,
            order=2,
            media="https://example.com/video.mp4",
            first_video_frame="https://example.com/poster.jpg",
            caption="Video caption",
        )

        Projects.objects.create(
            title="Related",
            slug="related",
            category=self.category,
            customer_name="Client",
            year=2024,
            type="Type",
            body_html="<p>R</p>",
            seo_title="R",
            seo_description="R",
            is_published=True,
        )

        context = build_project_render_context(project)
        rendered = context["project"]

        self.assertEqual(rendered.seo["title"], "SEO title")
        self.assertEqual(rendered.feature_media["kind"], "video")
        self.assertEqual(len(rendered.gallery_media), 1)
        self.assertTrue(rendered.share_links)
        self.assertTrue(context["related_projects"])
        self.assertIn("CreativeWork", context["project_json_ld"])


class ProjectApiTests(TestCase):
    def setUp(self):
        self.category = ProjectCategories.objects.create(title="Museums", slug="museums")
        self.project = Projects.objects.create(
            title="Visible",
            slug="visible-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            excerpt="Excerpt",
            seo_title="SEO",
            seo_description="SEO",
            preview_image="https://example.com/preview.jpg",
            preview_image_alt="Preview alt",
            is_published=True,
        )
        self.hidden_project = Projects.objects.create(
            title="Hidden",
            slug="hidden-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=False,
        )

        ProjectsContentBlock.objects.create(
            project=self.project,
            type=ProjectsContentBlock.IMAGE,
            order=1,
            media="https://example.com/image.jpg",
            media_alt="Alt",
            caption="Caption",
        )

    def test_projects_by_category_filters_unpublished_and_returns_string_preview(self):
        response = self.client.get(f"/api/projects/{self.category.slug}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["data"]), 1)
        self.assertEqual(payload["data"][0]["slug"], self.project.slug)
        self.assertEqual(payload["data"][0]["preview"], "https://example.com/preview.jpg")

    def test_project_legacy_detail_endpoint_keeps_list_and_has_media_fields(self):
        response = self.client.get(f"/api/projects/detail/{self.project.slug}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertIsInstance(payload, list)
        self.assertEqual(payload[0]["media_alt"], "Alt")
        self.assertEqual(payload[0]["caption"], "Caption")

    def test_project_full_detail_endpoint_returns_body_and_seo(self):
        response = self.client.get(f"/api/projects/detail/{self.project.slug}/full")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["slug"], self.project.slug)
        self.assertIn("body_html", payload)
        self.assertIn("seo", payload)

    def test_project_html_detail_route_available(self):
        response = self.client.get(f"/projects/{self.project.slug}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.title)


class ProjectAdminInlineImageUploadTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password123",
        )
        self.url = reverse("admin:projects_projects_inline_image_upload")

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

    @patch("projects.admin.upload_media_to_vk_cloud", return_value="https://cdn.example.com/projects/inline/image.png")
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
        self.assertEqual(payload["url"], "https://cdn.example.com/projects/inline/image.png")
        self.assertIn("<figure>", payload["html"])
        self.assertIn('alt="Inline alt"', payload["html"])
        upload_mock.assert_called_once()


class ProjectStaticGenerationSignalTests(TestCase):
    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_static_html_is_generated_and_removed_on_unpublish(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                category = ProjectCategories.objects.create(title="Cat", slug="cat")
                with self.captureOnCommitCallbacks(execute=True):
                    project = Projects.objects.create(
                        title="Static Project",
                        slug="static-project",
                        category=category,
                        customer_name="Client",
                        year=2025,
                        type="Type",
                        body_html="<p>Body</p>",
                        seo_title="SEO",
                        seo_description="SEO",
                        is_published=True,
                    )

                target = Path(temp_dir) / "projects" / project.slug / "index.html"
                sitemap_path = Path(temp_dir) / "sitemap.xml"
                self.assertTrue(target.exists())
                self.assertIn("/projects/static-project/", sitemap_path.read_text(encoding="utf-8"))

                with self.captureOnCommitCallbacks(execute=True):
                    project.is_published = False
                    project.save(update_fields=["is_published"])

                self.assertFalse(target.exists())
                self.assertNotIn("/projects/static-project/", sitemap_path.read_text(encoding="utf-8"))

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_project_slug_change_updates_generated_html_and_sitemap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                category = ProjectCategories.objects.create(title="Cat", slug="cat")
                with self.captureOnCommitCallbacks(execute=True):
                    project = Projects.objects.create(
                        title="Renamed Project",
                        slug="old-project-slug",
                        category=category,
                        customer_name="Client",
                        year=2025,
                        type="Type",
                        body_html="<p>Body</p>",
                        seo_title="SEO",
                        seo_description="SEO",
                        is_published=True,
                    )

                old_target = Path(temp_dir) / "projects" / "old-project-slug" / "index.html"
                sitemap_path = Path(temp_dir) / "sitemap.xml"

                with self.captureOnCommitCallbacks(execute=True):
                    project.slug = "new-project-slug"
                    project.save(update_fields=["slug"])

                new_target = Path(temp_dir) / "projects" / "new-project-slug" / "index.html"
                sitemap = sitemap_path.read_text(encoding="utf-8")

                self.assertFalse(old_target.exists())
                self.assertTrue(new_target.exists())
                self.assertIn("/projects/new-project-slug/", sitemap)
                self.assertNotIn("/projects/old-project-slug/", sitemap)

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_project_block_save_updates_lastmod_in_sitemap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                category = ProjectCategories.objects.create(title="Cat", slug="cat")
                with self.captureOnCommitCallbacks(execute=True):
                    project = Projects.objects.create(
                        title="Updated Project",
                        slug="updated-project",
                        category=category,
                        customer_name="Client",
                        year=2025,
                        type="Type",
                        body_html="<p>Body</p>",
                        seo_title="SEO",
                        seo_description="SEO",
                        is_published=True,
                    )

                older_timestamp = timezone.now() - timedelta(days=1)
                Projects.objects.filter(pk=project.pk).update(updated_at=older_timestamp)
                project.refresh_from_db()

                with self.captureOnCommitCallbacks(execute=True):
                    ProjectsContentBlock.objects.create(
                        project=project,
                        type=ProjectsContentBlock.IMAGE,
                        order=1,
                        media="https://example.com/image.jpg",
                        media_alt="Image alt",
                    )

                project.refresh_from_db()
                sitemap = (Path(temp_dir) / "sitemap.xml").read_text(encoding="utf-8")

                self.assertGreater(project.updated_at, older_timestamp)
                self.assertIn(project.updated_at.isoformat(timespec="seconds"), sitemap)
                self.assertIn("/projects/updated-project/", sitemap)
