from django.core.management.base import BaseCommand

from core.services.sitemap import build_public_sitemaps


class Command(BaseCommand):
    help = "Rebuild sitemap.xml from generated public HTML pages."

    def handle(self, *args, **options):
        result = build_public_sitemaps()
        self.stdout.write(
            self.style.SUCCESS(
                "XML: {xml_path}; HTML: {html_path}; URLs: {urls}; sections: {sections}; skipped noindex: {skipped}".format(
                    xml_path=result.xml_result.output_path,
                    html_path=result.html_result.output_path,
                    urls=result.xml_result.url_count,
                    sections=result.html_result.section_count,
                    skipped=result.xml_result.skipped_noindex_count,
                )
            )
        )
