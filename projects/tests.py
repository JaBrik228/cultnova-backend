import tempfile
from pathlib import Path
from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from projects.models import ProjectCategories, Projects, ProjectsContentBlock
from projects.services.project_listing import (
    PROJECTS_LISTING_PAGE_SIZE,
    build_public_project_category_path,
    build_public_projects_path,
)
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


class ProjectsListingViewTests(TestCase):
    def setUp(self):
        self.museums = ProjectCategories.objects.create(title="Museums", slug="museums")
        self.education = ProjectCategories.objects.create(title="Education", slug="education")
        self.empty_category = ProjectCategories.objects.create(title="Empty", slug="empty")

        self.first_project = Projects.objects.create(
            title="Museum Alpha",
            slug="museum-alpha",
            category=self.museums,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            excerpt="Alpha excerpt",
            preview_image="https://example.com/alpha.jpg",
            preview_image_alt="Alpha alt",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        self.second_project = Projects.objects.create(
            title="Museum Beta",
            slug="museum-beta",
            category=self.museums,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            excerpt="Beta excerpt",
            preview_image="https://example.com/beta.jpg",
            preview_image_alt="Beta alt",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        self.third_project = Projects.objects.create(
            title="Education Gamma",
            slug="education-gamma",
            category=self.education,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            excerpt="Gamma excerpt",
            preview_image="https://example.com/gamma.jpg",
            preview_image_alt="Gamma alt",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        self.fourth_project = Projects.objects.create(
            title="Education Delta",
            slug="education-delta",
            category=self.education,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            excerpt="Delta excerpt",
            preview_image="https://example.com/delta.jpg",
            preview_image_alt="Delta alt",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )

        now = timezone.now()
        Projects.objects.filter(pk=self.first_project.pk).update(created_at=now - timedelta(minutes=4))
        Projects.objects.filter(pk=self.second_project.pk).update(created_at=now - timedelta(minutes=3))
        Projects.objects.filter(pk=self.third_project.pk).update(created_at=now - timedelta(minutes=2))
        Projects.objects.filter(pk=self.fourth_project.pk).update(created_at=now - timedelta(minutes=1))

    def test_projects_root_page_renders_first_batch_and_load_more_state(self):
        response = self.client.get(reverse("projects:projects_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-projects-endpoint="https://cms.cultnova.ru/api/projects/"')
        self.assertContains(response, f'data-projects-page-size="{PROJECTS_LISTING_PAGE_SIZE}"')
        self.assertContains(response, "Education Delta")
        self.assertContains(response, "Education Gamma")
        self.assertContains(response, "Museum Beta")
        self.assertNotContains(response, "Museum Alpha")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "Показать еще")

    def test_projects_category_page_activates_selected_filter_and_excludes_other_categories(self):
        response = self.client.get(reverse("projects:projects_category_list", kwargs={"slug": self.museums.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'data-projects-endpoint="https://cms.cultnova.ru/api/projects/category/{self.museums.slug}/"',
        )
        self.assertContains(response, f'href="{build_public_project_category_path(self.museums.slug)}"')
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "Museum Alpha")
        self.assertContains(response, "Museum Beta")
        self.assertNotContains(response, "Education Gamma")
        self.assertNotContains(response, "Education Delta")

    def test_empty_category_page_renders_empty_state(self):
        response = self.client.get(reverse("projects:projects_category_list", kwargs={"slug": self.empty_category.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "В категории «Empty» пока нет опубликованных проектов.",
        )
        self.assertContains(response, 'id="projectsEmpty"')


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

    def test_all_projects_endpoint_excludes_unpublished_and_noindex_projects(self):
        Projects.objects.create(
            title="SEO Closed",
            slug="seo-closed-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            seo_robots="noindex,follow",
            is_published=True,
        )

        response = self.client.get(reverse("projects:get_all_projects"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["current_page"], 1)
        self.assertFalse(payload["has_next"])
        self.assertFalse(payload["has_previous"])
        self.assertIsNone(payload["next_page"])
        self.assertEqual(len(payload["data"]), 1)

        item = payload["data"][0]
        self.assertEqual(item["slug"], self.project.slug)
        self.assertEqual(item["category_title"], self.category.title)
        self.assertEqual(item["preview"], "https://example.com/preview.jpg")
        self.assertEqual(item["preview_image_alt"], "Preview alt")
        self.assertEqual(item["excerpt"], "Excerpt")
        self.assertEqual(item["images"], [{"url": "https://example.com/image.jpg", "alt": "Alt"}])
        self.assertNotIn(self.hidden_project.slug, [entry["slug"] for entry in payload["data"]])
        self.assertNotIn("seo-closed-project", [entry["slug"] for entry in payload["data"]])

    def test_all_projects_endpoint_includes_images_with_alt_and_order(self):
        ProjectsContentBlock.objects.create(
            project=self.project,
            type=ProjectsContentBlock.IMAGE,
            order=2,
            media="https://example.com/image-2.jpg",
            media_alt="",
            caption="Second caption",
        )
        ProjectsContentBlock.objects.create(
            project=self.project,
            type=ProjectsContentBlock.VIDEO,
            order=3,
            media="https://example.com/video.mp4",
            first_video_frame="https://example.com/poster.jpg",
            caption="Video caption",
        )

        with self.assertNumQueries(3):
            response = self.client.get(reverse("projects:get_all_projects"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        item = payload["data"][0]

        self.assertEqual(
            item["images"],
            [
                {"url": "https://example.com/image.jpg", "alt": "Alt"},
                {"url": "https://example.com/image-2.jpg", "alt": self.project.title},
            ],
        )
        self.assertNotIn("video.mp4", [image["url"] for image in item["images"]])

    def test_all_projects_endpoint_paginates_with_current_page(self):
        second_visible = Projects.objects.create(
            title="Second Visible",
            slug="second-visible-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        third_visible = Projects.objects.create(
            title="Third Visible",
            slug="third-visible-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        now = timezone.now()
        Projects.objects.filter(pk=self.project.pk).update(created_at=now - timedelta(minutes=3))
        Projects.objects.filter(pk=second_visible.pk).update(created_at=now - timedelta(minutes=2))
        Projects.objects.filter(pk=third_visible.pk).update(created_at=now - timedelta(minutes=1))

        response_page_1 = self.client.get(reverse("projects:get_all_projects"), {"limit": 2, "page": 1})

        self.assertEqual(response_page_1.status_code, 200)
        payload_page_1 = response_page_1.json()
        self.assertEqual(payload_page_1["current_page"], 1)
        self.assertTrue(payload_page_1["has_next"])
        self.assertEqual(payload_page_1["next_page"], 2)
        self.assertEqual(len(payload_page_1["data"]), 2)
        self.assertEqual({entry["slug"] for entry in payload_page_1["data"]}, {second_visible.slug, third_visible.slug})

        response_page_2 = self.client.get(reverse("projects:get_all_projects"), {"limit": 2, "page": 2})

        self.assertEqual(response_page_2.status_code, 200)
        payload_page_2 = response_page_2.json()
        self.assertEqual(payload_page_2["current_page"], 2)
        self.assertTrue(payload_page_2["has_previous"])
        self.assertFalse(payload_page_2["has_next"])
        self.assertIsNone(payload_page_2["next_page"])
        self.assertEqual(len(payload_page_2["data"]), 1)
        self.assertEqual(payload_page_2["data"][0]["slug"], self.project.slug)

    def test_projects_by_category_filters_unpublished_and_returns_string_preview(self):
        Projects.objects.create(
            title="Category Noindex",
            slug="category-noindex",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            excerpt="Hidden by SEO",
            seo_title="SEO",
            seo_description="SEO",
            seo_robots="noindex,follow",
            is_published=True,
        )

        response = self.client.get(f"/api/projects/{self.category.slug}")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["data"]), 1)
        self.assertEqual(payload["page"], 1)
        self.assertEqual(payload["data"][0]["slug"], self.project.slug)
        self.assertEqual(payload["data"][0]["preview"], "https://example.com/preview.jpg")
        self.assertEqual(payload["data"][0]["preview_image_alt"], "Preview alt")
        self.assertEqual(payload["data"][0]["category_title"], self.category.title)
        self.assertEqual(payload["data"][0]["excerpt"], "Excerpt")

    def test_explicit_category_endpoint_matches_legacy_category_payload(self):
        legacy_response = self.client.get(f"/api/projects/{self.category.slug}")
        explicit_response = self.client.get(f"/api/projects/category/{self.category.slug}/")

        self.assertEqual(explicit_response.status_code, 200)
        self.assertEqual(legacy_response.json(), explicit_response.json())

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
                listing_target = Path(temp_dir) / "projects" / "index.html"
                category_target = Path(temp_dir) / "projects" / "category" / category.slug / "index.html"
                sitemap_path = Path(temp_dir) / "sitemap.xml"
                self.assertTrue(target.exists())
                self.assertTrue(listing_target.exists())
                self.assertTrue(category_target.exists())
                self.assertIn('data-page="project"', target.read_text(encoding="utf-8"))
                self.assertIn('data-page="projects"', listing_target.read_text(encoding="utf-8"))
                self.assertIn(category.title, category_target.read_text(encoding="utf-8"))
                self.assertIn("/projects/static-project/", sitemap_path.read_text(encoding="utf-8"))
                self.assertIn(build_public_projects_path(), sitemap_path.read_text(encoding="utf-8"))
                self.assertIn(
                    build_public_project_category_path(category.slug),
                    sitemap_path.read_text(encoding="utf-8"),
                )

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

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_category_slug_change_rebuilds_category_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                with self.captureOnCommitCallbacks(execute=True):
                    category = ProjectCategories.objects.create(title="Cat", slug="old-cat")

                old_target = Path(temp_dir) / "projects" / "category" / "old-cat" / "index.html"
                self.assertTrue(old_target.exists())

                with self.captureOnCommitCallbacks(execute=True):
                    category.title = "Cat Updated"
                    category.slug = "new-cat"
                    category.save(update_fields=["title", "slug"])

                new_target = Path(temp_dir) / "projects" / "category" / "new-cat" / "index.html"

                self.assertFalse(old_target.exists())
                self.assertTrue(new_target.exists())
                self.assertIn("Cat Updated", new_target.read_text(encoding="utf-8"))

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_category_delete_removes_generated_category_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                with self.captureOnCommitCallbacks(execute=True):
                    category = ProjectCategories.objects.create(title="Cat", slug="cat")
                category_target = Path(temp_dir) / "projects" / "category" / category.slug / "index.html"
                self.assertTrue(category_target.exists())

                with self.captureOnCommitCallbacks(execute=True):
                    category.delete()

                self.assertFalse(category_target.exists())

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_new_category_is_added_to_root_and_existing_category_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                with self.captureOnCommitCallbacks(execute=True):
                    first_category = ProjectCategories.objects.create(title="Museums", slug="museums")
                root_page = Path(temp_dir) / "projects" / "index.html"
                first_category_page = Path(temp_dir) / "projects" / "category" / first_category.slug / "index.html"

                with self.captureOnCommitCallbacks(execute=True):
                    ProjectCategories.objects.create(title="Education", slug="education")

                self.assertIn("Education", root_page.read_text(encoding="utf-8"))
                self.assertIn("Education", first_category_page.read_text(encoding="utf-8"))

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_project_category_reassignment_updates_old_and_new_category_pages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                old_category = ProjectCategories.objects.create(title="Museums", slug="museums")
                new_category = ProjectCategories.objects.create(title="Education", slug="education")
                with self.captureOnCommitCallbacks(execute=True):
                    project = Projects.objects.create(
                        title="Moved Project",
                        slug="moved-project",
                        category=old_category,
                        customer_name="Client",
                        year=2025,
                        type="Type",
                        body_html="<p>Body</p>",
                        excerpt="Excerpt",
                        seo_title="SEO",
                        seo_description="SEO",
                        is_published=True,
                    )

                old_category_page = Path(temp_dir) / "projects" / "category" / old_category.slug / "index.html"
                new_category_page = Path(temp_dir) / "projects" / "category" / new_category.slug / "index.html"
                self.assertIn("Moved Project", old_category_page.read_text(encoding="utf-8"))

                with self.captureOnCommitCallbacks(execute=True):
                    project.category = new_category
                    project.save(update_fields=["category"])

                self.assertNotIn("Moved Project", old_category_page.read_text(encoding="utf-8"))
                self.assertIn("Moved Project", new_category_page.read_text(encoding="utf-8"))
