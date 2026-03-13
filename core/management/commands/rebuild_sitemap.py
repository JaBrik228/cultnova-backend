from django.core.management.base import BaseCommand

from core.services.sitemap import build_sitemap


class Command(BaseCommand):
    help = "Rebuild sitemap.xml from generated public HTML pages."

    def handle(self, *args, **options):
        result = build_sitemap()
        self.stdout.write(
            self.style.SUCCESS(
                "Output: {path}; URLs: {urls}; skipped noindex: {skipped}".format(
                    path=result.output_path,
                    urls=result.url_count,
                    skipped=result.skipped_noindex_count,
                )
            )
        )
