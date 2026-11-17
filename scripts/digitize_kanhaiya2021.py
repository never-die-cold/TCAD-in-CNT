"""Digitize Figure 3e and Figure 4 of Kanhaiya et al. (ACS Nano 2021).

The ACS Nano figures are exported as vector art: axes and curves are filled
paths, not text or bitmaps.  That makes the published curves recoverable
exactly, without hand reading:

* axis calibration comes from the tick marks (small filled rectangles) that sit
  on the inside of the frame edges, so no OCR of the numerals is needed;
* every data curve is one filled outline polygon; the centreline is the midpoint
  between the upper and lower boundary at each x, which is the plotted curve;
* error bars are separate shapes and are therefore excluded from the centreline.

The script asserts the expected number of ticks and curves, so a change in the
PDF layout fails loudly instead of producing a shifted curve.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SOURCE = "Kanhaiya2021"
PAPER = "Kanhaiya et al., ACS Nano 2021, 15, 17310-17318"
DOSE_UNIT = "krad(Si)"


@dataclass(frozen=True)
class Panel:
    key: str
    page: int
    frame: tuple[float, float, float, float]
    x_values: tuple[float, ...]
    y_values: tuple[float, ...]
    x_unit: str
    y_unit: str
    sample_x: tuple[float, ...]
    #: multiplier that converts the plotted dose axis into krad(Si)
    dose_scale: float = 1.0
    #: series name -> colour key; for multi-curve panels the tallest bounding
    #: box per colour is the thick-dielectric curve.
    series: list[tuple[str, str]] = field(default_factory=list)
    geometry: dict[str, str] = field(default_factory=dict)
    eot_nm: dict[str, float] = field(default_factory=dict)
    device_id: dict[str, str] = field(default_factory=dict)


COLOURS = {
    "black": (0.0, 0.0, 0.0),
    "red": (1.0, 0.0, 0.0),
    "blue": (0.0, 0.0, 1.0),
}

FIG3E = Panel(
    key="fig3e",
    page=4,
    frame=(403.0, 357.4, 511.3, 433.6),
    x_values=(0, 200, 400, 600, 800),
    y_values=(0, 200, 400, 600, 800),
    x_unit=DOSE_UNIT,
    y_unit="mV",
    sample_x=(0, 100, 200, 300, 500, 800),
    series=[("top_gate", "black"), ("local_bottom_gate", "red"), ("dual_gate", "blue")],
    geometry={
        "top_gate": "top-gate",
        "local_bottom_gate": "local bottom-gate",
        "dual_gate": "dual-gate",
    },
    eot_nm={"top_gate": 7.0, "local_bottom_gate": 7.0, "dual_gate": 7.0},
    device_id={
        "top_gate": "kanhaiya_top_gate",
        "local_bottom_gate": "kanhaiya_local_bottom_gate",
        "dual_gate": "kanhaiya_dual_gate",
    },
)

FIG4 = Panel(
    key="fig4",
    page=5,
    frame=(376.8, 71.1, 537.9, 201.9),
    x_values=(0, 2, 4, 6, 8, 10),
    y_values=(0, 200, 400, 600, 800),
    x_unit="Mrad(Si)",
    y_unit="mV",
    sample_x=(0, 0.1, 0.2, 0.5, 1, 2, 5, 8, 10),
    dose_scale=1000.0,
    series=[
        ("local_bottom_gate_thick", "red"),
        ("local_bottom_gate_thin", "red"),
        ("dual_gate_thick", "blue"),
        ("dual_gate_thin", "blue"),
    ],
    geometry={
        "local_bottom_gate_thick": "local bottom-gate EOT 7 nm",
        "local_bottom_gate_thin": "local bottom-gate EOT 2 nm",
        "dual_gate_thick": "dual-gate EOT 7 nm",
        "dual_gate_thin": "dual-gate EOT 2 nm",
    },
    eot_nm={
        "local_bottom_gate_thick": 7.0,
        "local_bottom_gate_thin": 2.0,
        "dual_gate_thick": 7.0,
        "dual_gate_thin": 2.0,
    },
    device_id={
        "local_bottom_gate_thick": "kanhaiya_local_bottom_gate_eot7",
        "local_bottom_gate_thin": "kanhaiya_local_bottom_gate_eot2",
        "dual_gate_thick": "kanhaiya_dual_gate_eot7",
        "dual_gate_thin": "kanhaiya_dual_gate_eot2",
    },
)

PANELS = (FIG3E, FIG4)


def pdf_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ticks(drawings, frame, axis: str) -> np.ndarray:
    """Tick-mark centres along one frame edge (inside the plot area)."""

    x0, y0, x1, y1 = frame
    found = []
    for drawing in drawings:
        rect = drawing["rect"]
        if drawing["type"] != "f" or rect.width > 3.0 or rect.height > 3.0:
            continue
        cx = (rect.x0 + rect.x1) / 2.0
        cy = (rect.y0 + rect.y1) / 2.0
        if axis == "x":
            if x0 - 0.3 <= cx <= x1 + 0.3 and y1 - 2.2 <= cy <= y1 - 0.2:
                found.append(cx)
        else:
            if y0 - 0.3 <= cy <= y1 + 0.3 and x0 + 0.2 <= cx <= x0 + 2.2:
                found.append(cy)
    values = np.array(sorted(found))
    if len(values) > 20:
        raise RuntimeError("tick detection exploded")
    if values.size == 0:
        return values
    # collapse duplicates that belong to the same tick
    merged = [values[0]]
    for value in values[1:]:
        if value - merged[-1] > 0.8:
            merged.append(value)
    return np.array(merged)


def _major_chain(values: np.ndarray) -> np.ndarray:
    """Keep the longest uniformly spaced run of ticks.

    Frame edges and corner artefacts also match the tick shape, so the useful
    ticks are the longest chain whose spacing equals the modal spacing.
    """

    if values.size < 3:
        return values
    steps = np.diff(values)
    rounded = np.round(steps / 0.5) * 0.5
    unique, counts = np.unique(rounded, return_counts=True)
    step = float(unique[np.argmax(counts)])
    if step <= 0:
        raise RuntimeError("tick spacing is not positive")
    best: list[float] = []
    for start in range(values.size):
        chain = [float(values[start])]
        for value in values[start + 1 :]:
            if abs((value - chain[-1]) - step) <= 0.15 * step:
                chain.append(float(value))
        if len(chain) > len(best):
            best = chain
    return np.array(best)


def _calibrate(tick_positions: np.ndarray, tick_values, axis_name: str) -> tuple[float, float]:
    tick_positions = _major_chain(tick_positions)
    if tick_positions.size != len(tick_values):
        raise RuntimeError(
            f"{axis_name} axis: expected {len(tick_values)} ticks, found {tick_positions.size}"
        )
    slope, intercept = np.polyfit(tick_positions, np.array(tick_values, dtype=float), 1)
    residual = float(np.max(np.abs(slope * tick_positions + intercept - np.array(tick_values))))
    tolerance = 0.02 * max(abs(float(min(tick_values))), abs(float(max(tick_values))), 1.0)
    if residual > tolerance:
        raise RuntimeError(f"{axis_name} axis: tick calibration residual {residual:.3g} too large")
    return float(slope), float(intercept)


def _centreline(drawing) -> tuple[np.ndarray, np.ndarray]:
    points = []
    for item in drawing["items"]:
        operator = item[0]
        if operator == "l":
            points.append((item[1].x, item[1].y))
            points.append((item[2].x, item[2].y))
        elif operator == "c":
            points.append((item[1].x, item[1].y))
            points.append((item[4].x, item[4].y))
    if not points:
        raise RuntimeError("curve path has no line items")
    array = np.array(points)
    xs = np.round(array[:, 0], 2)
    unique = []
    for value in np.unique(xs):
        ys = array[xs == value, 1]
        unique.append((value, float(ys.min()), float(ys.max())))
    curves = np.array(unique)
    return curves[:, 0], 0.5 * (curves[:, 1] + curves[:, 2])


def _series_paths(drawings, panel: Panel):
    """Collect the curve polygons, dropping frame, ticks, text and legend.

    Curves of the same colour are ordered by bounding-box height: the curve with
    the larger swing is the one drawn first in the panel definition.
    """

    x0, y0, x1, y1 = panel.frame
    width = x1 - x0
    by_colour: dict[str, list] = {}
    for drawing in drawings:
        fill = drawing.get("fill")
        if not fill or drawing["type"] != "f" or len(drawing["items"]) < 10:
            continue
        rect = drawing["rect"]
        if rect.width < 0.55 * width:
            continue
        if rect.x0 < x0 - 0.6 or rect.x1 > x1 + 0.6:
            continue
        if rect.y0 < y0 - 0.6 or rect.y1 > y1 + 0.6:
            continue
        # the axes frame is itself a filled path; skip anything that fills it
        if rect.width > 0.9 * width and rect.height > 0.9 * (y1 - y0):
            continue
        colour = tuple(round(c, 2) for c in fill)
        if colour not in COLOURS.values():
            continue
        by_colour.setdefault(colour, []).append((rect, drawing))

    for entries in by_colour.values():
        entries.sort(key=lambda item: item[0].height, reverse=True)

    counters: dict[str, int] = {}
    resolved = []
    for series_name, colour_name in panel.series:
        colour = COLOURS[colour_name]
        entries = by_colour.get(colour, [])
        index = counters.get(colour_name, 0)
        if index >= len(entries):
            raise RuntimeError(f"{panel.key}: no {colour_name} curve found for {series_name}")
        counters[colour_name] = index + 1
        resolved.append((series_name, entries[index]))
    return resolved


def digitize_panel(page, panel: Panel) -> dict:
    drawings = page.get_drawings()
    x_ticks = _ticks(drawings, panel.frame, "x")
    y_ticks = _ticks(drawings, panel.frame, "y")
    x_slope, x_intercept = _calibrate(x_ticks, panel.x_values, f"{panel.key} x")
    # y positions grow downwards, so the top tick carries the largest value
    y_slope, y_intercept = _calibrate(
        y_ticks, tuple(reversed(panel.y_values)), f"{panel.key} y"
    )

    series = _series_paths(drawings, panel)
    if len(series) != len(panel.series):
        raise RuntimeError(f"{panel.key}: expected {len(panel.series)} curves, got {len(series)}")

    rows = []
    for name, (rect, drawing) in series:
        xs, ys = _centreline(drawing)
        dose_axis = x_slope * xs + x_intercept
        value_axis = y_slope * ys + y_intercept
        order = np.argsort(dose_axis)
        dose_axis = dose_axis[order]
        value_axis = value_axis[order]
        span = float(dose_axis.max() - dose_axis.min())
        for target in panel.sample_x:
            if target < dose_axis.min() - 0.02 * span or target > dose_axis.max() + 0.02 * span:
                continue
            value = float(np.interp(target, dose_axis, value_axis))
            rows.append(
                {
                    "series": name,
                    "dose": float(target),
                    "value": value,
                    "bbox": [round(v, 2) for v in rect],
                }
            )
    return {
        "rows": rows,
        "calibration": {
            "x_slope": x_slope,
            "x_intercept": x_intercept,
            "y_slope": y_slope,
            "y_intercept": y_intercept,
            "n_x_ticks": int(x_ticks.size),
            "n_y_ticks": int(y_ticks.size),
            "series": [name for name, _ in series],
        },
    }


def draw_overlay(pdf_path: Path, results: dict, output: Path) -> None:
    import pymupdf
    from PIL import Image, ImageDraw

    doc = pymupdf.open(pdf_path)
    tiles = []
    for panel in PANELS:
        page = doc[panel.page - 1]
        x0, y0, x1, y1 = panel.frame
        clip = pymupdf.Rect(x0 - 26, y0 - 8, x1 + 6, y1 + 26)
        zoom = 6.0
        pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), clip=clip)
        image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
        draw = ImageDraw.Draw(image)
        cal = results[panel.key]["calibration"]
        for row in results[panel.key]["rows"]:
            px = ((row["dose"] - cal["x_intercept"]) / cal["x_slope"] - clip.x0) * zoom
            py = ((row["value"] - cal["y_intercept"]) / cal["y_slope"] - clip.y0) * zoom
            draw.line((px - 5, py, px + 5, py), fill=(255, 0, 255), width=1)
            draw.line((px, py - 5, px, py + 5), fill=(255, 0, 255), width=1)
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
    parser.add_argument("--pdf", type=Path, default=Path("reference/literature/nn1c04194.pdf"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/literature/kanhaiya2021/vt_shift_vs_tid.csv"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("data/literature/kanhaiya2021/digitization_report.json"),
    )
    parser.add_argument("--overlay", type=Path, default=Path("results/literature/kanhaiya_overlay.png"))
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
                    "device_id": panel.device_id[row["series"]],
                    "polarity": "p",
                    "geometry": panel.geometry[row["series"]],
                    "eot_nm": f"{panel.eot_nm[row['series']]:g}",
                    "dose_value": f"{row['dose'] * panel.dose_scale:g}",
                    "dose_unit": DOSE_UNIT,
                    "metric": "vt_shift_mv",
                    "value": f"{row['value']:.4g}",
                    "unit": panel.y_unit,
                    "figure": "Figure 3e" if panel.key == "fig3e" else "Figure 4",
                    "page": str(panel.page),
                    "extraction_method": f"pdf_vector_centreline:PyMuPDF-{pymupdf.__version__}",
                    "quality": "machine_extracted_pending_review",
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    columns = list(rows[0].keys())
    with args.output.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)

    report = {
        "schema_version": "1.0",
        "paper": PAPER,
        "pdf": str(args.pdf),
        "pdf_sha256": pdf_sha256(args.pdf),
        "pymupdf_version": pymupdf.__version__,
        "panels": {panel.key: results[panel.key]["calibration"] for panel in PANELS},
        "note": "Curve centrelines are recovered from the filled outline polygons; "
        "error bars are separate shapes and are not part of the centreline.",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + chr(10), encoding="utf-8")
    draw_overlay(args.pdf, results, args.overlay)

    print(f"CSV: {args.output} ({len(rows)} rows)")
    print(f"Report: {args.report}")
    print(f"Overlay: {args.overlay}")
    for panel in PANELS:
        print(" ", panel.key, [name for name, _ in panel.series])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
