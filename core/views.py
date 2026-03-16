import logging
import xml.etree.ElementTree as ET

from django.conf import settings
from django.http import Http404, HttpResponseServerError
from django.shortcuts import render

from core.services.html_sitemap import SitemapXmlMissingError, build_html_sitemap

logger = logging.getLogger(__name__)


def sitemap_page(request):
    try:
        sections = build_html_sitemap()
    except SitemapXmlMissingError as exc:
        logger.warning("Sitemap page requested before sitemap.xml existed: %s", exc)
        raise Http404("Sitemap page is unavailable.") from exc
    except ET.ParseError:
        logger.exception("Failed to parse sitemap.xml for sitemap page")
        return HttpResponseServerError("Failed to render sitemap page.")

    return render(
        request,
        "sitemap_page.html",
        {
            "sections": sections,
            "canonical_url": f"{settings.SITE_PUBLIC_BASE_URL.rstrip('/')}{request.path}",
        },
    )
