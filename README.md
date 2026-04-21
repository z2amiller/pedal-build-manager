# Pedal Build Manager

A server-rendered web app for guided pedal assembly. Displays interactive PCB board views alongside synchronized Bill of Materials (BOM) panels, helping builders place components correctly.

## Stack

- **FastAPI** — Python web framework
- **Jinja2** — server-side HTML templating
- **HTMX** — dynamic updates without a JS framework
- Vanilla JS modules for SVG interactivity

## Installation

```bash
pip install -e ".[dev]"
```

## Running the Dev Server

```bash
uvicorn app.main:app --reload
```

Then open http://127.0.0.1:8000 in your browser.

## Routes

- `GET /` — index page listing available boards
- `GET /board/{slug}/{version}` — two-panel board view (BOM left, SVG right)

## Notes

- The manifest loader (reads `.manifest.zip` files produced by the KiCad plugin) is implemented in a later ticket.
- `kicad-pedal-common` will be added as a dependency once it is available as a pip package.
