#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "playwright>=1.52.0",
# ]
# ///

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import NoReturn
from urllib.parse import quote

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


DEFAULT_MARGIN_MM = 12.0
DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 900
DEFAULT_WAIT_MS = 1000


def fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render an HTML file in headless Chromium and export it to PDF with minimal modification.",
    )
    parser.add_argument("--html", required=True, type=Path, help="Input HTML file")
    parser.add_argument("--output", type=Path, help="Output PDF path (default: <html stem>.pdf)")
    parser.add_argument("--browser", type=str, help="Browser executable path (default: auto-detect chromium/google-chrome)")
    parser.add_argument("--margin-mm", type=float, default=DEFAULT_MARGIN_MM, help="A4 page margin in mm (default: 12)")
    parser.add_argument("--viewport-width", type=int, default=DEFAULT_VIEWPORT_WIDTH, help="Viewport width in CSS px before printing")
    parser.add_argument("--viewport-height", type=int, default=DEFAULT_VIEWPORT_HEIGHT, help="Viewport height in CSS px before printing")
    parser.add_argument("--scale", type=float, default=1.0, help="PDF scale factor for Chromium page.pdf (default: 1.0)")
    parser.add_argument("--wait-ms", type=int, default=DEFAULT_WAIT_MS, help="Extra wait after load, in ms (default: 1000)")
    parser.add_argument(
        "--media",
        choices=("screen", "print"),
        default="screen",
        help="CSS media to emulate before printing (default: screen)",
    )
    parser.add_argument(
        "--hide-selector",
        action="append",
        default=[],
        help="CSS selector to remove before printing; may be passed multiple times",
    )
    return parser.parse_args()


def resolve_input(path: Path) -> Path:
    path = path.expanduser().resolve()
    if not path.exists():
        fail(f"input HTML not found: {path}")
    if not path.is_file():
        fail(f"input path is not a file: {path}")
    return path


def resolve_browser(user_value: str | None) -> str | None:
    if user_value:
        browser = Path(user_value).expanduser().resolve()
        if not browser.exists():
            fail(f"browser executable not found: {browser}")
        return str(browser)

    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return None


def file_url(path: Path) -> str:
    return f"file://{quote(str(path))}"


def injected_css() -> str:
    return """
html {
  -webkit-print-color-adjust: exact !important;
  print-color-adjust: exact !important;
}

img,
svg,
canvas,
video,
iframe,
figure,
table,
pre,
blockquote,
math,
mjx-container,
.katex,
.MathJax,
.highlight,
.codehilite {
  break-inside: avoid-page !important;
  page-break-inside: avoid !important;
  max-width: 100% !important;
}

h1, h2, h3, h4, h5, h6 {
  break-after: avoid-page;
  page-break-after: avoid;
}

pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

p, li {
  orphans: 3;
  widows: 3;
}
"""


def apply_minimal_changes(page, selectors: list[str]) -> None:
    page.add_style_tag(content=injected_css())
    if selectors:
        page.evaluate(
            """
            (selectors) => {
              for (const selector of selectors) {
                document.querySelectorAll(selector).forEach((el) => el.remove());
              }
            }
            """,
            selectors,
        )


def render_pdf(
    html_path: Path,
    output_path: Path,
    browser_path: str | None,
    margin_mm: float,
    viewport_width: int,
    viewport_height: int,
    scale: float,
    wait_ms: int,
    media: str,
    hide_selectors: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        launch_kwargs = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
        }
        if browser_path:
            launch_kwargs["executable_path"] = browser_path

        try:
            browser = p.chromium.launch(**launch_kwargs)
        except PlaywrightError as exc:
            fail(
                "failed to launch Chromium. Install a browser with "
                "`python -m playwright install chromium` or pass --browser /path/to/chromium. "
                f"Details: {exc}"
            )

        page = browser.new_page(viewport={"width": viewport_width, "height": viewport_height})
        page.goto(file_url(html_path), wait_until="networkidle", timeout=60_000)
        if wait_ms > 0:
            page.wait_for_timeout(wait_ms)

        page.emulate_media(media=media)
        apply_minimal_changes(page, hide_selectors)

        page.pdf(
            path=str(output_path),
            format="A4",
            print_background=True,
            prefer_css_page_size=False,
            margin={
                "top": f"{margin_mm}mm",
                "right": f"{margin_mm}mm",
                "bottom": f"{margin_mm}mm",
                "left": f"{margin_mm}mm",
            },
            scale=scale,
        )
        browser.close()


def main() -> None:
    args = parse_args()
    html_path = resolve_input(args.html)
    output_path = (args.output or html_path.with_suffix(".pdf")).expanduser().resolve()
    browser_path = resolve_browser(args.browser)

    print(f"html:   {html_path}")
    print(f"output: {output_path}")
    if browser_path:
        print(f"browser: {browser_path}")
    else:
        print("browser: playwright-managed chromium")

    render_pdf(
        html_path=html_path,
        output_path=output_path,
        browser_path=browser_path,
        margin_mm=args.margin_mm,
        viewport_width=args.viewport_width,
        viewport_height=args.viewport_height,
        scale=args.scale,
        wait_ms=args.wait_ms,
        media=args.media,
        hide_selectors=args.hide_selector,
    )

    print("done")


if __name__ == "__main__":
    main()
