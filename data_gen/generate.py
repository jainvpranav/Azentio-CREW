"""
Generate synthetic bank statements (BUILD_PLAN.md section 7) for the demo
AND as a test fixture set. Run with:

    venv/Scripts/python.exe -m data_gen.generate

Produces data_gen/output/*.pdf|csv|json|xlsx plus ground_truth.json
(txn key "<filename>#<row_index>" -> expected category).
"""
import csv
import json
import os
from decimal import Decimal as D

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

from data_gen import scenarios as sc

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")
STYLES = getSampleStyleSheet()


# ===================== balance computation =====================

def compute_balances(opening: D, ledger: list) -> list:
    """ledger: [(date, desc, debit, credit, category)] -> adds running balance"""
    rows = []
    balance = opening
    for d, desc, debit, credit, category in ledger:
        balance = balance + (credit or D(0)) - (debit or D(0))
        rows.append({"date": d, "desc": desc, "debit": debit, "credit": credit, "balance": balance, "category": category})
    return rows


def slice_range(rows_with_balance: list, opening_before: D, start, end) -> dict:
    """
    rows_with_balance: output of compute_balances for the FULL ledger.
    opening_before: the ledger's true opening balance (before row 0).
    Returns {"opening": Decimal, "closing": Decimal, "rows": [...]} for rows
    whose date falls in [start, end], with the correct true opening balance
    (the running balance immediately before the first included row).
    """
    included = [r for r in rows_with_balance if start <= r["date"] <= end]
    if not included:
        return {"opening": opening_before, "closing": opening_before, "rows": []}

    idx0 = rows_with_balance.index(included[0])
    opening = rows_with_balance[idx0 - 1]["balance"] if idx0 > 0 else opening_before
    closing = included[-1]["balance"]
    return {"opening": opening, "closing": closing, "rows": included}


# ===================== PDF Layout A (table) =====================

def format_money(amount: D, currency: str = "INR") -> str:
    if amount is None:
        return "-"
    return f"{amount:,.2f} {currency}"


def write_layout_a_pdf(path: str, holder: str, account_number: str, bank_name: str,
                        start, end, opening: D, closing: D, rows: list, currency: str = "INR"):
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    story = [
        Paragraph(f"{bank_name} — Savings Account Statement", STYLES["Title"]),
        Spacer(1, 6),
        Paragraph(f"Account Holder: {holder}", STYLES["Normal"]),
        Paragraph(f"Account Number: {account_number}", STYLES["Normal"]),
        Paragraph(f"Bank: {bank_name}", STYLES["Normal"]),
        Paragraph(f"Statement Period: {start:%d %b %Y} to {end:%d %b %Y}", STYLES["Normal"]),
        Paragraph(f"Opening Balance: {format_money(opening, currency)}", STYLES["Normal"]),
        Paragraph(f"Closing Balance: {format_money(closing, currency)}", STYLES["Normal"]),
        Spacer(1, 12),
    ]

    table_data = [["Date", "Description", "Debit", "Credit", "Balance"]]
    for r in rows:
        table_data.append([
            r["date"].strftime("%d/%m/%Y"),
            r["desc"],
            f"{r['debit']:,.2f}" if r["debit"] else "-",
            f"{r['credit']:,.2f}" if r["credit"] else "-",
            f"{r['balance']:,.2f}",
        ])

    table = Table(table_data, colWidths=[22 * mm, 68 * mm, 25 * mm, 25 * mm, 28 * mm])
    table.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (2, 0), (4, -1), "RIGHT"),
    ]))
    story.append(table)
    doc.build(story)


def write_broken_balance_pdf(path: str, holder: str, account_number: str, bank_name: str):
    base_rows = compute_balances(sc.BROKEN_OPENING, sc.BROKEN_LEDGER)
    start, end = base_rows[0]["date"].replace(day=1), base_rows[-1]["date"]

    # Corrupt one row's PRINTED balance and carry the offset through every
    # later row, so only that one row's chain breaks (BUILD_PLAN 3.3).
    rows = [dict(r) for r in base_rows]
    for i, r in enumerate(rows):
        if i + 1 >= sc.BROKEN_ROW_INDEX:
            r["balance"] = r["balance"] + sc.BROKEN_OFFSET

    write_layout_a_pdf(
        path, holder, account_number, bank_name,
        start, end, sc.BROKEN_OPENING, rows[-1]["balance"], rows,
    )
    return rows


