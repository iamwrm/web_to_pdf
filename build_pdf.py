#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy>=2.0.0",
#   "pillow>=11.0.0",
#   "playwright>=1.52.0",
# ]
# ///

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

import numpy as np
from PIL import Image
from playwright.sync_api import sync_playwright


DEFAULT_MARGIN_MM = 5.0
DEFAULT_SEARCH_BAND = 300
DEFAULT_VIEWPORT_WIDTH = 800
DEFAULT_DEVICE_SCALE_FACTOR = 1.0
PRINTABLE_A4_WIDTH_MM = 210.0
PRINTABLE_A4_HEIGHT_MM = 297.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render a saved HTML page to an A4 PDF by screenshotting the main content column, slicing it at safe cut points, and compiling with Typst.",
    )
    parser.add_argument("--html", required=True, type=Path, help="Input HTML file")
    parser.add_argument("--output", type=Path, help="Output PDF path (default: <html stem>.pdf)")
    parser.add_argument("--artifacts-dir", type=Path, help="Directory for intermediate files (default: .build_pdf/<html stem>)")
    parser.add_argument("--browser", type=str, help="Browser executable path (default: auto-detect chromium/google-chrome)")
    parser.add_argument("--typst", type=str, default="typst", help="Typst executable")
    parser.add_argument("--margin-mm", type=float, default=DEFAULT_MARGIN_MM, help="Page margin in mm (default: 5)")
    parser.add_argument("--search-band", type=int, default=DEFAULT_SEARCH_BAND, help="Search ±N pixels around each target cut (default: 300)")
    parser.add_argument("--viewport-width", type=int, default=DEFAULT_VIEWPORT_WIDTH, help="Browser viewport width before clipping (default: 800)")
    parser.add_argument("--device-scale-factor", type=float, default=DEFAULT_DEVICE_SCALE_FACTOR, help="Browser device scale factor (default: 1.0)")
    parser.add_argument("--keep-artifacts", action="store_true", help="Keep intermediate files")
    return parser.parse_args()


def fail(message: str) -> "never":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def check_file(path: Path) -> Path:
    path = path.resolve()
    if not path.exists():
        fail(f"input HTML not found: {path}")
    if not path.is_file():
        fail(f"input path is not a file: {path}")
    return path


def resolve_browser(user_value: str | None) -> str | None:
    if user_value:
        browser_path = Path(user_value).expanduser().resolve()
        if not browser_path.exists():
            fail(f"browser executable not found: {browser_path}")
        return str(browser_path)

    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        found = shutil.which(name)
        if found:
            return found
    return None


def require_executable(name: str) -> str:
    found = shutil.which(name)
    if not found:
        fail(f"required executable not found on PATH: {name}")
    return found


def file_url(path: Path) -> str:
    return f"file://{quote(str(path))}"


def html_to_long_screenshot(
    html_path: Path,
    screenshot_path: Path,
    browser_path: str | None,
    viewport_width: int,
    device_scale_factor: float,
) -> tuple[int, int]:
    screenshot_path.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        launch_kwargs = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-setuid-sandbox", "--disable-gpu"],
        }
        if browser_path:
            launch_kwargs["executable_path"] = browser_path

        browser = p.chromium.launch(**launch_kwargs)
        page = browser.new_page(
            viewport={"width": viewport_width, "height": 600},
            device_scale_factor=device_scale_factor,
        )
        page.goto(file_url(html_path), wait_until="networkidle", timeout=30_000)
        page.wait_for_timeout(750)

        found_primary_column = page.evaluate(
            """
            () => {
              for (const sel of [
                '[data-testid="sidebarColumn"]',
                '[role="banner"]',
                '[data-testid="BottomBar"]',
                '[data-testid="logged_out_read_replies_pivot"]',
              ]) {
                document.querySelector(sel)?.remove();
              }

              document.querySelectorAll('*').forEach((el) => {
                const s = getComputedStyle(el);
                if (s.position === 'fixed' || s.position === 'sticky') {
                  el.style.position = 'relative';
                }
              });

              const appBar = document.querySelector('[data-testid="app-bar-back"]');
              if (appBar) {
                let el = appBar;
                for (let i = 0; i < 10; i++) {
                  el = el.parentElement;
                  if (!el) break;
                  if (el.offsetHeight < 60 && el.offsetWidth > 400) {
                    el.style.display = 'none';
                    break;
                  }
                }
              }

              const pill = document.querySelector('[data-testid="pillLabel"]');
              if (pill) {
                let el = pill;
                for (let i = 0; i < 5; i++) {
                  el = el.parentElement;
                  if (!el) break;
                }
                if (el) el.style.display = 'none';
              }

              const primaryColumn = document.querySelector('[data-testid="primaryColumn"]');
              if (!primaryColumn) {
                return false;
              }

              primaryColumn.style.maxWidth = '100%';
              primaryColumn.style.width = '100%';
              primaryColumn.style.borderLeft = 'none';
              primaryColumn.style.borderRight = 'none';

              document.body.style.margin = '0';
              document.body.style.padding = '0';
              document.documentElement.style.overflow = 'visible';
              return true;
            }
            """
        )

        if not found_primary_column:
            browser.close()
            fail("could not find [data-testid=\"primaryColumn\"] in the HTML")

        page.locator('[data-testid="primaryColumn"]').screenshot(
            path=str(screenshot_path),
            animations="disabled",
        )
        browser.close()

    with Image.open(screenshot_path) as image:
        return image.size


