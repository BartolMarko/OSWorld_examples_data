# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "reportlab",
# ]
# ///
"""Generate mock sales PDF tables for Q1-Q4 of 2024 and 2025."""

import csv
import random
from pathlib import Path
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)

# ── product definitions ──────────────────────────────────────────────────────
PRODUCTS = [
    {
        "name": "Logitech MX Master 3S Mouse",
        "price_range": (75, 110),
        "cost_ratio": (0.55, 0.70),
    },
    {
        "name": "Keychron Q6 Pro Keyboard (Red)",
        "price_range": (180, 230),
        "cost_ratio": (0.50, 0.65),
    },
    {
        "name": "Anker PowerExpand USB-C Hub",
        "price_range": (30, 55),
        "cost_ratio": (0.45, 0.60),
    },
    {
        "name": 'Dell U2723QE 27" 4K Monitor',
        "price_range": (480, 620),
        "cost_ratio": (0.60, 0.75),
    },
    {
        "name": "Herman Miller Aeron Chair (Size B)",
        "price_range": (1100, 1500),
        "cost_ratio": (0.50, 0.65),
    },
    {
        "name": "Flexispot E7 Pro Desk (Bamboo)",
        "price_range": (350, 500),
        "cost_ratio": (0.55, 0.70),
    },
    {
        "name": "Elgato Facecam Pro 4K",
        "price_range": (250, 330),
        "cost_ratio": (0.50, 0.65),
    },
    {
        "name": "Sony WH-1000XM5 Headphones",
        "price_range": (280, 400),
        "cost_ratio": (0.45, 0.60),
    },
    {
        "name": "Rain Design mStand (Silver)",
        "price_range": (40, 65),
        "cost_ratio": (0.40, 0.55),
    },
    {
        "name": "BenQ ScreenBar Halo Light",
        "price_range": (130, 180),
        "cost_ratio": (0.45, 0.60),
    },
]

COLUMNS = [
    "Product",
    "Units Sold",
    "Unit Price",
    "Unit Cost",
    "Total Revenue",
    "Total Cost",
    "Total Profit",
]


def fmt_dollar(value: float) -> str:
    """Format a float as USD with 2 decimals and thousands separator."""
    return f"${value:,.2f}"


def fmt_int(value: int) -> str:
    """Format integer with thousands separator."""
    return f"{value:,}"


MASTER_SEED = 42


def generate_row(product: dict, rng: random.Random) -> list[str]:
    """Generate one data row for a product."""
    units = rng.randint(0, 20_000)
    price = round(rng.uniform(*product["price_range"]), 2)
    cost_ratio = rng.uniform(*product["cost_ratio"])
    cost = round(price * cost_ratio, 2)

    revenue = round(units * price, 2)
    total_cost = round(units * cost, 2)
    profit = round(revenue - total_cost, 2)

    return [
        product["name"],
        fmt_int(units),
        fmt_dollar(price),
        fmt_dollar(cost),
        fmt_dollar(revenue),
        fmt_dollar(total_cost),
        fmt_dollar(profit),
    ]


def build_files(pdf_path: Path, csv_path: Path, quarter: int, year: int, seed: int) -> None:
    """Create a single-page sales PDF + CSV for the given quarter/year."""
    rng = random.Random(seed)

    doc = SimpleDocTemplate(
        str(pdf_path),
        pagesize=landscape(A4),
        rightMargin=1.5 * cm,
        leftMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm,
    )

    style = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "CustomTitle",
        parent=style["Heading1"],
        fontSize=18,
        spaceAfter=0.5 * cm,
        alignment=1,  # centre
    )

    elements = []

    # title
    elements.append(Paragraph(f"Sales Q{quarter} {year}", title_style))
    elements.append(Spacer(1, 0.3 * cm))

    # header + data rows
    data = [COLUMNS]
    for product in PRODUCTS:
        data.append(generate_row(product, rng))

    # totals row
    totals = [0.0] * 3  # revenue, cost, profit
    for row in data[1:]:
        # parse dollar strings back to floats
        totals[0] += float(row[4].replace("$", "").replace(",", ""))
        totals[1] += float(row[5].replace("$", "").replace(",", ""))
        totals[2] += float(row[6].replace("$", "").replace(",", ""))
    total_units = sum(
        int(row[1].replace(",", "")) for row in data[1:]
    )

    data.append([
        "TOTAL",
        fmt_int(total_units),
        "—",
        "—",
        fmt_dollar(totals[0]),
        fmt_dollar(totals[1]),
        fmt_dollar(totals[2]),
    ])

    # build table
    col_widths = [7.2 * cm, 2.0 * cm, 2.6 * cm, 2.6 * cm, 3.4 * cm, 3.4 * cm, 3.4 * cm]
    table = Table(data, colWidths=col_widths, repeatRows=1)

    table_style = TableStyle([
        # header
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a5276")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        # body
        ("FONTNAME", (0, 1), (-1, -2), "Helvetica"),
        ("FONTSIZE", (0, 1), (-1, -2), 7),
        # totals row
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#d5dbdb")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, -1), (-1, -1), 9),
        # alignment
        ("ALIGN", (0, 0), (0, -1), "LEFT"),    # product name left
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),  # numbers right
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        # grid
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#bdc3c7")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.2, colors.HexColor("#0e3750")),
        ("LINEABOVE", (0, -1), (-1, -1), 1.2, colors.HexColor("#7f8c8d")),
        # padding
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        # alternating row colours
        *[
            ("BACKGROUND", (0, i), (-1, i), colors.HexColor("#eaf2f8"))
            for i in range(2, len(data), 2)
        ],
    ])
    table.setStyle(table_style)

    elements.append(table)

    doc.build(elements)

    # ── write CSV ──────────────────────────────────────────────────────────
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        for row in data[1:-1]:  # product rows (without header, without totals)
            # strip $ and , for clean numeric CSV
            clean_row = [
                col.replace("$", "").replace(",", "")
                if "$" in col else col.replace(",", "")
                for col in row
            ]
            writer.writerow(clean_row)
        # totals row (already formatted)
        totals_row = [
            col.replace("$", "").replace(",", "")
            if "$" in col or "," in col else col
            for col in data[-1]
        ]
        writer.writerow(totals_row)


def main() -> None:
    base_dir = Path(__file__).resolve().parent / "mock_sales_tables"
    base_dir.mkdir(exist_ok=True)

    for year in (2024, 2025):
        for quarter in range(1, 5):
            seed = MASTER_SEED + year * 10 + quarter
            pdf_path = base_dir / f"sales_Q{quarter}_{year}.pdf"
            csv_path = base_dir / f"sales_Q{quarter}_{year}.csv"
            build_files(pdf_path, csv_path, quarter, year, seed=seed)
            print(f"  ✓  {pdf_path.name}  +  {csv_path.name}")

    print(f"\nDone! 16 files written to {base_dir}")


if __name__ == "__main__":
    main()