# ===================== PDF Layout B (free text) =====================

def write_layout_b_pdf(path: str, holder: str, account_number: str, bank_name: str,
                        start, end, opening: D, closing: D, rows: list, currency: str = "INR"):
    doc = SimpleDocTemplate(path, pagesize=A4, topMargin=20 * mm, bottomMargin=20 * mm)
    mono = STYLES["Normal"].clone("mono")
    mono.fontName = "Courier"
    mono.fontSize = 8
    mono.leading = 12

    story = [
        Paragraph(f"{bank_name}", STYLES["Title"]),
        Paragraph("Current Account Statement", STYLES["Heading2"]),
        Spacer(1, 6),
        Paragraph(f"Name: {holder}", STYLES["Normal"]),
        Paragraph(f"A/c No: {account_number}", STYLES["Normal"]),
        Paragraph(f"Period: {start:%d-%b-%Y} to {end:%d-%b-%Y}", STYLES["Normal"]),
        Paragraph(f"Opening Bal: {format_money(opening, currency)}", STYLES["Normal"]),
        Paragraph(f"Closing Bal: {format_money(closing, currency)}", STYLES["Normal"]),
        Spacer(1, 12),
    ]

    for r in rows:
        side = "CR" if r["credit"] else "DR"
        amount = r["credit"] or r["debit"]
        line = f"{r['date']:%d-%b-%Y} | {r['desc']} | {side} | {amount:,.2f} {currency} | {r['balance']:,.2f} {currency}"
        story.append(Paragraph(line, mono))

    doc.build(story)


# ===================== scanned (image-only) page =====================

def write_scanned_page_pdf(path: str):
    """One page with only vector graphics, no text objects at all."""
    c = canvas.Canvas(path, pagesize=A4)
    c.setFillColorRGB(0.92, 0.92, 0.92)
    c.rect(40, 400, 500, 350, fill=1, stroke=0)
    c.setStrokeColorRGB(0.6, 0.6, 0.6)
    for y in range(420, 720, 25):
        c.line(60, y, 500, y)
    c.showPage()
    c.save()


def write_scanned_image_pdf(path: str, accent: str = "#5b6f94"):
    """Second image-only PDF variant to exercise a second scanned page file."""
    c = canvas.Canvas(path, pagesize=A4)
    c.setFillColor(colors.HexColor(accent))
    c.rect(70, 160, 180, 90, fill=1, stroke=0)
    c.setFillColor(colors.HexColor("#f6f8fb"))
    c.rect(120, 280, 360, 240, fill=1, stroke=0)
    c.setStrokeColor(colors.HexColor("#8ea0ba"))
    for y in range(300, 500, 22):
        c.line(150, y, 430, y)
    c.showPage()
    c.save()


# ===================== structured files =====================

def write_csv(path: str, rows: list, columns: dict):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([columns["date"], columns["description"], columns["debit"], columns["credit"]])
        for d, desc, debit, credit, _cat in rows:
            writer.writerow([
                d.strftime("%d/%m/%Y"), desc,
                f"{debit:.2f}" if debit else "",
                f"{credit:.2f}" if credit else "",
            ])


def write_json(path: str, rows: list, fields: dict):
    out = []
    for d, desc, debit, credit, _cat in rows:
        out.append({
            fields["date"]: d.strftime("%Y-%m-%d"),
            fields["description"]: desc,
            fields["debit"]: float(debit) if debit else None,
            fields["credit"]: float(credit) if credit else None,
        })
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)


