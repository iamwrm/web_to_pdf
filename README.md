# web_to_pdf

Turn a saved HTML page into a print-friendly A4 PDF.

The pipeline:
1. Render the HTML in headless Chromium
2. Remove the left/right panels and login/banner UI
3. Capture the main content column as one long screenshot
4. Slice it at low-variance rows to avoid cutting through images/code blocks/math
5. Compile the slices into an A4 PDF with Typst

## Local usage

Requirements:
- `uv`
- `typst`
- Chromium/Chrome, or Playwright-installed Chromium

Run:

```bash
uv run build_pdf.py --html input.html
```

Or:

```bash
./build_pdf.py --html input.html
```

Output:
- default PDF: `input.pdf`
- intermediate files: `.build_pdf/input/`

## GitHub Actions

This repo includes a workflow that builds `input.html` and uploads the resulting PDF as an artifact.
