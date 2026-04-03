from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.services.frontend_partials_sync import sync_frontend_partials


class Command(BaseCommand):
    help = "Sync shared frontend partials into backend templates/partials."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Fail when the configured frontend partial source is unavailable.",
        )

    def handle(self, *args, **options):
        try:
            result = sync_frontend_partials(
                backend_base_dir=settings.BASE_DIR,
                frontend_repo_path=getattr(settings, "FRONTEND_REPO_PATH", ""),
                frontend_export_dir=getattr(settings, "FRONTEND_PARTIALS_EXPORT_DIR", ""),
                strict=options["strict"],
            )
        except FileNotFoundError as error:
            raise CommandError(str(error)) from error

        if result is None:
            self.stdout.write(
                self.style.WARNING(
                    "Frontend partial sync skipped: configure FRONTEND_REPO_PATH or FRONTEND_PARTIALS_EXPORT_DIR."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                "Synced frontend partials from {kind}: written={written}; unchanged={unchanged}; root={root}".format(
                    kind=result.source_kind,
                    written=len(result.written_files),
                    unchanged=len(result.unchanged_files),
                    root=result.source_root,
                )
            )
        )
