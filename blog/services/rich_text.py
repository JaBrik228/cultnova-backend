import re
from html.parser import HTMLParser

import nh3
from django.utils.html import escape


ALLOWED_TAGS = {
    "p",
    "br",
    "strong",
    "em",
    "u",
    "s",
    "blockquote",
    "ul",
    "ol",
    "li",
    "a",
    "hr",
    "h2",
    "h3",
    "h4",
    "table",
    "thead",
    "tbody",
    "tfoot",
    "tr",
    "th",
    "td",
    "caption",
    "colgroup",
    "col",
    "figure",
    "img",
    "figcaption",
}

ALLOWED_ATTRIBUTES = {
    "a": {"href", "title", "target"},
    "img": {"src", "alt", "loading", "decoding"},
    "th": {"colspan", "rowspan", "scope"},
    "td": {"colspan", "rowspan", "scope"},
    "col": {"span"},
}

ALLOWED_CLASSES = {"p": {"article__lead"}}
ALLOWED_URL_SCHEMES = {"http", "https", "mailto"}
BLOCK_LEVEL_TAGS = {
    "p",
    "blockquote",
    "ul",
    "ol",
    "table",
    "figure",
    "hr",
    "h1",
    "h2",
    "h3",
    "h4",
}
HTML_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
H1_RE = re.compile(r"<\s*h1(?:\s|>)", re.IGNORECASE)


def looks_like_html_fragment(value: str) -> bool:
    return bool(value and HTML_TAG_RE.search(value))


def normalize_legacy_text_to_html(value: str) -> str:
    normalized = (value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return ""

    paragraphs = []
    for chunk in re.split(r"\n\s*\n+", normalized):
        lines = [escape(line.strip()) for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue
        paragraphs.append(f"<p>{'<br>'.join(lines)}</p>")

    return "".join(paragraphs)


class _LeadStructureParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.top_level_blocks = []
        self.lead_count = 0
        self.has_h1 = False

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        is_top_level = self.depth == 0 and tag in BLOCK_LEVEL_TAGS

        if tag == "h1":
            self.has_h1 = True

        if is_top_level:
            classes = {
                class_name.strip()
                for class_name in (attrs_dict.get("class") or "").split()
                if class_name.strip()
            }
            is_lead = tag == "p" and "article__lead" in classes
            self.top_level_blocks.append((tag, is_lead))
            if is_lead:
                self.lead_count += 1

        self.depth += 1

    def handle_startendtag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "h1":
            self.has_h1 = True
        if tag in BLOCK_LEVEL_TAGS:
            classes = {
                class_name.strip()
                for class_name in (attrs_dict.get("class") or "").split()
                if class_name.strip()
            }
            is_lead = tag == "p" and "article__lead" in classes
            self.top_level_blocks.append((tag, is_lead))
            if is_lead:
                self.lead_count += 1

    def handle_endtag(self, tag):
        if self.depth > 0:
            self.depth -= 1


def validate_lead_block_structure(value: str) -> None:
    parser = _LeadStructureParser()
    parser.feed(value or "")
    parser.close()

    if parser.has_h1:
        raise ValueError("H1 is not allowed inside article body.")

    if parser.lead_count > 1:
        raise ValueError("Only one lead paragraph is allowed in article body.")

    if parser.lead_count == 1:
        first_tag, is_lead = parser.top_level_blocks[0] if parser.top_level_blocks else (None, False)
        if first_tag != "p" or not is_lead:
            raise ValueError("Lead paragraph must be the first content block in article body.")


def sanitize_article_body_html(value: str) -> str:
    raw_value = (value or "").strip()
    if not raw_value:
        return ""

    html_value = raw_value if looks_like_html_fragment(raw_value) else normalize_legacy_text_to_html(raw_value)

    cleaned = nh3.clean(
        html_value,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        allowed_classes=ALLOWED_CLASSES,
        url_schemes=ALLOWED_URL_SCHEMES,
        clean_content_tags={"script", "style"},
        set_tag_attribute_values={"img": {"loading": "lazy", "decoding": "async"}},
        link_rel="noopener noreferrer",
        strip_comments=True,
    )

    return cleaned.strip()


def build_inline_image_html(url: str, alt: str, caption: str = "") -> str:
    image_html = (
        f'<figure><img src="{escape(url)}" alt="{escape(alt)}" loading="lazy" decoding="async" />'
    )
    if caption.strip():
        image_html += f"<figcaption>{escape(caption.strip())}</figcaption>"
    image_html += "</figure>"
    return sanitize_article_body_html(image_html)