def compute_target_height_px(image_width_px: int, margin_mm: float) -> int:
    printable_width_mm = PRINTABLE_A4_WIDTH_MM - 2 * margin_mm
    printable_height_mm = PRINTABLE_A4_HEIGHT_MM - 2 * margin_mm
    if printable_width_mm <= 0 or printable_height_mm <= 0:
        fail("margin is too large for A4")
    pixels_per_mm = image_width_px / printable_width_mm
    return max(1, int(round(printable_height_mm * pixels_per_mm)))


def row_scores(rgb_array: np.ndarray) -> np.ndarray:
    gray = rgb_array[..., :3].mean(axis=2).astype(np.float32)
    row_mean = gray.mean(axis=1)
    row_std = gray.std(axis=1)
    return row_std + (255.0 - row_mean)


def find_cut_positions(height: int, target_height: int, scores: np.ndarray, search_band: int) -> list[int]:
    cuts = [0]
    min_slice_height = max(200, target_height // 3)
    current = 0

    while current + target_height < height:
        target = current + target_height
        lo = max(current + min_slice_height, target - search_band)
        hi = min(height, target + 1)

        if lo >= hi:
            cut = min(height, target)
        else:
            window = scores[lo:hi]
            cut = lo + int(np.argmin(window))

        if cut <= current:
            cut = min(height, target)
        cuts.append(cut)
        current = cut

    if cuts[-1] != height:
        cuts.append(height)
    return cuts


def slice_image(long_png: Path, slices_dir: Path, margin_mm: float, search_band: int) -> list[Path]:
    if slices_dir.exists():
        shutil.rmtree(slices_dir)
    slices_dir.mkdir(parents=True, exist_ok=True)

    with Image.open(long_png) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        arr = np.array(rgb)

        target_height = compute_target_height_px(width, margin_mm)
        scores = row_scores(arr)
        cuts = find_cut_positions(height, target_height, scores, search_band)

        slice_paths: list[Path] = []
        for index, (y0, y1) in enumerate(zip(cuts, cuts[1:])):
            out_path = slices_dir / f"slice_{index:02d}.png"
            rgb.crop((0, y0, width, y1)).save(out_path)
            slice_paths.append(out_path)

    return slice_paths


def write_typst(typst_path: Path, slice_paths: Iterable[Path], margin_mm: float, artifacts_dir: Path) -> None:
    slice_paths = list(slice_paths)
    lines = [
        "#set page(",
        '  paper: "a4",',
        f"  margin: (top: {margin_mm}mm, bottom: {margin_mm}mm, left: {margin_mm}mm, right: {margin_mm}mm),",
        ")",
        "#set par(leading: 0pt, spacing: 0pt)",
        "",
    ]

    for index, path in enumerate(slice_paths):
        rel_path = path.relative_to(artifacts_dir)
        lines.append(f'#image("{rel_path.as_posix()}", width: 100%)')
        if index < len(slice_paths) - 1:
            lines.append("#pagebreak()")

    typst_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def compile_typst(typst_exe: str, typst_path: Path, output_pdf: Path) -> None:
    cmd = [typst_exe, "compile", str(typst_path), str(output_pdf)]
    subprocess.run(cmd, check=True, cwd=typst_path.parent)


def main() -> None:
    args = parse_args()
    html_path = check_file(args.html)

    output_pdf = (args.output or html_path.with_suffix(".pdf")).resolve()
    artifacts_dir = (args.artifacts_dir or (html_path.parent / ".build_pdf" / html_path.stem)).resolve()
    long_png = artifacts_dir / "long_screenshot.png"
    slices_dir = artifacts_dir / "slices"
    typst_path = artifacts_dir / "article.typ"

    browser_path = resolve_browser(args.browser)
    require_executable(args.typst)
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    started = time.time()

    print(f"[1/4] render HTML: {html_path}")
    if browser_path:
        print(f"      browser: {browser_path}")
    else:
        print("      browser: playwright-managed chromium")
    width, height = html_to_long_screenshot(
        html_path=html_path,
        screenshot_path=long_png,
        browser_path=browser_path,
        viewport_width=args.viewport_width,
        device_scale_factor=args.device_scale_factor,
    )
    print(f"      screenshot: {long_png} ({width}x{height})")

    print("[2/4] slice into A4-safe page images")
    target_height = compute_target_height_px(width, args.margin_mm)
    print(f"      target slice height: ~{target_height}px")
    slice_paths = slice_image(long_png, slices_dir, args.margin_mm, args.search_band)
    print(f"      slices: {len(slice_paths)} -> {slices_dir}")

    print(f"[3/4] write Typst source: {typst_path}")
    write_typst(typst_path, slice_paths, args.margin_mm, artifacts_dir)

    print(f"[4/4] compile PDF: {output_pdf}")
    compile_typst(args.typst, typst_path, output_pdf)

    elapsed = time.time() - started
    print(f"done in {elapsed:.1f}s")
    print(f"pdf: {output_pdf}")
    if args.keep_artifacts:
        print(f"artifacts: {artifacts_dir}")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        fail(f"command failed with exit code {exc.returncode}: {' '.join(map(str, exc.cmd))}")
