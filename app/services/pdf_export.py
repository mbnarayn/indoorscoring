"""Render a match scorecard (as produced by MatchService.scorecard) to PDF."""

from typing import Any

from fpdf import FPDF
from fpdf.fonts import FontFace

GREEN = (11, 61, 46)
GREY = (90, 90, 90)


def _t(value: Any) -> str:
    # Core PDF fonts only cover Latin-1; replace anything else rather than failing.
    return str(value if value is not None else "").encode("latin-1", "replace").decode("latin-1")


class _ScorecardPDF(FPDF):
    def __init__(self, title: str):
        super().__init__(orientation="P", unit="mm", format="A4")
        self.doc_title = title
        self.set_auto_page_break(auto=True, margin=15)
        self.set_margins(12, 12, 12)

    def footer(self) -> None:
        self.set_y(-12)
        self.set_font("Helvetica", size=8)
        self.set_text_color(*GREY)
        self.cell(0, 6, _t(f"{self.doc_title} - page {self.page_no()}"), align="C")


def _heading(pdf: FPDF, text: str, size: int = 13) -> None:
    pdf.set_font("Helvetica", "B", size)
    pdf.set_text_color(*GREEN)
    pdf.cell(0, 8, _t(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)


def _line(pdf: FPDF, label: str, text: str) -> None:
    pdf.set_font("Helvetica", "B", 9)
    pdf.write(5, _t(f"{label}: "))
    pdf.set_font("Helvetica", size=9)
    pdf.write(5, _t(text))
    pdf.ln(5)


def _table(pdf: FPDF, header: list[str], rows: list[list[Any]], widths: tuple[int, ...], text_cols: int = 1) -> None:
    pdf.set_font("Helvetica", size=8.5)
    head_style = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=GREEN)
    align = ["LEFT"] * text_cols + ["RIGHT"] * (len(header) - text_cols)
    with pdf.table(
        col_widths=widths,
        text_align=align,
        headings_style=head_style,
        line_height=5,
        borders_layout="HORIZONTAL_LINES",
        first_row_as_headings=True,
    ) as table:
        table.row([_t(h) for h in header])
        for r in rows:
            table.row([_t(c) for c in r])
    pdf.ln(2)


def render_scorecard_pdf(scorecard: dict[str, Any]) -> bytes:
    match = scorecard["match"]
    summary = scorecard["summary"]
    pdf = _ScorecardPDF(match["name"])
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _t(match["name"]), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=10)
    pdf.set_text_color(*GREY)
    venue = f" - {match['venue']}" if match.get("venue") else ""
    pdf.cell(0, 6, _t(f"{match['date']}{venue}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(0, 0, 0)
    pdf.ln(2)

    result = (summary.get("result") or {}).get("text") or "Match in progress"
    _heading(pdf, result, 14)
    for t in summary["team_scores"]:
        _line(pdf, t["name"], " & ".join(t["innings"]) or "Yet to bat")
    if tb := summary.get("top_batsman"):
        _line(pdf, "Top batsman", f"{tb['name']} ({tb['team_name']}) {tb['runs']} ({tb['balls']})")
    if tw := summary.get("top_bowler"):
        _line(pdf, "Top bowler", f"{tw['name']} ({tw['team_name']}) {tw['wickets']}/{tw['runs']} ({tw['overs']} ov)")
    pdf.ln(3)

    for inn in scorecard["innings"]:
        _heading(
            pdf,
            f"{inn['batting_team_name']} - Innings {inn['number']}: {inn['runs']}/{inn['wickets']} ({inn['overs']} ov)",
        )
        if inn.get("target"):
            _line(pdf, "Target", str(inn["target"]))

        batting_rows = []
        for b in inn["batting"]:
            how = b.get("dismissal") or ""
            if b.get("pair_dismissals"):
                how += f"; out {len(b['pair_dismissals'])}x in pairs ({'; '.join(b['pair_dismissals'])})"
            batting_rows.append(
                [b["name"], how, b["runs"], b["balls"], b["wides_faced"], b["fours"], b["sixes"], f"{b['strike_rate']:.1f}"]
            )
        _table(pdf, ["Batsman", "How out", "R", "B", "Wd", "4s", "6s", "SR"], batting_rows, (30, 68, 12, 12, 12, 12, 12, 22), text_cols=2)

        x = inn["extras"]
        _line(pdf, "Extras", f"{x['total']} (wd {x['wide']}, nb {x['no_ball']})")
        _line(pdf, "Total", f"{inn['runs']}/{inn['wickets']} ({inn['overs']} ov, RR {inn['run_rate']:.2f})")
        if inn["retired"]:
            _line(pdf, "Retired not out", ", ".join(inn["retired"]))
        if inn["did_not_bat"]:
            _line(pdf, "Did not bat", ", ".join(inn["did_not_bat"]))
        if inn["fall_of_wickets"]:
            fow = ", ".join(f"{f['wicket']}-{f['runs']} ({f['name']}, {f['overs']})" for f in inn["fall_of_wickets"])
            _line(pdf, "Fall of wickets", fow)
        pdf.ln(1)

        bowling_rows = [
            [b["name"], b["overs"], b["runs"], b["wickets"], f"{b['economy']:.2f}", b["wides"], b["no_balls"]]
            for b in inn["bowling"]
        ]
        _table(pdf, ["Bowler", "O", "R", "W", "Econ", "Wd", "Nb"], bowling_rows, (60, 20, 20, 20, 22, 20, 20))

        if inn.get("balls"):
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(0, 6, "Ball by ball", new_x="LMARGIN", new_y="NEXT")
            pdf.set_font("Helvetica", size=8.5)
            overs: list[tuple[int, str, list[str]]] = []
            for ball in inn["balls"]:
                if not overs or overs[-1][0] != ball["over"]:
                    overs.append((ball["over"], ball["bowler_name"], []))
                overs[-1][2].append("." if ball["label"] == "\u2022" else ball["label"])
            for over, bowler, labels in overs:
                pdf.multi_cell(0, 4.5, _t(f"Ov {over} ({bowler}):  " + "  ".join(labels)), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

    return bytes(pdf.output())
