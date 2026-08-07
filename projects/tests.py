import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch
import json

from django.conf import settings
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.db.models.deletion import ProtectedError
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from projects.models import ProjectCategories, Projects, ProjectsContentBlock, ServicePageProjects
from projects.services.project_category_seo import (
    CURRENT_YEAR_TOKEN,
    get_project_category_current_year,
)
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


class ProjectCategorySeoMigrationTests(MigrationTestCase):
    migrate_from = ("projects", "0009_migrate_project_body_html_and_seo")
    migrate_to = ("projects", "0010_projectcategories_page_h1_and_seo_fields")

    def set_up_before_migration(self, apps):
        ProjectCategories = apps.get_model("projects", "ProjectCategories")
        category = ProjectCategories.objects.create(title="Museums", slug="museums")
        self.category_id = category.id

    def test_existing_categories_receive_new_seo_fields_and_noindex_defaults(self):
        ProjectCategories = self.apps.get_model("projects", "ProjectCategories")
        category = ProjectCategories.objects.get(pk=self.category_id)

        self.assertEqual(category.page_h1, "")
        self.assertEqual(category.seo_title, "")
        self.assertEqual(category.seo_description, "")
        self.assertEqual(category.seo_keywords, "")
        self.assertEqual(category.seo_robots, "noindex,nofollow")
        self.assertEqual(category.canonical_url, "")