def write_xlsx(path: str, rows: list, columns: dict):
    dates, descs, debits, credits = [], [], [], []
    for d, desc, debit, credit, _cat in rows:
        dates.append(d.strftime("%d/%m/%Y"))
        descs.append(desc)
        debits.append(float(debit) if debit else None)
        credits.append(float(credit) if credit else None)

    data = {
        columns["date"]: dates,
        columns["description"]: descs,
        columns["debit"]: debits,
        columns["credit"]: credits,
    }
    pd.DataFrame(data).to_excel(path, index=False)


# ===================== ground truth =====================

def add_ground_truth(gt: dict, filename: str, rows: list):
    for i, r in enumerate(rows, 1):
        gt[f"{filename}#{i}"] = r["category"] if isinstance(r, dict) else r[4]


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ground_truth = {}

    # ---- Account A: Lotus Bank savings (Layout A) ----
    bankA_full = compute_balances(sc.BANKA_OPENING, sc.BANKA_LEDGER)
    file1 = slice_range(bankA_full, sc.BANKA_OPENING, *sc.BANKA_FILE1_RANGE)
    file2 = slice_range(bankA_full, sc.BANKA_OPENING, *sc.BANKA_FILE2_RANGE)

    write_layout_a_pdf(
        os.path.join(OUTPUT_DIR, "bankA_savings_apr_jun.pdf"),
        sc.ACCOUNT_A["holder_name"], sc.ACCOUNT_A["account_number"], sc.ACCOUNT_A["bank_name"],
        sc.BANKA_FILE1_RANGE[0], sc.BANKA_FILE1_RANGE[1], file1["opening"], file1["closing"], file1["rows"],
    )
    add_ground_truth(ground_truth, "bankA_savings_apr_jun.pdf", file1["rows"])

    write_layout_a_pdf(
        os.path.join(OUTPUT_DIR, "bankA_savings_jun_aug.pdf"),
        sc.ACCOUNT_A["holder_name"], sc.ACCOUNT_A["account_number"], sc.ACCOUNT_A["bank_name"],
        sc.BANKA_FILE2_RANGE[0], sc.BANKA_FILE2_RANGE[1], file2["opening"], file2["closing"], file2["rows"],
    )
    add_ground_truth(ground_truth, "bankA_savings_jun_aug.pdf", file2["rows"])

    # ---- Account B: Meridian current (Layout B), July gap ----
    bankB_full = compute_balances(sc.BANKB_OPENING, sc.BANKB_LEDGER)
    fileB1 = slice_range(bankB_full, sc.BANKB_OPENING, *sc.BANKB_FILE1_RANGE)
    fileB2 = slice_range(bankB_full, sc.BANKB_OPENING, *sc.BANKB_FILE2_RANGE)

    write_layout_b_pdf(
        os.path.join(OUTPUT_DIR, "bankB_current_apr_jun.pdf"),
        sc.ACCOUNT_B["holder_name"], sc.ACCOUNT_B["account_number"], sc.ACCOUNT_B["bank_name"],
        sc.BANKB_FILE1_RANGE[0], sc.BANKB_FILE1_RANGE[1], fileB1["opening"], fileB1["closing"], fileB1["rows"],
    )
    add_ground_truth(ground_truth, "bankB_current_apr_jun.pdf", fileB1["rows"])

    write_layout_b_pdf(
        os.path.join(OUTPUT_DIR, "bankB_current_aug_sep.pdf"),
        sc.ACCOUNT_B["holder_name"], sc.ACCOUNT_B["account_number"], sc.ACCOUNT_B["bank_name"],
        sc.BANKB_FILE2_RANGE[0], sc.BANKB_FILE2_RANGE[1], fileB2["opening"], fileB2["closing"], fileB2["rows"],
    )
    add_ground_truth(ground_truth, "bankB_current_aug_sep.pdf", fileB2["rows"])

    # ---- Scanned (unreadable) page ----
    write_scanned_page_pdf(os.path.join(OUTPUT_DIR, "bankB_scanned_page.pdf"))
    write_scanned_image_pdf(os.path.join(OUTPUT_DIR, "bankB_scanned_image.pdf"))

    # ---- Broken balance ----
    broken_rows = write_broken_balance_pdf(
        os.path.join(OUTPUT_DIR, "bankA_broken_balance.pdf"),
        sc.ACCOUNT_A["holder_name"], "1234569999", sc.ACCOUNT_A["bank_name"],
    )
    add_ground_truth(ground_truth, "bankA_broken_balance.pdf", broken_rows)

    # ---- Structured files ----
    write_csv(
        os.path.join(OUTPUT_DIR, "card_spend.csv"), sc.CARD_SPEND_ROWS,
        {"date": "Transaction Date", "description": "Merchant", "debit": "Amount Debited", "credit": "Amount Credited"},
    )
    add_ground_truth(ground_truth, "card_spend.csv", sc.CARD_SPEND_ROWS)

    write_json(
        os.path.join(OUTPUT_DIR, "wallet.json"), sc.WALLET_JSON_ROWS,
        {"date": "txn_date", "description": "narration", "debit": "debit_amt", "credit": "credit_amt"},
    )
    add_ground_truth(ground_truth, "wallet.json", sc.WALLET_JSON_ROWS)

    write_xlsx(
        os.path.join(OUTPUT_DIR, "ledger.xlsx"), sc.LEDGER_XLSX_ROWS,
        {"date": "Value Date", "description": "Particulars", "debit": "Withdrawal Amt", "credit": "Deposit Amt"},
    )
    add_ground_truth(ground_truth, "ledger.xlsx", sc.LEDGER_XLSX_ROWS)

    # ---- SME scenario: concentration, supplier payments, possible
    # circular flow, NSF bounce (handoff Phase 8). ----
    write_csv(
        os.path.join(OUTPUT_DIR, "sme_business.csv"), sc.SME_LEDGER,
        {"date": "Date", "description": "Description", "debit": "Debit", "credit": "Credit"},
    )
    add_ground_truth(ground_truth, "sme_business.csv", sc.SME_LEDGER)

    # ---- UAE / Oman foreign-currency examples ----
    uae_rows = compute_balances(sc.UAE_OPENING, sc.UAE_LEDGER)
    uae_file = slice_range(uae_rows, sc.UAE_OPENING, *sc.UAE_FILE_RANGE)
    write_layout_a_pdf(
        os.path.join(OUTPUT_DIR, "bank_muscat_omr_apr_sep.pdf"),
        sc.UAE_ACCOUNT["holder_name"], sc.UAE_ACCOUNT["account_number"], sc.UAE_ACCOUNT["bank_name"],
        sc.UAE_FILE_RANGE[0], sc.UAE_FILE_RANGE[1], uae_file["opening"], uae_file["closing"], uae_file["rows"],
        currency=sc.UAE_ACCOUNT["currency"],
    )
    add_ground_truth(ground_truth, "bank_muscat_omr_apr_sep.pdf", uae_file["rows"])

    aed_rows = compute_balances(sc.AED_OPENING, sc.AED_LEDGER)
    aed_file = slice_range(aed_rows, sc.AED_OPENING, *sc.AED_FILE_RANGE)
    write_layout_b_pdf(
        os.path.join(OUTPUT_DIR, "emirates_nbd_aed_apr_sep.pdf"),
        sc.AED_ACCOUNT["holder_name"], sc.AED_ACCOUNT["account_number"], sc.AED_ACCOUNT["bank_name"],
        sc.AED_FILE_RANGE[0], sc.AED_FILE_RANGE[1], aed_file["opening"], aed_file["closing"], aed_file["rows"],
        currency=sc.AED_ACCOUNT["currency"],
    )
    add_ground_truth(ground_truth, "emirates_nbd_aed_apr_sep.pdf", aed_file["rows"])

    with open(os.path.join(OUTPUT_DIR, "ground_truth.json"), "w", encoding="utf-8") as f:
        json.dump(ground_truth, f, indent=2)

    print(f"Generated {len(ground_truth)} ground-truth transactions into {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
