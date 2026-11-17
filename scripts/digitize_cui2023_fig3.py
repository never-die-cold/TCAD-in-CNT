"""Digitize Cui 2023 Figure 3 from the PDF vector content.

The project must not rely on hand-typed numbers.  Figure 3 of Cui et al.,
*Electronics* 12 (2023) 1000 is drawn as vector graphics, so marker centres,
axis tick labels and error-bar caps can be read back from the PDF content
stream in device-independent points.  This script:

1. locates the three plot frames and verifies each frame edge exists;
2. calibrates axes from the typeset tick labels (linear least squares);
3. converts filled square markers into (dose, value) pairs;
4. converts error-bar caps into an asymmetric uncertainty interval;
5. writes a long-format CSV plus an audit JSON and a visual overlay.

The script fails loudly instead of guessing: if a frame edge, a tick label or
a dose point is missing, it raises rather than emitting a partial curve.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

DOSE_UNIT = "krad(Si)"
VDS_V = -0.1
SOURCE = "Cui2023"
DEVICE_ID = "cui2023_cnt_network_p"
PAPER = "Ding et al., Electronics 2023, 12, 1000"
FIGURE = "Figure 3"
DOSE_GRID = (0.0, 200.0, 500.0, 1000.0, 2000.0, 3000.0)

MINUS_SIGN = chr(8722)
MULTIPLY_SIGN = chr(215)
NUM = re.compile("^-?[0-9]+(?:[.][0-9]+)?$")
SCI = re.compile(
    "^(-?[0-9]+(?:[.][0-9]+)?)[ ]*[" + MULTIPLY_SIGN + "x][ ]*10[ ]*(-?[0-9]+)$"
)


@dataclass(frozen=True)
class Panel:
    """One sub-plot of Figure 3.

    frame is (x0, y0, x1, y1) in PDF points with the origin at the top left,
    measured directly from the stroke that outlines the axes box.
    """

    key: str
    panel: str
    page: int
    frame: tuple[float, float, float, float]
    unit: str


PANELS = (
    Panel("vth_v", "a", 4, (214.7, 555.0, 417.0, 718.7), "V"),
    Panel("gm_max_s", "b", 5, (215.4, 100.3, 417.7, 264.0), "S"),
    Panel("ss_mv_dec", "c", 5, (215.4, 314.0, 417.7, 477.7), "mV/dec"),
)


def parse_label(text: str) -> float | None:
    """Parse a tick label such as -1.2 or 1.1x10-5."""

    cleaned = text.strip().replace(MINUS_SIGN, "-")
    match = SCI.match(cleaned)
    if match:
        return float(match.group(1)) * 10.0 ** int(match.group(2))
    if NUM.match(cleaned):
        return float(cleaned)
    return None


def affine(pairs: list[tuple[float, float]]) -> tuple[float, float, float]:
    """Least-squares y = a * x + b with an explicit failure on degeneracy."""

    if len(pairs) < 2:
        raise ValueError(f"need at least two calibration points, got {len(pairs)}")
    x = np.array([item[0] for item in pairs], dtype=float)
    y = np.array([item[1] for item in pairs], dtype=float)
    if np.ptp(x) <= 0:
        raise ValueError("degenerate calibration axis")
    slope, intercept = np.polyfit(x, y, 1)
    residual = float(np.max(np.abs(slope * x + intercept - y)))
    return float(slope), float(intercept), residual


def pdf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _check_frame(drawings, frame) -> None:
    """Every panel must be bounded by four long strokes we can find again."""

    x0, y0, x1, y1 = frame
    horizontal = 0
    vertical = 0
    for drawing in drawings:
        rect = drawing["rect"]
        if rect.height < 1.0 and abs(rect.x0 - x0) < 1.5 and abs(rect.x1 - x1) < 1.5:
            horizontal += int(abs(rect.y0 - y0) < 1.5 or abs(rect.y0 - y1) < 1.5)
        if rect.width < 1.0 and abs(rect.y0 - y0) < 1.5 and abs(rect.y1 - y1) < 1.5:
            vertical += int(abs(rect.x0 - x0) < 1.5 or abs(rect.x0 - x1) < 1.5)
    if horizontal < 2 or vertical < 2:
        raise RuntimeError(
            f"axis frame {frame} not found (h={horizontal}, v={vertical}); "
            "the PDF layout changed, re-measure the frame before trusting output"
        )


def digitize_panel(page, panel: Panel) -> dict:
    """Return calibrated markers, uncertainties and calibration diagnostics."""

    drawings = page.get_drawings()
    _check_frame(drawings, panel.frame)
    x0, y0, x1, y1 = panel.frame

    y_labels: list[tuple[float, float, str]] = []
    x_labels: list[tuple[float, float, str]] = []
    for wx0, wy0, wx1, wy1, text, *_ in page.get_text("words"):
        value = parse_label(text)
        if value is None:
            continue
        centre_y = (wy0 + wy1) / 2.0
        centre_x = (wx0 + wx1) / 2.0
        if wx1 <= x0 - 0.5 and y0 - 12.0 <= centre_y <= y1 + 12.0:
            y_labels.append((centre_y, value, text))
        # Only the tick-label row directly under the frame; this excludes the
        # axis title and the next panel's labels.
        if y1 + 0.5 <= wy0 <= y1 + 25.0 and x0 - 12.0 <= centre_x <= x1 + 12.0:
            x_labels.append((centre_x, value, text))
    if not y_labels or not x_labels:
        raise RuntimeError(f"panel {panel.key}: tick labels not found")

    y_slope, y_intercept, y_residual = affine([(pos, val) for pos, val, _ in y_labels])
    x_slope, x_intercept, x_residual = affine([(pos, val) for pos, val, _ in x_labels])
    if y_residual > 0.002 * max(abs(yl[1]) for yl in y_labels) or x_residual > 2.0:
        raise RuntimeError(
            f"panel {panel.key}: calibration residual too large "
            f"(y={y_residual:.4g}, x={x_residual:.4g})"
        )

    # The legend key is a filled square followed by the text "VDS = -0.1V".
    # Locate that text so the key is not mistaken for a data point.
    legend: list[tuple[float, float]] = []
    for wx0, wy0, wx1, wy1, text, *_ in page.get_text("words"):
        if text == "VDS" and x0 <= (wx0 + wx1) / 2.0 <= x1 and y0 <= (wy0 + wy1) / 2.0 <= y1:
            legend.append((wx0, (wy0 + wy1) / 2.0))

    markers: list[tuple[float, float]] = []
    caps: list[tuple[float, float]] = []
    for drawing in drawings:
        rect = drawing["rect"]
        centre_x = (rect.x0 + rect.x1) / 2.0
        centre_y = (rect.y0 + rect.y1) / 2.0
        if not (x0 - 1.0 <= centre_x <= x1 + 1.0 and y0 - 1.0 <= centre_y <= y1 + 1.0):
            continue
        if drawing["type"] == "f" and 3.0 < rect.width < 8.0 and 3.0 < rect.height < 8.0:
            is_legend_key = any(
                4.0 < text_x - centre_x < 30.0 and abs(text_y - centre_y) < 6.0
                for text_x, text_y in legend
            )
            if not is_legend_key:
                markers.append((centre_x, centre_y))
        if drawing["type"] == "s" and rect.height < 0.8 and 2.0 < rect.width < 8.0:
            caps.append((centre_x, centre_y))

    points = []
    for centre_x, centre_y in markers:
        dose = x_slope * centre_x + x_intercept
        value = y_slope * centre_y + y_intercept
        nearest = min(DOSE_GRID, key=lambda reference: abs(reference - dose))
        if abs(nearest - dose) > 20.0:
            continue  # legend key or decorative marker
        points.append((nearest, value, centre_x, centre_y))
    points.sort()
    doses = [round(point[0], 3) for point in points]
    if sorted(doses) != list(DOSE_GRID):
        raise RuntimeError(f"panel {panel.key}: expected doses {DOSE_GRID}, got {doses}")

    rows = []
    span = max(abs(point[1]) for point in points) * 0.25
    for dose, value, centre_x, centre_y in points:
        nearby = [
            y_slope * cap_y + y_intercept
            for cap_x, cap_y in caps
            if abs(cap_x - centre_x) < 0.6
            and abs(y_slope * cap_y + y_intercept - value) < span
        ]
        low = min(nearby) if nearby else value
        high = max(nearby) if nearby else value
        rows.append(
            {
                "dose_value": dose,
                "value": value,
                "err_minus": value - low,
                "err_plus": high - value,
                "pdf_x": centre_x,
                "pdf_y": centre_y,
            }
        )
    return {
        "rows": rows,
        "calibration": {
            "x_slope_krad_per_pt": x_slope,
            "x_intercept_krad": x_intercept,
            "x_max_residual_krad": x_residual,
            "y_slope_per_pt": y_slope,
            "y_intercept": y_intercept,
            "y_max_residual": y_residual,
            "n_y_labels": len(y_labels),
            "n_x_labels": len(x_labels),
        },
    }


def draw_overlay(pdf_path: Path, results: dict, output: Path) -> None:
    """Render the source panel with digitized points marked, for eyeball audit."""

    import pymupdf
    from PIL import Image, ImageDraw

    doc = pymupdf.open(pdf_path)
    tiles = []
    for panel in PANELS:
        page = doc[panel.page - 1]
        x0, y0, x1, y1 = panel.frame
        clip = pymupdf.Rect(x0 - 45, y0 - 12, x1 + 12, y1 + 40)
        zoom = 3.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        draw = ImageDraw.Draw(image)
        for row in results[panel.key]["rows"]:
            px = (row["pdf_x"] - clip.x0) * zoom
            py = (row["pdf_y"] - clip.y0) * zoom
            draw.line((px - 6, py, px + 6, py), fill=(220, 0, 0), width=1)
            draw.line((px, py - 6, px, py + 6), fill=(220, 0, 0), width=1)
            draw.text((px + 7, py - 12), f"{row['value']:.4g}", fill=(180, 0, 0))
        tiles.append(image)
    width = max(tile.width for tile in tiles)
    height = sum(tile.height for tile in tiles)
    combined = Image.new("RGB", (width, height), "white")
    offset = 0
    for tile in tiles:
        combined.paste(tile, (0, offset))
        offset += tile.height
    output.parent.mkdir(parents=True, exist_ok=True)
    combined.save(output)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pdf", type=Path, default=Path("reference/literature/electronics-12-01000.pdf")
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/literature/cui2023_topgate/fig3_metrics_digitized.csv"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/literature/cui2023_topgate/fig3_digitization_report.json"),
    )
    parser.add_argument("--overlay", type=Path, default=Path("results/literature/fig3_overlay.png"))
    args = parser.parse_args(argv)

    import pymupdf

    doc = pymupdf.open(args.pdf)
    results = {}
    rows = []
    for panel in PANELS:
        page = doc[panel.page - 1]
        results[panel.key] = digitize_panel(page, panel)
        for row in results[panel.key]["rows"]:
            rows.append(
                {
                    "source": SOURCE,
                    "device_id": DEVICE_ID,
                    "polarity": "p",
                    "dose_value": f"{row['dose_value']:g}",
                    "dose_unit": DOSE_UNIT,
                    "vds_signed_v": f"{VDS_V:g}",
                    "metric": panel.key,
                    "value": f"{row['value']:.6g}",
                    "unit": panel.unit,
                    "err_minus": f"{row['err_minus']:.3g}",
                    "err_plus": f"{row['err_plus']:.3g}",
                    "figure": FIGURE,
                    "panel": panel.panel,
                    "page": str(panel.page),
                    "pdf_x_pt": f"{row['pdf_x']:.2f}",
                    "pdf_y_pt": f"{row['pdf_y']:.2f}",
                    "extraction_method": f"pdf_vectors:PyMuPDF-{pymupdf.__version__}",
                    "quality": "machine_extracted_pending_review",
                }
            )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0].keys())
    body = "".join(",".join(row[column] for column in columns) + chr(10) for row in rows)
    args.output.write_text(",".join(columns) + chr(10) + body, encoding="utf-8")
    report = {
        "schema_version": "1.0",
        "paper": PAPER,
        "pdf": str(args.pdf),
        "pdf_sha256": pdf_sha256(args.pdf),
        "pymupdf_version": pymupdf.__version__,
        "dose_grid_krad_si": list(DOSE_GRID),
        "panels": {panel.key: results[panel.key]["calibration"] for panel in PANELS},
        "note": "Values are read from vector markers, not typed by hand; "
        "the overlay image is the human audit artifact.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + chr(10), encoding="utf-8")
    draw_overlay(args.pdf, results, args.overlay)

    print(f"CSV: {args.output} ({len(rows)} rows)")
    print(f"Report: {args.report}")
    print(f"Overlay: {args.overlay}")
    for panel in PANELS:
        values = [row["value"] for row in results[panel.key]["rows"]]
        print(f"  {panel.key:10s} " + "  ".join(f"{value:.6g}" for value in values))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
