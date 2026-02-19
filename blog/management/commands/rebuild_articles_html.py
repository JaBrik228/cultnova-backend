from django.core.management.base import BaseCommand

from blog.models import Articles
from core.services.build_item_html import build_item_detail_static_html, delete_item_detail_static_html


class Command(BaseCommand):
    help = "Rebuild static HTML pages for blog articles."

    def add_arguments(self, parser):
        parser.add_argument(
            '--delete-unpublished',
            action='store_true',
            help='Delete generated pages for unpublished articles.',
        )

    def handle(self, *args, **options):
        published_articles = Articles.objects.filter(is_published=True).order_by('slug')

        rebuilt = 0
        for article in published_articles:
            build_item_detail_static_html(article, 'article_detail.html', 'articles')
            rebuilt += 1

        deleted = 0
        if options['delete_unpublished']:
            unpublished_articles = Articles.objects.filter(is_published=False).order_by('slug')
            for article in unpublished_articles:
                delete_item_detail_static_html(article, 'articles')
                deleted += 1

        self.stdout.write(self.style.SUCCESS(f"Rebuilt: {rebuilt}, deleted: {deleted}"))
