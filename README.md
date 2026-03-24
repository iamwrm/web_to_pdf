# web_to_pdf

Turn a saved HTML page into an A4 PDF with minimal modification.

The pipeline:
1. Render the HTML in headless Chromium
2. Keep the original layout as much as possible
3. Apply only light print CSS to reduce bad page breaks for images/code/math
4. Export directly to PDF

## Local usage

Requirements:
- `uv`
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

Useful options:

```bash
uv run build_pdf.py --html input.html --output out.pdf
uv run build_pdf.py --html input.html --media print
uv run build_pdf.py --html input.html --hide-selector '[role="banner"]'
```

## GitHub Actions

This repo includes a workflow that builds `input.html` and uploads the resulting PDF as a direct-upload artifact (`actions/upload-artifact@v7` with `archive: false`).

That lets GitHub expose the uploaded PDF file directly, and the workflow adds an `Open PDF` link to the job summary.
