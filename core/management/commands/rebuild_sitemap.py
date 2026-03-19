from django.core.management.base import BaseCommand

from core.services.html_sitemap import build_static_html_sitemap_page
from core.services.sitemap import build_sitemap


class Command(BaseCommand):
    help = "Rebuild sitemap.xml from generated public HTML pages."

    def handle(self, *args, **options):
        result = build_sitemap()
        html_result = build_static_html_sitemap_page()
        self.stdout.write(
            self.style.SUCCESS(
                "XML: {xml_path}; HTML: {html_path}; URLs: {urls}; sections: {sections}; skipped noindex: {skipped}".format(
                    xml_path=result.output_path,
                    html_path=html_result.output_path,
                    urls=result.url_count,
                    sections=html_result.section_count,
                    skipped=result.skipped_noindex_count,
                )
            )
        )
