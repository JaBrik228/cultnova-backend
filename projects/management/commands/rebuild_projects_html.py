from django.core.management.base import BaseCommand

from core.services.build_item_html import build_item_detail_static_html, delete_item_detail_static_html
from projects.models import Projects
from projects.services.project_listing import rebuild_projects_listing_static_html


class Command(BaseCommand):
    help = "Rebuild static HTML pages for projects."

    def add_arguments(self, parser):
        parser.add_argument(
            "--delete-unpublished",
            action="store_true",
            help="Delete generated pages for unpublished projects.",
        )

    def handle(self, *args, **options):
        published_projects = Projects.objects.filter(is_published=True).order_by("slug")

        rebuilt = 0
        for project in published_projects:
            build_item_detail_static_html(project, "project_detail.html", "projects")
            rebuilt += 1

        listing_pages = rebuild_projects_listing_static_html(prune_stale=True)

        deleted = 0
        if options["delete_unpublished"]:
            unpublished_projects = Projects.objects.filter(is_published=False).order_by("slug")
            for project in unpublished_projects:
                delete_item_detail_static_html(project, "projects")
                deleted += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Rebuilt detail pages: {rebuilt}, rebuilt listing pages: {len(listing_pages)}, deleted: {deleted}"
            )
        )
