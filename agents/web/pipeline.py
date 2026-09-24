"""Bounded provider-neutral website generation pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import re


MAX_PAGES = 8
MAX_SOURCE_CHARS = 8000
MAX_PAGE_CONTENT_CHARS = 12000
MAX_TOTAL_OUTPUT_CHARS = 80000

_PAGE_TEMPLATES = (
    ("home", "ホーム"),
    ("about", "概要"),
    ("services", "サービス"),
    ("contact", "お問い合わせ"),
)
_SLUG_PATTERN = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True)
class WebPage:
    slug: str
    title: str
    purpose: str

    def __post_init__(self) -> None:
        if not self.slug or not _SLUG_PATTERN.fullmatch(self.slug):
            raise ValueError("invalid page slug")
        if not self.title.strip() or len(self.title) > 120:
            raise ValueError("invalid page title")
        if not self.purpose.strip() or len(self.purpose) > 300:
            raise ValueError("invalid page purpose")


@dataclass(frozen=True)
class WebSitePlan:
    title: str
    source_summary: str
    pages: tuple[WebPage, ...]

    def __post_init__(self) -> None:
        if not self.title.strip() or len(self.title) > 160:
            raise ValueError("invalid site title")
        if not self.source_summary.strip() or len(self.source_summary) > MAX_SOURCE_CHARS:
            raise ValueError("source summary exceeds bound")
        if not 1 <= len(self.pages) <= MAX_PAGES:
            raise ValueError("page count exceeds bound")


@dataclass(frozen=True)
class WebGeneratedFile:
    path: str
    content: str

    def __post_init__(self) -> None:
        if not self.path.strip() or self.path.startswith("/"):
            raise ValueError("invalid generated file path")
        if len(self.content) > MAX_PAGE_CONTENT_CHARS:
            raise ValueError("generated file exceeds content bound")


@dataclass(frozen=True)
class WebGenerationBundle:
    files: tuple[WebGeneratedFile, ...]

    def __post_init__(self) -> None:
        if not self.files:
            raise ValueError("generation produced no files")
        if sum(len(item.content) for item in self.files) > MAX_TOTAL_OUTPUT_CHARS:
            raise ValueError("total generated output exceeds bound")


class WebProductionPipeline:
    """Generate a static, local-only website bundle without external providers."""

    def plan(self, source: str, *, title: str | None = None, page_count: int | None = None) -> WebSitePlan:
        text = str(source or "").strip()
        if not text:
            raise ValueError("source is required")
        if len(text) > MAX_SOURCE_CHARS:
            raise ValueError("source exceeds maximum length")

        lowered = text.casefold()
        if page_count is None:
            page_count = 1 if any(term in lowered for term in ("lp", "ランディングページ", "1ページ")) else 3
        if not 1 <= page_count <= MAX_PAGES:
            raise ValueError("page_count must be between 1 and 8")

        site_title = (title or _derive_title(text)).strip()[:160] or "AI Website"
        templates = _PAGE_TEMPLATES[:page_count]
        pages = tuple(
            WebPage(slug=slug, title=label, purpose=purpose)
            for (slug, label), purpose in zip(
                templates,
                (
                    "訪問者にサイトの目的と主要メッセージを伝える",
                    "サービスやプロジェクトの背景・特徴を説明する",
                    "提供内容と利用メリットを整理する",
                    "問い合わせ・次のアクションを案内する",
                ),
            )
        )
        if page_count > len(templates):
            extra = tuple(
                WebPage(
                    slug=f"page-{index}",
                    title=f"ページ {index}",
                    purpose="追加情報を整理して提示する",
                )
                for index in range(len(templates) + 1, page_count + 1)
            )
            pages += extra
        return WebSitePlan(site_title, text, pages)

    def generate(self, plan: WebSitePlan) -> WebGenerationBundle:
        css = _css()
        js = _js()
        files = [
            WebGeneratedFile("styles.css", css),
            WebGeneratedFile("script.js", js),
        ]
        for page in plan.pages:
            files.append(
                WebGeneratedFile(
                    f"{page.slug}.html",
                    _html(plan, page),
                )
            )
        return WebGenerationBundle(tuple(files))


def build_initial_site_plan(source: str, *, title: str | None = None, page_count: int | None = None) -> WebSitePlan:
    return WebProductionPipeline().plan(source, title=title, page_count=page_count)


def _derive_title(source: str) -> str:
    compact = " ".join(source.split())
    for marker in ("。", "!", "！", "?", "？"):
        if marker in compact:
            compact = compact.split(marker, 1)[0]
            break
    return compact[:80] or "AI Website"


def _html(plan: WebSitePlan, page: WebPage) -> str:
    body = escape(plan.source_summary[:1800])
    nav = " ".join(
        f'<a href="{escape(other.slug)}.html">{escape(other.title)}</a>'
        for other in plan.pages
    )
    return (
        "<!doctype html>\n"
        '<html lang="ja">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{escape(plan.title)} - {escape(page.title)}</title>\n"
        '<link rel="stylesheet" href="styles.css">\n'
        "</head>\n<body>\n"
        "<header>\n"
        f"<nav aria-label="Main">{nav}</nav>\n"
        "</header>\n"
        "<main>\n"
        f"<p class="eyebrow">{escape(page.purpose)}</p>\n"
        f"<h1>{escape(page.title)}</h1>\n"
        f"<p>{body}</p>\n"
        '<a class="cta" href="contact.html">お問い合わせ</a>\n'
        "</main>\n"
        "<footer>\n"
        f"<small>{escape(plan.title)}</small>\n"
        "</footer>\n"
        '<script src="script.js"></script>\n'
        "</body>\n</html>\n"
    )


def _css() -> str:
    return """* { box-sizing: border-box; }
:root { font-family: system-ui, -apple-system, sans-serif; color: #172033; background: #f7f8fb; }
body { margin: 0; min-height: 100vh; line-height: 1.7; }
header, footer { max-width: 1100px; margin: 0 auto; padding: 1rem 1.5rem; }
nav { display: flex; flex-wrap: wrap; gap: 1rem; }
nav a { text-decoration: none; color: inherit; }
main { max-width: 900px; margin: 10vh auto; padding: 0 1.5rem; }
.eyebrow { font-size: .9rem; opacity: .7; }
h1 { font-size: clamp(2rem, 7vw, 4.5rem); line-height: 1.1; margin: .2em 0; }
.cta { display: inline-block; margin-top: 1rem; padding: .8rem 1.1rem; border-radius: .6rem; text-decoration: none; border: 1px solid currentColor; }
footer { margin-top: 4rem; opacity: .7; }
@media (max-width: 640px) { nav { gap: .6rem; } main { margin-top: 6vh; } }
"""


def _js() -> str:
    return """document.documentElement.dataset.js = "ready";
"""