class ProjectSortOrderMigrationTests(MigrationTestCase):
    migrate_from = ("projects", "0012_servicepageprojects_position")
    migrate_to = ("projects", "0013_projects_sort_order")

    def set_up_before_migration(self, apps):
        ProjectCategories = apps.get_model("projects", "ProjectCategories")
        Projects = apps.get_model("projects", "Projects")

        category = ProjectCategories.objects.create(title="Museums", slug="museums")
        oldest = Projects.objects.create(
            title="Oldest",
            slug="oldest",
            category_id=category.id,
            customer_name="Client",
            year=2023,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        middle = Projects.objects.create(
            title="Middle",
            slug="middle",
            category_id=category.id,
            customer_name="Client",
            year=2024,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        newest = Projects.objects.create(
            title="Newest",
            slug="newest",
            category_id=category.id,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )

        now = timezone.now()
        Projects.objects.filter(pk=oldest.pk).update(created_at=now - timedelta(days=3))
        Projects.objects.filter(pk=middle.pk).update(created_at=now - timedelta(days=2))
        Projects.objects.filter(pk=newest.pk).update(created_at=now - timedelta(days=1))

    def test_existing_projects_receive_sequential_sort_order_in_previous_public_order(self):
        Projects = self.apps.get_model("projects", "Projects")

        projects = list(Projects.objects.order_by("sort_order").values_list("slug", "sort_order"))

        self.assertEqual(
            projects,
            [("newest", 1), ("middle", 2), ("oldest", 3)],
        )


class ProjectCategoriesManyToManyMigrationTests(MigrationTestCase):
    migrate_from = ("projects", "0013_projects_sort_order")
    migrate_to = ("projects", "0014_project_categories_many_to_many")

    def set_up_before_migration(self, apps):
        ProjectCategories = apps.get_model("projects", "ProjectCategories")
        Projects = apps.get_model("projects", "Projects")

        older = ProjectCategories.objects.create(title="Older", slug="older")
        newer = ProjectCategories.objects.create(title="Newer", slug="newer")
        now = timezone.now()
        ProjectCategories.objects.filter(pk=older.pk).update(created_at=now - timedelta(days=1))
        ProjectCategories.objects.filter(pk=newer.pk).update(created_at=now)

        self.project_category_pairs = []
        for category, slug in ((older, "old-project"), (newer, "new-project")):
            project = Projects.objects.create(
                title=slug,
                slug=slug,
                category_id=category.pk,
                customer_name="Client",
                year=2025,
                type="Type",
                body_html="<p>Body</p>",
                seo_title="SEO",
                seo_description="SEO",
            )
            self.project_category_pairs.append((project.pk, category.pk))

    def test_fk_values_and_global_order_are_preserved_without_duplicate_pairs(self):
        ProjectCategories = self.apps.get_model("projects", "ProjectCategories")
        Projects = self.apps.get_model("projects", "Projects")

        self.assertEqual(
            list(ProjectCategories.objects.order_by("sort_order").values_list("slug", "sort_order")),
            [("newer", 1), ("older", 2)],
        )
        self.assertEqual(
            sorted(Projects.categories.through.objects.values_list("projects_id", "projectcategories_id")),
            sorted(self.project_category_pairs),
        )
        self.assertEqual(
            Projects.categories.through.objects.count(),
            Projects.categories.through.objects.values("projects_id", "projectcategories_id").distinct().count(),
        )


class ProjectCategoriesManyToManyReverseMigrationTests(MigrationTestCase):
    migrate_from = ("projects", "0014_project_categories_many_to_many")
    migrate_to = ("projects", "0013_projects_sort_order")

    def set_up_before_migration(self, apps):
        ProjectCategories = apps.get_model("projects", "ProjectCategories")
        Projects = apps.get_model("projects", "Projects")

        first = ProjectCategories.objects.create(title="First", slug="first-reverse", sort_order=1)
        second = ProjectCategories.objects.create(title="Second", slug="second-reverse", sort_order=2)
        project = Projects.objects.create(
            title="Reverse Project",
            slug="reverse-project",
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
        )
        project.categories.add(second, first)
        self.project_id = project.pk
        self.first_category_id = first.pk

    def test_reverse_uses_first_globally_ordered_category(self):
        Projects = self.apps.get_model("projects", "Projects")

        self.assertEqual(
            Projects.objects.get(pk=self.project_id).category_id,
            self.first_category_id,
        )


class ProjectCategoryCurrentYearHelperTests(TestCase):
    def test_current_year_uses_moscow_timezone(self):
        boundary_moment = datetime(2025, 12, 31, 21, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(get_project_category_current_year(now=boundary_moment), 2026)


class ProjectRenderingTests(TestCase):
    def setUp(self):
        self.category = ProjectCategories.objects.create(title="Museums", slug="museums")

    def test_build_project_render_context_builds_feature_media_related_and_seo(self):
        secondary_category = ProjectCategories.objects.create(
            title="Education",
            slug="education-rendering",
            sort_order=1,
        )
        self.category.sort_order = 2
        self.category.save(update_fields=["sort_order"])
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
        project.categories.add(secondary_category)

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

        related_project = Projects.objects.create(
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
        related_project.categories.add(secondary_category)

        context = build_project_render_context(project)
        rendered = context["project"]

        self.assertEqual(rendered.seo["title"], "SEO title")
        self.assertEqual(rendered.feature_media["kind"], "video")
        self.assertEqual(len(rendered.gallery_media), 1)
        self.assertTrue(rendered.share_links)
        self.assertTrue(context["related_projects"])
        self.assertEqual(len(context["related_projects"]), 1)
        self.assertEqual(rendered.categories_text, "Education · Museums")
        self.assertEqual(context["related_projects"][0]["categories_text"], "Education · Museums")
        self.assertIn("CreativeWork", context["project_json_ld"])


class ProjectDetailViewTests(TestCase):
    def test_project_detail_renders_inline_discuss_form_contract(self):
        category = ProjectCategories.objects.create(title="Museums", slug="museums")
        project = Projects.objects.create(
            title="Project",
            slug="project-with-inline-form",
            category=category,
            customer_name="Client",
            year=2025,
            type="Installation",
            body_html="<p>Body</p>",
            excerpt="Excerpt",
            seo_title="SEO title",
            seo_description="SEO description",
            is_published=True,
        )

        response = self.client.get(reverse("projects:project_detail", kwargs={"slug": project.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="project-discuss__form"')
        self.assertContains(response, 'data-form-type="project-discuss"')
        self.assertContains(response, 'name="name"')
        self.assertContains(response, 'name="company"')
        self.assertContains(response, 'name="email"')
        self.assertContains(response, 'name="phone"')
        self.assertContains(response, '<script src="/js/script.js"></script>', html=True)

    def test_project_detail_includes_lightbox_assets_and_keeps_video_player_assets(self):
        category = ProjectCategories.objects.create(title="Museums", slug="museums")
        project = Projects.objects.create(
            title="Project",
            slug="project-with-lightbox",
            category=category,
            customer_name="Client",
            year=2025,
            type="Installation",
            body_html='<figure><img src="https://example.com/inline.jpg" alt="Inline"></figure><p>Body</p>',
            excerpt="Excerpt",
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
        )

        response = self.client.get(reverse("projects:project_detail", kwargs={"slug": project.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '/vendor/photoswipe/photoswipe.css')
        self.assertContains(response, '/css/lightbox.css?v=2026-04-17-1')
        self.assertContains(response, '/vendor/photoswipe/photoswipe.umd.min.js')
        self.assertContains(response, '/vendor/photoswipe/photoswipe-lightbox.umd.min.js')
        self.assertContains(response, '/js/lightbox.js?v=2026-04-17-1')
        self.assertContains(response, '/js/video-player.js?v=2026-03-10-1')
        self.assertContains(response, 'data-page="project"')


class PublicStaticManifestTests(TestCase):
    def test_manifest_includes_lightbox_assets(self):
        with open("tools/public_static_manifest.json", "r", encoding="utf-8") as manifest_file:
            manifest = json.load(manifest_file)

        entries = {(entry["source"], entry["target"]) for entry in manifest["entries"]}

        self.assertIn(("static/css/lightbox.css", "css/lightbox.css"), entries)
        self.assertIn(("static/js/lightbox.js", "js/lightbox.js"), entries)
        self.assertIn(("static/vendor/photoswipe", "vendor/photoswipe"), entries)


class ProjectsListingViewTests(TestCase):
    def setUp(self):
        self.museums = ProjectCategories.objects.create(title="Museums", slug="museums")
        self.education = ProjectCategories.objects.create(title="Education", slug="education")
        self.empty_category = ProjectCategories.objects.create(title="Empty", slug="empty")

        self.first_project = Projects.objects.create(
            title="Museum Alpha",
            slug="museum-alpha",
            category=self.museums,
            sort_order=None,
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
            sort_order=1,
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
            sort_order=3,
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
            sort_order=2,
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

    def test_all_tab_stays_first_and_initial_cards_show_all_categories(self):
        self.education.sort_order = 1
        self.education.save(update_fields=["sort_order"])
        self.museums.sort_order = 2
        self.museums.save(update_fields=["sort_order"])
        self.second_project.categories.add(self.education)

        response = self.client.get(reverse("projects:projects_list"))

        self.assertEqual(
            [category["title"] for category in response.context["categories"][:3]],
            ["Все", "Education", "Museums"],
        )
        self.assertContains(response, "Education · Museums")

    def test_projects_root_page_renders_first_batch_and_load_more_state(self):
        response = self.client.get(reverse("projects:projects_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="projectsListingShell"')
        self.assertContains(response, 'data-projects-endpoint="https://cms.cultnova.ru/api/projects/"')
        self.assertContains(response, f'data-projects-page-size="{PROJECTS_LISTING_PAGE_SIZE}"')
        self.assertContains(response, 'data-projects-current-page="1"')
        self.assertContains(response, 'data-projects-next-page="2"')
        self.assertContains(response, 'data-projects-has-next="1"')
        self.assertContains(response, 'data-page-title="Реализованные проекты компании «CultNova»"')
        self.assertContains(response, 'hx-history-elt')
        self.assertContains(response, 'hx-boost="true"')
        self.assertContains(response, 'hx-target="#projectsListingShell"')
        self.assertContains(response, 'hx-select="#projectsListingShell"')
        self.assertContains(response, 'hx-swap="outerHTML show:none"')
        self.assertContains(response, 'hx-push-url="true"')
        html = response.content.decode("utf-8")
        self.assertLess(html.find("Museum Beta"), html.find("Education Delta"))
        self.assertLess(html.find("Education Delta"), html.find("Education Gamma"))
        self.assertContains(response, "Education Delta")
        self.assertContains(response, "Education Gamma")
        self.assertContains(response, "Museum Beta")
        self.assertNotContains(response, "Museum Alpha")
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "Показать еще")

    def test_projects_category_page_activates_selected_filter_and_excludes_other_categories(self):
        response = self.client.get(reverse("projects:projects_category_list", kwargs={"slug": self.museums.slug}))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="projectsListingShell"')
        self.assertContains(
            response,
            f'data-projects-endpoint="https://cms.cultnova.ru/api/projects/category/{self.museums.slug}/"',
        )
        self.assertContains(response, f'data-projects-page-size="{PROJECTS_LISTING_PAGE_SIZE}"')
        self.assertContains(response, 'data-projects-current-page="1"')
        self.assertContains(response, 'data-projects-next-page=""')
        self.assertContains(response, 'data-projects-has-next="0"')
        self.assertContains(response, 'data-page-title="Museums | Проекты | CultNova"')
        self.assertContains(response, 'hx-swap="outerHTML show:none"')
        self.assertContains(response, f'href="{build_public_project_category_path(self.museums.slug)}"')
        self.assertContains(response, 'aria-current="page"')
        html = response.content.decode("utf-8")
        self.assertLess(html.find("Museum Beta"), html.find("Museum Alpha"))
        self.assertContains(response, "Museum Alpha")
        self.assertContains(response, "Museum Beta")
        self.assertNotContains(response, "Education Gamma")
        self.assertNotContains(response, "Education Delta")

    def test_projects_category_page_uses_category_seo_and_custom_h1(self):
        self.museums.page_h1 = "Музеи и выставочные кейсы"
        self.museums.seo_title = "Музейные проекты"
        self.museums.seo_description = "Подборка музейных проектов Cultnova."
        self.museums.seo_keywords = "музеи, проекты, cultnova"
        self.museums.seo_robots = "noindex,nofollow"
        self.museums.canonical_url = "https://example.com/custom-category/"
        self.museums.save(
            update_fields=[
                "page_h1",
                "seo_title",
                "seo_description",
                "seo_keywords",
                "seo_robots",
                "canonical_url",
            ]
        )

        response = self.client.get(reverse("projects:projects_category_list", kwargs={"slug": self.museums.slug}))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("<title>Музейные проекты | CultNova</title>", html)
        self.assertIn('<meta name="description" content="Подборка музейных проектов Cultnova." />', html)
        self.assertIn('<meta name="keywords" content="музеи, проекты, cultnova" />', html)
        self.assertIn('<meta name="robots" content="noindex,nofollow" />', html)
        self.assertIn('<link rel="canonical" href="https://example.com/custom-category/" />', html)
        self.assertIn('<meta property="og:url" content="https://example.com/custom-category/" />', html)
        self.assertIn(">Музеи и выставочные кейсы</h1>", html)
        self.assertIn('"mainEntityOfPage": "https://example.com/custom-category/"', html)

    def test_projects_category_page_resolves_current_year_token_in_supported_fields(self):
        current_year = get_project_category_current_year()
        self.museums.page_h1 = f"Кейсы {CURRENT_YEAR_TOKEN}"
        self.museums.seo_title = f"Музейные проекты {CURRENT_YEAR_TOKEN}"
        self.museums.seo_description = f"Подборка музейных проектов Cultnova за {CURRENT_YEAR_TOKEN}."
        self.museums.seo_keywords = f"музеи, проекты, {CURRENT_YEAR_TOKEN}"
        self.museums.save(
            update_fields=[
                "page_h1",
                "seo_title",
                "seo_description",
                "seo_keywords",
            ]
        )

        response = self.client.get(reverse("projects:projects_category_list", kwargs={"slug": self.museums.slug}))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn(f"<title>Музейные проекты {current_year} | CultNova</title>", html)
        self.assertIn(
            f'<meta name="description" content="Подборка музейных проектов Cultnova за {current_year}." />',
            html,
        )
        self.assertIn(f'<meta name="keywords" content="музеи, проекты, {current_year}" />', html)
        self.assertIn(f">Кейсы {current_year}</h1>", html)
        self.assertIn(f'"description": "Подборка музейных проектов Cultnova за {current_year}."', html)
        self.assertNotIn(CURRENT_YEAR_TOKEN, html)

    def test_projects_category_page_uses_fallback_seo_and_default_h1_when_fields_are_empty(self):
        response = self.client.get(reverse("projects:projects_category_list", kwargs={"slug": self.museums.slug}))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("<title>Museums | Проекты | CultNova</title>", html)
        self.assertIn('<meta name="description" content="Проекты Cultnova в категории «Museums»." />', html)
        self.assertNotIn('<meta name="keywords"', html)
        self.assertIn('<meta name="robots" content="index,follow" />', html)
        self.assertIn(build_public_project_category_path(self.museums.slug), html)
        self.assertIn(">Проекты</h1>", html)

    def test_projects_root_page_keeps_default_seo_values(self):
        response = self.client.get(reverse("projects:projects_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("<title>Реализованные проекты компании «CultNova»</title>", html)
        self.assertIn(
            '<meta name="description" content="Портфолио реализованных проектов: комплексное проектирование музеев, оформление выставок и интеграция передовых мультимедийных решений в культурных объектах🏛." />',
            html,
        )
        self.assertNotIn('<meta name="keywords"', html)
        self.assertIn('<meta name="robots" content="index,follow" />', html)
        self.assertIn(">Проекты</h1>", html)

    def test_projects_root_page_ignores_current_year_token_from_category_seo(self):
        self.museums.page_h1 = f"Кейсы {CURRENT_YEAR_TOKEN}"
        self.museums.seo_title = f"Музейные проекты {CURRENT_YEAR_TOKEN}"
        self.museums.seo_description = f"Подборка музейных проектов Cultnova за {CURRENT_YEAR_TOKEN}."
        self.museums.save(
            update_fields=[
                "page_h1",
                "seo_title",
                "seo_description",
            ]
        )

        response = self.client.get(reverse("projects:projects_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn("<title>Реализованные проекты компании «CultNova»</title>", html)
        self.assertIn(
            '<meta name="description" content="Портфолио реализованных проектов: комплексное проектирование музеев, оформление выставок и интеграция передовых мультимедийных решений в культурных объектах🏛." />',
            html,
        )
        self.assertIn(">Проекты</h1>", html)

    def test_projects_root_page_uses_single_combined_stylesheet(self):
        response = self.client.get(reverse("projects:projects_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('/css/projects.css?v=2026-04-08-3', html)
        self.assertNotIn("/css/simple-page.css", html)
        self.assertEqual(html.count('rel="stylesheet"'), 1)

    def test_projects_root_page_uses_responsive_hero_assets_and_deferred_scripts(self):
        response = self.client.get(reverse("projects:projects_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        self.assertIn('/images/projects/projects-mobile-640.webp', html)
        self.assertIn('/images/projects/projects-mobile-1200.webp', html)
        self.assertIn('/images/projects/projects-768.webp', html)
        self.assertIn('/images/projects/projects-1170.webp', html)
        self.assertIn('/images/projects/projects-1600.webp', html)
        self.assertIn('class="projects__hero-picture"', html)
        self.assertNotIn('href="https://example.com/delta.jpg"', html)
        self.assertIn('<script src="/js/script.js" defer></script>', html)
        self.assertIn('<script src="/vendor/htmx/htmx.min.js?v=2.0.4" defer></script>', html)
        self.assertIn('<script src="/js/projects-listing.js?v=2026-04-16-1" defer></script>', html)
        self.assertIn("requestIdleCallback", html)
        self.assertIn("https://mc.yandex.ru/metrika/tag.js", html)

    def test_projects_root_page_includes_rich_collection_schema(self):
        response = self.client.get(reverse("projects:projects_list"))

        self.assertEqual(response.status_code, 200)
        html = response.content.decode("utf-8")
        base_url = settings.SITE_PUBLIC_BASE_URL.rstrip("/")

        self.assertIn('<script type="application/ld+json">', html)
        self.assertIn('"@type": ["WebPage", "CollectionPage"]', html)
        self.assertIn('"@type": "BreadcrumbList"', html)
        self.assertIn('"@type": "ItemList"', html)
        self.assertIn(f'"@id": "{base_url}/projects/#webpage"', html)
        self.assertIn(f'"@id": "{base_url}/projects/#breadcrumbs"', html)
        self.assertIn(f'"@id": "{base_url}/projects/#item-list"', html)
        self.assertIn(f'"url": "{base_url}/projects/"', html)
        self.assertIn(f'"url": "{base_url}/"', html)
        self.assertNotIn("ItemListOrderDescending", html)

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

        with self.assertNumQueries(4):
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

    def test_multi_category_payload_is_ordered_and_keeps_legacy_aliases(self):
        self.category.sort_order = 20
        self.category.save(update_fields=["sort_order"])
        second_category = ProjectCategories.objects.create(
            title="Education",
            slug="education-api",
            sort_order=10,
        )
        self.project.categories.add(second_category)

        with self.assertNumQueries(4):
            response = self.client.get(reverse("projects:get_all_projects"))

        self.assertEqual(response.status_code, 200)
        item = response.json()["data"][0]
        self.assertEqual(
            item["categories"],
            [
                {
                    "id": second_category.pk,
                    "title": second_category.title,
                    "slug": second_category.slug,
                    "sort_order": 10,
                },
                {
                    "id": self.category.pk,
                    "title": self.category.title,
                    "slug": self.category.slug,
                    "sort_order": 20,
                },
            ],
        )
        self.assertEqual(item["category_title"], second_category.title)
        self.assertEqual(item["category"], item["categories"][0])

        for category in (self.category, second_category):
            category_response = self.client.get(
                reverse("projects:get_projects_by_category_explicit", kwargs={"slug": category.slug})
            )
            matching_slugs = [entry["slug"] for entry in category_response.json()["data"]]
            self.assertEqual(matching_slugs.count(self.project.slug), 1)

    def test_categories_endpoint_uses_global_order_and_includes_sort_order(self):
        self.category.sort_order = None
        self.category.save(update_fields=["sort_order"])
        first = ProjectCategories.objects.create(title="Zulu", slug="zulu-api", sort_order=1)
        second = ProjectCategories.objects.create(title="Alpha", slug="alpha-api", sort_order=2)

        response = self.client.get(reverse("projects:get_all_categories"))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual([item["slug"] for item in payload], [first.slug, second.slug, self.category.slug])
        self.assertEqual([item["sort_order"] for item in payload], [1, 2, None])

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

        with self.assertNumQueries(4):
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

    def test_all_projects_endpoint_paginates_in_sort_order_with_empty_values_last(self):
        second_visible = Projects.objects.create(
            title="Second Visible",
            slug="second-visible-project",
            category=self.category,
            sort_order=2,
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
            sort_order=1,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        fourth_visible = Projects.objects.create(
            title="Fourth Visible",
            slug="fourth-visible-project",
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
        Projects.objects.filter(pk=third_visible.pk).update(created_at=now - timedelta(minutes=4))
        Projects.objects.filter(pk=fourth_visible.pk).update(created_at=now - timedelta(minutes=1))

        response_page_1 = self.client.get(reverse("projects:get_all_projects"), {"limit": 3, "page": 1})

        self.assertEqual(response_page_1.status_code, 200)
        payload_page_1 = response_page_1.json()
        self.assertEqual(payload_page_1["current_page"], 1)
        self.assertTrue(payload_page_1["has_next"])
        self.assertEqual(payload_page_1["next_page"], 2)
        self.assertEqual(len(payload_page_1["data"]), 3)
        self.assertEqual(
            [entry["slug"] for entry in payload_page_1["data"]],
            [third_visible.slug, second_visible.slug, fourth_visible.slug],
        )

        response_page_2 = self.client.get(reverse("projects:get_all_projects"), {"limit": 3, "page": 2})

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

    def test_projects_by_category_orders_by_sort_order_with_empty_values_last(self):
        first_sorted = Projects.objects.create(
            title="Category First",
            slug="category-first",
            category=self.category,
            sort_order=1,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        second_unsorted = Projects.objects.create(
            title="Category Second",
            slug="category-second",
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
        Projects.objects.filter(pk=self.project.pk).update(created_at=now - timedelta(minutes=2))
        Projects.objects.filter(pk=first_sorted.pk).update(created_at=now - timedelta(minutes=3))
        Projects.objects.filter(pk=second_unsorted.pk).update(created_at=now - timedelta(minutes=1))

        response = self.client.get(f"/api/projects/category/{self.category.slug}/")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(
            [item["slug"] for item in payload["data"]],
            [first_sorted.slug, second_unsorted.slug, self.project.slug],
        )

    def test_explicit_category_endpoint_matches_legacy_category_payload(self):
        legacy_response = self.client.get(f"/api/projects/{self.category.slug}")
        explicit_response = self.client.get(f"/api/projects/category/{self.category.slug}/")

        self.assertEqual(explicit_response.status_code, 200)
        self.assertEqual(legacy_response.json(), explicit_response.json())

    def test_service_page_projects_endpoint_returns_selected_visible_projects_in_slot_order(self):
        second_visible = Projects.objects.create(
            title="Second Visible",
            slug="second-visible-service-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        noindex_project = Projects.objects.create(
            title="Noindex",
            slug="noindex-service-project",
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
        ProjectsContentBlock.objects.create(
            project=second_visible,
            type=ProjectsContentBlock.IMAGE,
            order=1,
            media="https://example.com/second-visible.jpg",
            media_alt="Second visible alt",
        )
        service_page = ServicePageProjects.objects.get(slug="musium")
        service_page.project_1 = second_visible
        service_page.project_2 = self.hidden_project
        service_page.project_3 = self.project
        service_page.save()

        ServicePageProjects.objects.filter(pk=service_page.pk).update(project_2=noindex_project)

        response = self.client.get(reverse("projects:get_service_page_projects", kwargs={"slug": "musium"}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["slug"], "musium")
        self.assertEqual(payload["title"], "Музеи и интерактивные пространства")
        self.assertEqual([item["slug"] for item in payload["data"]], [second_visible.slug, self.project.slug])
        self.assertEqual(
            payload["data"][0]["images"],
            [{"url": "https://example.com/second-visible.jpg", "alt": "Second visible alt"}],
        )
        self.assertEqual(payload["data"][1]["images"], [{"url": "https://example.com/image.jpg", "alt": "Alt"}])

    def test_service_page_projects_endpoint_allows_empty_slots(self):
        response = self.client.get(reverse("projects:get_service_page_projects", kwargs={"slug": "content"}))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload["slug"], "content")
        self.assertEqual(payload["data"], [])


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
        self.assertEqual(payload["categories"][0]["id"], self.category.pk)
        self.assertEqual(payload["category"], payload["categories"][0])
        self.assertEqual(payload["category_title"], self.category.title)

    def test_project_html_detail_route_available(self):
        response = self.client.get(f"/projects/{self.project.slug}/")

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.project.title)


class ServicePageProjectsModelTests(TestCase):
    def test_default_service_pages_are_created_and_ordered_by_menu(self):
        expected_slugs = [slug for slug, _title in ServicePageProjects.SERVICE_PAGE_CHOICES]

        self.assertEqual(list(ServicePageProjects.objects.values_list("slug", flat=True)), expected_slugs)

    def test_ensure_default_pages_restores_missing_static_page(self):
        ServicePageProjects.objects.filter(slug="service").delete()

        ServicePageProjects.ensure_default_pages()

        self.assertTrue(ServicePageProjects.objects.filter(slug="service").exists())
        self.assertEqual(
            list(ServicePageProjects.objects.values_list("slug", flat=True)),
            [slug for slug, _title in ServicePageProjects.SERVICE_PAGE_CHOICES],
        )


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


class ProjectCategoryAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="category-admin",
            email="category-admin@example.com",
            password="password123",
        )
        self.category = ProjectCategories.objects.create(title="Museums", slug="museums")

    def test_category_admin_change_page_contains_seo_fields_and_previews(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:projects_projectcategories_change", args=[self.category.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="page_h1"')
        self.assertContains(response, 'name="seo_title"')
        self.assertContains(response, 'name="seo_description"')
        self.assertContains(response, 'name="seo_keywords"')
        self.assertContains(response, 'name="seo_robots"')
        self.assertContains(response, 'name="canonical_url"')
        self.assertContains(response, "Public URL")
        self.assertContains(response, "SEO snippet preview")
        self.assertContains(response, "Переменная года")
        self.assertContains(response, CURRENT_YEAR_TOKEN)
        self.assertContains(response, "Текущий год считается по Москве.")

    def test_category_admin_preview_resolves_current_year_token(self):
        current_year = get_project_category_current_year()
        self.category.seo_title = f"Проекты музеев {CURRENT_YEAR_TOKEN}"
        self.category.seo_description = f"Категория проектов за {CURRENT_YEAR_TOKEN}."
        self.category.save(update_fields=["seo_title", "seo_description"])

        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:projects_projectcategories_change", args=[self.category.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"Проекты музеев {current_year}")
        self.assertContains(response, f"Категория проектов за {current_year}.")

    def test_category_admin_form_allows_blank_seo_fields(self):
        from projects.admin import ProjectCategoriesAdminForm

        form = ProjectCategoriesAdminForm(
            data={
                "title": "Education",
                "slug": "education",
                "page_h1": "",
                "seo_title": "",
                "seo_description": "",
                "seo_keywords": "",
                "seo_robots": "",
                "canonical_url": "",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.page_h1, "")
        self.assertEqual(category.seo_title, "")
        self.assertEqual(category.seo_description, "")
        self.assertEqual(category.seo_keywords, "")
        self.assertEqual(category.seo_robots, "index,follow")
        self.assertEqual(category.canonical_url, "")

    def test_category_admin_form_trims_seo_fields(self):
        from projects.admin import ProjectCategoriesAdminForm

        form = ProjectCategoriesAdminForm(
            data={
                "title": "Architecture",
                "slug": "architecture",
                "page_h1": "  Архитектурные кейсы  ",
                "seo_title": "  Архитектурные проекты  ",
                "seo_description": "  Описание категории  ",
                "seo_keywords": "  архитектура, проекты  ",
                "seo_robots": "  noindex,nofollow  ",
                "canonical_url": " https://example.com/projects/category/architecture/ ",
            }
        )

        self.assertTrue(form.is_valid(), form.errors)
        category = form.save()
        self.assertEqual(category.page_h1, "Архитектурные кейсы")
        self.assertEqual(category.seo_title, "Архитектурные проекты")
        self.assertEqual(category.seo_description, "Описание категории")
        self.assertEqual(category.seo_keywords, "архитектура, проекты")
        self.assertEqual(category.seo_robots, "noindex,nofollow")
        self.assertEqual(category.canonical_url, "https://example.com/projects/category/architecture/")

    def test_category_admin_exposes_editable_global_sort_order(self):
        model_admin = admin.site._registry[ProjectCategories]

        self.assertIn("sort_order", model_admin.list_display)
        self.assertIn("sort_order", model_admin.list_editable)


class ProjectsAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="projects-admin",
            email="projects-admin@example.com",
            password="password123",
        )
        self.category = ProjectCategories.objects.create(title="Museums", slug="museums-project-admin")
        self.project = Projects.objects.create(
            title="Admin Project",
            slug="admin-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )

    def test_projects_admin_change_page_contains_sort_order_field(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:projects_projects_change", args=[self.project.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="sort_order"')

    def test_projects_admin_form_saves_sort_order_and_allows_blank(self):
        from projects.admin import ProjectsAdminForm

        second_category = ProjectCategories.objects.create(
            title="Education",
            slug="education-project-admin",
            sort_order=1,
        )

        numbered_form = ProjectsAdminForm(
            data={
                "title": "Sorted project",
                "slug": "sorted-project",
                "categories": [self.category.pk, second_category.pk],
                "sort_order": "7",
                "customer_name": "Client",
                "year": "2025",
                "type": "Type",
                "body_html": "<p>Body</p>",
                "excerpt": "Excerpt",
                "preview_image": "",
                "preview_image_alt": "",
                "seo_title": "SEO title",
                "seo_description": "SEO description",
                "seo_keywords": "",
                "seo_robots": "index,follow",
                "canonical_url": "",
                "is_published": "on",
            }
        )

        self.assertTrue(numbered_form.is_valid(), numbered_form.errors)
        numbered_project = numbered_form.save()
        self.assertEqual(numbered_project.sort_order, 7)
        self.assertEqual(
            list(numbered_project.categories.values_list("pk", flat=True)),
            [second_category.pk, self.category.pk],
        )

        blank_form = ProjectsAdminForm(
            data={
                "title": "Unsorted project",
                "slug": "unsorted-project",
                "categories": [self.category.pk],
                "sort_order": "",
                "customer_name": "Client",
                "year": "2025",
                "type": "Type",
                "body_html": "<p>Body</p>",
                "excerpt": "Excerpt",
                "preview_image": "",
                "preview_image_alt": "",
                "seo_title": "SEO title",
                "seo_description": "SEO description",
                "seo_keywords": "",
                "seo_robots": "index,follow",
                "canonical_url": "",
                "is_published": "",
            }
        )

        self.assertTrue(blank_form.is_valid(), blank_form.errors)
        blank_project = blank_form.save()
        self.assertIsNone(blank_project.sort_order)

    def test_projects_admin_form_requires_at_least_one_category(self):
        from projects.admin import ProjectsAdminForm

        form = ProjectsAdminForm(
            data={
                "title": "No category",
                "slug": "no-category",
                "categories": [],
                "customer_name": "Client",
                "year": "2025",
                "type": "Type",
                "body_html": "<p>Body</p>",
                "seo_title": "SEO title",
                "seo_description": "SEO description",
                "seo_robots": "index,follow",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("categories", form.errors)

    def test_admin_uses_multiple_category_autocomplete_and_displays_all_categories(self):
        second_category = ProjectCategories.objects.create(
            title="Education",
            slug="education-admin-display",
            sort_order=1,
        )
        self.project.categories.add(second_category)
        request = RequestFactory().get(reverse("admin:projects_projects_changelist"))
        request.user = self.user
        model_admin = admin.site._registry[Projects]
        project = model_admin.get_queryset(request).get(pk=self.project.pk)

        self.assertEqual(model_admin.autocomplete_fields, ("categories",))
        self.assertEqual(model_admin.categories_display(project), "Education · Museums")
        self.assertIn("categories", model_admin.list_filter)

    def test_projects_admin_changelist_orders_by_sort_order_with_empty_values_last(self):
        projects = []
        for title, slug, sort_order in (
            ("Admin First", "admin-first", 1),
            ("Admin Second", "admin-second", 2),
            ("Admin Unsorted", "admin-unsorted", None),
        ):
            projects.append(
                Projects.objects.create(
                    title=title,
                    slug=slug,
                    category=self.category,
                    sort_order=sort_order,
                    customer_name="Client",
                    year=2025,
                    type="Type",
                    body_html="<p>Body</p>",
                    seo_title="SEO",
                    seo_description="SEO",
                    is_published=True,
                )
            )

        request = RequestFactory().get(reverse("admin:projects_projects_changelist"))
        request.user = self.user
        model_admin = admin.site._registry[Projects]
        titles = list(
            model_admin.get_queryset(request)
            .filter(pk__in=[project.pk for project in projects])
            .values_list("title", flat=True)
        )

        self.assertEqual(titles, ["Admin First", "Admin Second", "Admin Unsorted"])


class ProjectCategoryDeleteGuardTests(TestCase):
    def setUp(self):
        self.first = ProjectCategories.objects.create(title="First", slug="first")
        self.second = ProjectCategories.objects.create(title="Second", slug="second")
        self.third = ProjectCategories.objects.create(title="Third", slug="third")
        self.project = Projects.objects.create(
            title="Guarded Project",
            slug="guarded-project",
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
        )
        self.project.categories.add(self.first)

    def test_individual_delete_is_blocked_if_project_would_have_no_categories(self):
        with self.assertRaises(ProtectedError):
            self.first.delete()

        self.assertTrue(ProjectCategories.objects.filter(pk=self.first.pk).exists())

    def test_delete_succeeds_when_project_keeps_another_category(self):
        self.project.categories.add(self.second)

        self.first.delete()

        self.assertEqual(list(self.project.categories.values_list("pk", flat=True)), [self.second.pk])

    def test_bulk_delete_checks_the_entire_deleted_set(self):
        self.project.categories.set([self.second, self.third])

        with self.assertRaises(ProtectedError):
            ProjectCategories.objects.filter(pk__in=[self.second.pk, self.third.pk]).delete()

        self.assertEqual(self.project.categories.count(), 2)

    def test_admin_delete_preview_marks_orphaned_project_as_protected(self):
        request = RequestFactory().get(reverse("admin:projects_projectcategories_delete", args=[self.first.pk]))
        request.user = get_user_model().objects.create_superuser(
            username="category-delete-admin",
            email="category-delete-admin@example.com",
            password="password123",
        )
        model_admin = admin.site._registry[ProjectCategories]

        _deleted, _counts, _permissions, protected = model_admin.get_deleted_objects(
            [self.first],
            request,
        )

        self.assertIn(f"Проект: {self.project}", protected)

class ServicePageProjectsAdminTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="service-page-admin",
            email="service-page-admin@example.com",
            password="password123",
        )
        self.category = ProjectCategories.objects.create(title="Museums", slug="museums-admin")
        self.project = Projects.objects.create(
            title="Admin Project",
            slug="admin-service-page-project",
            category=self.category,
            customer_name="Client",
            year=2025,
            type="Type",
            body_html="<p>Body</p>",
            seo_title="SEO",
            seo_description="SEO",
            is_published=True,
        )
        self.service_page = ServicePageProjects.objects.get(slug="service")

    def test_service_page_projects_admin_change_page_contains_three_project_slots(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:projects_servicepageprojects_change", args=[self.service_page.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Техническое сопровождение и обслуживание")
        self.assertContains(response, 'name="project_1"')
        self.assertContains(response, 'name="project_2"')
        self.assertContains(response, 'name="project_3"')
        self.assertNotContains(response, 'name="_delete"')

    def test_service_page_projects_admin_changelist_restores_static_pages(self):
        ServicePageProjects.objects.filter(slug="service").delete()

        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:projects_servicepageprojects_changelist"))

        self.assertEqual(response.status_code, 200)
        self.assertTrue(ServicePageProjects.objects.filter(slug="service").exists())
        self.assertContains(response, "Техническое сопровождение и обслуживание")

    def test_service_page_projects_admin_disables_add_view(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("admin:projects_servicepageprojects_add"))

        self.assertEqual(response.status_code, 403)

    def test_service_page_projects_admin_form_rejects_duplicate_projects(self):
        from projects.admin import ServicePageProjectsAdminForm

        form = ServicePageProjectsAdminForm(
            instance=self.service_page,
            data={
                "slug": self.service_page.slug,
                "project_1": self.project.pk,
                "project_2": self.project.pk,
                "project_3": "",
            },
        )

        self.assertFalse(form.is_valid())
        self.assertIn("Один и тот же проект нельзя выбрать", str(form.errors))


class ProjectStaticGenerationSignalTests(TestCase):
    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_category_reorder_rebuilds_detail_and_listing_labels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                first = ProjectCategories.objects.create(title="First", slug="first-reorder", sort_order=1)
                second = ProjectCategories.objects.create(title="Second", slug="second-reorder", sort_order=2)
                with self.captureOnCommitCallbacks(execute=True):
                    project = Projects.objects.create(
                        title="Reordered Project",
                        slug="reordered-project",
                        category=first,
                        customer_name="Client",
                        year=2025,
                        type="Type",
                        body_html="<p>Body</p>",
                        seo_title="SEO",
                        seo_description="SEO",
                        is_published=True,
                    )
                    project.categories.add(second)

                root = Path(temp_dir)
                detail_path = root / "projects" / project.slug / "index.html"
                listing_path = root / "projects" / "index.html"
                self.assertIn("First · Second", detail_path.read_text(encoding="utf-8"))

                with self.captureOnCommitCallbacks(execute=True):
                    first.sort_order = 3
                    first.save(update_fields=["sort_order"])

                self.assertIn("Second · First", detail_path.read_text(encoding="utf-8"))
                self.assertIn("Second · First", listing_path.read_text(encoding="utf-8"))

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_m2m_add_updates_timestamp_detail_both_listings_and_sitemap(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                first = ProjectCategories.objects.create(title="First", slug="first-signal", sort_order=2)
                second = ProjectCategories.objects.create(title="Second", slug="second-signal", sort_order=1)
                with self.captureOnCommitCallbacks(execute=True):
                    project = Projects.objects.create(
                        title="Multi Signal Project",
                        slug="multi-signal-project",
                        category=first,
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

                with self.captureOnCommitCallbacks(execute=True):
                    project.categories.add(second)

                project.refresh_from_db()
                root = Path(temp_dir)
                detail_html = (root / "projects" / project.slug / "index.html").read_text(encoding="utf-8")
                sitemap = (root / "sitemap.xml").read_text(encoding="utf-8")

                self.assertGreater(project.updated_at, older_timestamp)
                self.assertIn("Second · First", detail_html)
                self.assertIn(
                    project.title,
                    (root / "projects" / "category" / first.slug / "index.html").read_text(encoding="utf-8"),
                )
                self.assertIn(
                    project.title,
                    (root / "projects" / "category" / second.slug / "index.html").read_text(encoding="utf-8"),
                )
                self.assertIn(f"/projects/{project.slug}/", sitemap)

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
                generated_html = target.read_text(encoding="utf-8")
                self.assertIn('data-page="project"', generated_html)
                self.assertIn('/vendor/photoswipe/photoswipe.css', generated_html)
                self.assertIn('/css/lightbox.css?v=2026-04-17-1', generated_html)
                self.assertIn('/vendor/photoswipe/photoswipe.umd.min.js', generated_html)
                self.assertIn('/vendor/photoswipe/photoswipe-lightbox.umd.min.js', generated_html)
                self.assertIn('/js/lightbox.js?v=2026-04-17-1', generated_html)
                listing_html = listing_target.read_text(encoding="utf-8")
                self.assertIn('data-page="projects"', listing_html)
                self.assertNotIn("ItemListOrderDescending", listing_html)
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
    def test_category_seo_change_rebuilds_generated_category_page(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                with self.captureOnCommitCallbacks(execute=True):
                    category = ProjectCategories.objects.create(title="Cat", slug="cat")

                category_target = Path(temp_dir) / "projects" / "category" / category.slug / "index.html"
                self.assertIn("<title>Cat | Проекты | CultNova</title>", category_target.read_text(encoding="utf-8"))

                with self.captureOnCommitCallbacks(execute=True):
                    category.page_h1 = "Кейсы категории"
                    category.seo_title = "Категория SEO"
                    category.seo_description = "SEO описание категории."
                    category.seo_keywords = "seo, category"
                    category.seo_robots = "noindex,nofollow"
                    category.canonical_url = "https://example.com/custom-category/"
                    category.save(
                        update_fields=[
                            "page_h1",
                            "seo_title",
                            "seo_description",
                            "seo_keywords",
                            "seo_robots",
                            "canonical_url",
                        ]
                    )

                updated_html = category_target.read_text(encoding="utf-8")
                self.assertIn("<title>Категория SEO | CultNova</title>", updated_html)
                self.assertIn('content="SEO описание категории."', updated_html)
                self.assertIn('content="seo, category"', updated_html)
                self.assertIn('content="noindex,nofollow"', updated_html)
                self.assertIn('href="https://example.com/custom-category/"', updated_html)
                self.assertIn(">Кейсы категории</h1>", updated_html)

    @override_settings(SITE_PUBLIC_BASE_URL="https://example.com")
    def test_category_current_year_token_is_resolved_in_generated_html(self):
        current_year = get_project_category_current_year()
        with tempfile.TemporaryDirectory() as temp_dir:
            with override_settings(GENERATED_HTML_PAGES_PATH=temp_dir):
                with self.captureOnCommitCallbacks(execute=True):
                    category = ProjectCategories.objects.create(
                        title="Cat",
                        slug="cat",
                        page_h1=f"Кейсы {CURRENT_YEAR_TOKEN}",
                        seo_title=f"Категория {CURRENT_YEAR_TOKEN}",
                        seo_description=f"SEO описание {CURRENT_YEAR_TOKEN}.",
                        seo_keywords=f"seo, {CURRENT_YEAR_TOKEN}",
                    )

                category_target = Path(temp_dir) / "projects" / "category" / category.slug / "index.html"
                html = category_target.read_text(encoding="utf-8")

                self.assertIn(f"<title>Категория {current_year} | CultNova</title>", html)
                self.assertIn(f'content="SEO описание {current_year}."', html)
                self.assertIn(f'content="seo, {current_year}"', html)
                self.assertIn(f">Кейсы {current_year}</h1>", html)
                self.assertNotIn(CURRENT_YEAR_TOKEN, html)

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
                    project.categories.set([new_category])

                self.assertNotIn("Moved Project", old_category_page.read_text(encoding="utf-8"))
                self.assertIn("Moved Project", new_category_page.read_text(encoding="utf-8"))
