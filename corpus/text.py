import re

from bs4 import BeautifulSoup, Comment, NavigableString


NOISE = (
    "script, style, noscript, .toc, .mw-editsection, .navbox, .vertical-navbox, "
    ".hatnote, .noprint, sup.reference, .reflist, .references, .mw-references-wrap"
)
BLOCKS = {
    "p", "div", "section", "article", "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "dl", "dt", "dd", "blockquote", "figure", "figcaption",
    "table", "caption", "tr", "pre",
}


def extract_document(html):
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("#mw-content-text .mw-parser-output")
    if content is None:
        content = soup.select_one(".mw-parser-output")
    if content is None:
        raise ValueError("Не найден основной блок статьи")

    heading = soup.select_one("#firstHeading")
    if heading is None:
        heading = soup.title
    title = " ".join(heading.get_text().split()) if heading else ""

    for element in content.select(NOISE):
        if element.parent is not None:
            element.decompose()

    def render(node):
        if isinstance(node, Comment):
            return ""
        if isinstance(node, NavigableString):
            return re.sub(r"\s+", " ", str(node))
        if node.name == "br":
            return "\n"
        value = "".join(render(child) for child in node.children)
        if node.name in BLOCKS:
            return "\n" + value + "\n"
        if node.name in {"td", "th"}:
            return value + " "
        return value

    lines = [" ".join(line.split()) for line in render(content).splitlines()]
    text = "\n".join(line for line in lines if line)
    if not text:
        raise ValueError("Основной блок статьи не содержит текста")
    return title, text
