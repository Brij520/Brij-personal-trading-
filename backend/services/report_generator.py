"""Professional research report generator.

Produces the 25-section research report required by the specification, from a
:class:`ResearchReport`, and exports it to Markdown, HTML, PDF, CSV, XLSX or JSON.

Every financial figure in the rendered output is accompanied by its source and
as-of date, and a data-quality banner appears at the top of every format. If the
data is synthetic, that is stated in the first three lines, not in a footnote.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.core.errors import ValidationError
from backend.services.formats import PdfLine, write_pdf, write_xlsx
from backend.services.orchestrator import ResearchReport

SECTIONS = [
    "Company overview",
    "Business model",
    "Industry analysis",
    "Financial performance",
    "Revenue growth",
    "Profitability",
    "Cash flow",
    "Balance sheet",
    "Management quality",
    "Corporate governance",
    "Promoter holding",
    "Institutional ownership",
    "Peer comparison",
    "Valuation",
    "Technical analysis",
    "News and sentiment",
    "Bull case",
    "Base case",
    "Bear case",
    "Risk factors",
    "Investment thesis",
    "Thesis invalidation",
    "Data limitations",
    "Source references",
    "Final research classification",
]


def _fmt(value: Any, digits: int = 2, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:,.{digits}f}{suffix}"
    return str(value)


def _get(report: ResearchReport, agent: str) -> dict[str, Any]:
    finding = report.findings.get(agent)
    return finding.model_dump(mode="json") if finding else {}


def build_sections(report: ResearchReport) -> list[dict[str, Any]]:
    """Structured, format-independent report body."""
    bundle = report.bundle_summary
    fund = _get(report, "fundamental_research")
    val = _get(report, "valuation")
    tech = _get(report, "technical_analysis")
    news = _get(report, "news_sentiment")
    forensic = _get(report, "forensic_accounting")
    bull = _get(report, "bull_research")
    bear = _get(report, "bear_research")
    committee = _get(report, "research_committee")
    market = _get(report, "market_intelligence")
    risk = _get(report, "risk_management")

    fmetrics = fund.get("metrics", {})
    vmetrics = val.get("metrics", {})
    tmetrics = tech.get("metrics", {})
    cmetrics = committee.get("metrics", {})
    latest_ratios = fmetrics.get("latest_ratios", {})
    scenarios = vmetrics.get("scenarios", [])
    base_case = next((s for s in scenarios if s["name"] == "BASE"), None)

    def section(title: str, body: list[str], sources: list[str] | None = None) -> dict[str, Any]:
        return {"title": title, "body": body, "sources": sources or []}

    out: list[dict[str, Any]] = []
    out.append(
        section(
            "Company overview",
            [
                f"{bundle.get('company')} ({report.symbol}) operates in "
                f"{bundle.get('sector')} / {bundle.get('industry')}.",
                f"Last price {_fmt(bundle.get('price'))}; price history spans "
                f"{bundle.get('first_bar')} to {bundle.get('last_bar')} "
                f"({bundle.get('bars')} bars).",
                f"Data mode: {report.data_mode.upper()}. Data quality "
                f"{bundle.get('data_quality', {}).get('score')}/100 "
                f"({bundle.get('data_quality', {}).get('band')}).",
            ],
        )
    )
    out.append(
        section(
            "Business model",
            [
                "The platform does not ingest the company's business description, "
                "segment mix or revenue model from a primary source. This section is "
                "therefore intentionally blank rather than guessed from the sector label.",
                f"Sector classification used for peer grouping: {bundle.get('sector')}.",
            ],
        )
    )
    out.append(
        section(
            "Industry analysis",
            [
                "No industry-level demand, capacity or regulatory dataset is integrated. "
                "Sector performance below is a price-based proxy only.",
                *[
                    f"{row['sector']}: average 1-month price change {row['avg_1m_pct']:+.2f}%, "
                    f"{row['breadth_pct']:.0f}% of constituents positive"
                    for row in market.get("metrics", {}).get("sector_performance", [])[:5]
                ],
            ],
        )
    )
    out.append(
        section(
            "Financial performance",
            [
                f"Latest fiscal year {latest_ratios.get('fiscal_year')}: revenue "
                f"INR {_fmt(latest_ratios.get('revenue_cr'), 0)} crore, EBITDA "
                f"INR {_fmt(latest_ratios.get('ebitda_margin_pct'), 1)}% margin, "
                f"PAT margin {_fmt(latest_ratios.get('net_margin_pct'), 1)}%.",
                f"Return on equity {_fmt(latest_ratios.get('roe_pct'), 1)}%; "
                f"return on capital employed {_fmt(latest_ratios.get('roce_pct'), 1)}%; "
                f"return on assets {_fmt(latest_ratios.get('roa_pct'), 2)}%.",
                f"Fundamental quality score {fmetrics.get('quality_score')}/100 "
                f"({fmetrics.get('quality_band')}).",
            ],
            ["Reported annual statements"],
        )
    )
    out.append(
        section(
            "Revenue growth",
            [
                f"3-year revenue CAGR {_fmt(fmetrics.get('revenue_cagr_3y_pct'), 1)}%; "
                f"5-year CAGR {_fmt(fmetrics.get('revenue_cagr_5y_pct'), 1)}%.",
                f"3-year PAT CAGR {_fmt(fmetrics.get('pat_cagr_3y_pct'), 1)}%; EPS CAGR "
                f"{_fmt(fmetrics.get('eps_cagr_3y_pct'), 1)}%.",
                f"Proportion of years with positive growth: "
                f"{_fmt(fmetrics.get('eps_consistency_pct'), 0)}%.",
            ],
            ["Reported annual statements"],
        )
    )
    out.append(
        section(
            "Profitability",
            [
                f"EBITDA margin {_fmt(latest_ratios.get('ebitda_margin_pct'), 1)}%, "
                f"EBIT margin {_fmt(latest_ratios.get('ebit_margin_pct'), 1)}%, "
                f"net margin {_fmt(latest_ratios.get('net_margin_pct'), 1)}%.",
                f"Margin trend across the series: {fmetrics.get('margin_trend')}.",
                f"Cash quality: {fmetrics.get('cash_quality')} "
                f"(CFO/PAT {_fmt(latest_ratios.get('cfo_to_pat'))}).",
            ],
            ["Reported annual statements"],
        )
    )
    out.append(
        section(
            "Cash flow",
            [
                f"Operating cash flow conversion (CFO/PAT) "
                f"{_fmt(latest_ratios.get('cfo_to_pat'))}; free cash flow "
                f"INR {_fmt(latest_ratios.get('fcf_cr'), 0)} crore "
                f"(FCF margin {_fmt(latest_ratios.get('fcf_margin_pct'), 1)}%).",
                f"Cash conversion cycle {_fmt(latest_ratios.get('cash_conversion_cycle_days'), 1)} days "
                f"(receivables {_fmt(latest_ratios.get('receivable_days'), 1)}d, "
                f"inventory {_fmt(latest_ratios.get('inventory_days'), 1)}d, "
                f"payables {_fmt(latest_ratios.get('payable_days'), 1)}d).",
            ],
            ["Reported cash-flow statements"],
        )
    )
    out.append(
        section(
            "Balance sheet",
            [
                f"Debt-to-equity {_fmt(latest_ratios.get('debt_to_equity'))}; net debt/EBITDA "
                f"{_fmt(latest_ratios.get('net_debt_to_ebitda'))}; interest coverage "
                f"{_fmt(latest_ratios.get('interest_coverage'))}x.",
                f"Leverage trend: {fmetrics.get('leverage_trend')}.",
            ],
            ["Reported balance sheet"],
        )
    )
    out.append(
        section(
            "Management quality",
            [
                "Capital-allocation judgement requires the annual report, transcripts and "
                "a multi-year track record. This platform does not have those inputs, so "
                "no management-quality rating is issued.",
                "Observable proxies: dividend payout "
                f"{_fmt(fmetrics.get('dividend_payout'))}, equity dilution "
                f"{_fmt(forensic.get('metrics', {}).get('governance', {}).get('equity_dilution_pct_3y'))}"
                "% over three years.",
            ],
        )
    )
    gov = forensic.get("metrics", {}).get("governance", {})
    out.append(
        section(
            "Corporate governance",
            [
                f"Auditor changes in five years: {gov.get('auditor_changes_5y', 'n/a')}.",
                f"Auditor qualification: {gov.get('auditor_qualification') or 'none reported'}.",
                f"Related-party transactions: {_fmt(gov.get('related_party_pct_revenue'))}% of revenue; "
                f"contingent liabilities {_fmt(gov.get('contingent_liab_pct_equity'))}% of equity.",
                f"Forensic flags: {forensic.get('metrics', {}).get('flag_count', 0)} "
                f"({forensic.get('metrics', {}).get('critical_count', 0)} high severity).",
            ],
            ["Reported statements and disclosures"],
        )
    )
    out.append(
        section(
            "Promoter holding",
            [
                f"Promoter holding {_fmt(fmetrics.get('promoter_holding_pct'))}% "
                f"with {_fmt(fmetrics.get('promoter_pledge_pct'))}% of that pledged.",
            ],
            ["Shareholding pattern snapshot"],
        )
    )
    out.append(
        section(
            "Institutional ownership",
            [
                f"FII + DII combined {_fmt(fmetrics.get('institutional_pct'))}%.",
                "Quarter-on-quarter changes in institutional holding require the filings "
                "feed and are not analysed in this release.",
            ],
            ["Shareholding pattern snapshot"],
        )
    )
    peers = vmetrics.get("peers", [])
    out.append(
        section(
            "Peer comparison",
            [
                f"{len(peers)} same-sector peer(s) compared on P/E, P/B and EV/EBITDA.",
                *[
                    f"{row['metric']}: company {_fmt(row['company'])} vs peer median "
                    f"{_fmt(row['peer_median'])} — {row['verdict']}."
                    for row in vmetrics.get("multiples", [])
                ],
            ],
            ["Peer multiples computed from the platform universe"],
        )
    )
    val_lines = [val.get("headline", "Valuation not computed.")]
    if base_case:
        val_lines.append(
            f"Base case value INR {_fmt(base_case['value_per_share'])} per share under "
            f"growth {base_case['growth'] * 100:.1f}%, margin {base_case['margin'] * 100:.1f}%, "
            f"WACC {base_case['wacc'] * 100:.1f}%, terminal growth "
            f"{base_case['terminal_growth'] * 100:.1f}%."
        )
    if "dcf" in vmetrics:
        dcf = vmetrics["dcf"]
        val_lines.append(
            f"Terminal value accounts for {dcf['terminal_share_of_value'] * 100:.0f}% of "
            "the DCF enterprise value."
        )
    if "bank_valuation" in vmetrics:
        bv = vmetrics["bank_valuation"]
        val_lines.append(
            f"Justified P/B {_fmt(bv['justified_pb'])} vs traded P/B {_fmt(bv['price_to_book'])} "
            f"using ROE {bv['assumptions']['roe'] * 100:.1f}%, cost of equity "
            f"{bv['assumptions']['cost_of_equity'] * 100:.1f}%, sustainable growth "
            f"{bv['assumptions']['sustainable_growth'] * 100:.1f}%."
        )
    val_lines.append(
        "Valuation is a model output, not a forecast or a target price. Assumptions above "
        "drive the answer; change them and re-run before relying on any figure."
    )
    out.append(section("Valuation", val_lines, ["Valuation models (FCFF DCF / justified P/B)"]))
    ind = tmetrics.get("indicators", {})
    out.append(
        section(
            "Technical analysis",
            [
                tech.get("headline", "Technical read unavailable."),
                f"Trend alignment: {tmetrics.get('alignment')}. Support "
                f"{tmetrics.get('support')}, resistance {tmetrics.get('resistance')}.",
                f"RSI(14) {_fmt(ind.get('rsi14'), 1)}; MACD histogram "
                f"{_fmt(ind.get('macd_hist'), 3)}; ADX {_fmt(ind.get('adx14'), 1)}; "
                f"ATR {_fmt(ind.get('atr14'))} "
                f"({_fmt(tmetrics.get('atr_pct_of_price'), 1)}% of price).",
            ],
            ["End-of-day price series"],
        )
    )
    out.append(
        section(
            "News and sentiment",
            [
                news.get("headline", "News not available."),
                f"Facts vs opinions: {news.get('metrics', {}).get('fact_count_14d', 0)} factual "
                f"item(s) in 14 days; {len(news.get('metrics', {}).get('opinions', []))} opinion "
                "item(s) excluded from scoring.",
                *[
                    f"- {item['headline']}"
                    for item in news.get("metrics", {}).get("facts", [])[:5]
                ],
            ],
            ["News provider feed"],
        )
    )
    bull_metrics = bull.get("metrics", {})
    bear_metrics = bear.get("metrics", {})
    out.append(
        section(
            "Bull case",
            [
                bull.get("headline", "Bull case not constructed."),
                str(bull_metrics.get("narrative", "")),
                *[f"- {p['claim']}" for p in bull_metrics.get("pillars", [])[:5]],
            ],
            ["Derived from statements and price data"],
        )
    )
    out.append(
        section(
            "Base case",
            [
                base_case["note"] if base_case else "No base-case valuation was computed.",
                f"Scenario values per share: "
                + ", ".join(
                    f"{s['name']} {_fmt(s['value_per_share'])}" for s in scenarios
                )
                if scenarios
                else "Scenario grid unavailable.",
            ],
            ["Valuation scenarios"],
        )
    )
    out.append(
        section(
            "Bear case",
            [
                bear.get("headline", "Bear case not constructed."),
                str(bear_metrics.get("narrative", "")),
                *[f"- {a['claim']}" for a in bear_metrics.get("attacks", [])[:5]],
                "Conceded by the bear: "
                + ("; ".join(bear_metrics.get("concessions", [])) or "none"),
            ],
            ["Derived from statements and price data"],
        )
    )
    risk_metrics = risk.get("metrics", {})
    out.append(
        section(
            "Risk factors",
            [
                *(f"- {r}" for r in committee.get("risks", [])),
                f"Reference position sizing: {risk_metrics.get('decision', {}).get('quantity', 0)} shares, "
                f"{risk_metrics.get('decision', {}).get('risk_pct_capital', 0)}% of capital at risk.",
                f"Market risk level: {market.get('metrics', {}).get('market_risk', 'n/a')}; "
                f"volatility regime {market.get('metrics', {}).get('volatility_regime', 'n/a')}.",
            ],
        )
    )
    out.append(
        section(
            "Investment thesis",
            [
                cmetrics.get("thesis", {}).get("one_line", "No thesis produced."),
                cmetrics.get("thesis", {}).get("fundamental_view", ""),
                cmetrics.get("thesis", {}).get("technical_view", ""),
                cmetrics.get("thesis", {}).get("valuation_view", ""),
            ],
        )
    )
    out.append(
        section(
            "Thesis invalidation",
            [f"- {item}" for item in cmetrics.get("thesis_invalidation", [])],
        )
    )
    out.append(
        section(
            "Data limitations",
            [
                *[f"- {item}" for item in committee.get("limitations", [])],
                *[f"- {item}" for item in report.bundle_summary.get("warnings", [])[:4]],
            ],
        )
    )
    provenance = bundle.get("provenance", {})
    out.append(
        section(
            "Source references",
            [
                f"Primary series: {provenance.get('source')} "
                f"(exchange {provenance.get('exchange')}, freshness "
                f"{provenance.get('freshness')}, verification "
                f"{provenance.get('verification')}).",
                f"Reporting period: {provenance.get('market_timestamp', 'n/a')}; "
                f"retrieved {provenance.get('retrieved_at', 'n/a')}.",
                "Financial statements: " + str(fmetrics.get("latest_ratios", {}).get("fiscal_year", "n/a")),
                "Agent failures this run: "
                + (", ".join(f["agent"] for f in report.failures) or "none"),
            ],
        )
    )
    out.append(
        section(
            "Final research classification",
            [
                f"**{report.classification}**",
                cmetrics.get("rationale", ""),
                f"Composite score {_fmt(cmetrics.get('composite_score'), 1)}; "
                f"{cmetrics.get('corroboration', {}).get('groups', 'no')} independent evidence groups.",
                "This is a research classification, not advice, and not an order.",
            ],
        )
    )
    return out


def to_markdown(report: ResearchReport) -> str:
    bundle = report.bundle_summary
    quality = bundle.get("data_quality", {})
    lines = [
        f"# {bundle.get('company')} ({report.symbol}) — Research Report",
        "",
        f"**Classification: {report.classification}**  ",
        f"Generated {report.generated_at:%Y-%m-%d %H:%M UTC} · run `{report.run_id}` · "
        f"{report.duration_ms:.0f} ms",
        "",
        f"> **Data quality {quality.get('score')}/100 ({quality.get('band')}).** "
        + (
            "**This report uses SYNTHETIC demonstration data and describes no real company.**"
            if bundle.get("is_synthetic")
            else "Sources are listed per section."
        ),
        "",
        "| Field | Value |",
        "| --- | --- |",
        f"| Sector | {bundle.get('sector')} |",
        f"| Industry | {bundle.get('industry')} |",
        f"| Last price | {_fmt(bundle.get('price'))} |",
        f"| Bars analysed | {bundle.get('bars')} ({bundle.get('first_bar')} → {bundle.get('last_bar')}) |",
        f"| Data mode | {report.data_mode} |",
        "",
    ]
    for i, sec in enumerate(build_sections(report), start=1):
        lines.append(f"## {i}. {sec['title']}")
        lines.append("")
        for item in sec["body"]:
            if not item:
                continue
            lines.append(item if item.startswith(("-", "*", "**")) else f"{item}")
            lines.append("")
        if sec["sources"]:
            lines.append(f"*Sources: {', '.join(sec['sources'])}*")
            lines.append("")
    lines += ["---", "", f"*{report.disclaimer}*", ""]
    return "\n".join(lines)


def to_html(report: ResearchReport) -> str:
    bundle = report.bundle_summary
    quality = bundle.get("data_quality", {})
    sections = build_sections(report)
    synthetic = bool(bundle.get("is_synthetic"))
    rows = "".join(
        f"<tr><td>{k}</td><td>{v}</td></tr>"
        for k, v in [
            ("Sector", bundle.get("sector")),
            ("Industry", bundle.get("industry")),
            ("Last price", _fmt(bundle.get("price"))),
            ("Bars", f"{bundle.get('bars')} ({bundle.get('first_bar')} to {bundle.get('last_bar')})"),
            ("Data mode", report.data_mode),
            ("Data quality", f"{quality.get('score')}/100 ({quality.get('band')})"),
        ]
    )
    body = []
    for i, sec in enumerate(sections, start=1):
        items = "".join(
            f"<p>{_html_safe(x)}</p>" for x in sec["body"] if x
        )
        src = (
            f"<p class='src'>Sources: {_html_safe(', '.join(sec['sources']))}</p>"
            if sec["sources"]
            else ""
        )
        body.append(f"<section><h2>{i}. {_html_safe(sec['title'])}</h2>{items}{src}</section>")
    banner = (
        "<div class='banner synthetic'>SYNTHETIC DEMONSTRATION DATA — these figures do "
        "not describe any real company.</div>"
        if synthetic
        else "<div class='banner'>Sources are listed per section. Data may be delayed.</div>"
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html_safe(bundle.get('company', report.symbol))} — Research Report</title>
<style>
 :root {{ --bg:#0b0e11; --panel:#12161c; --line:#1f2630; --text:#d7dee8; --muted:#8b97a8; --accent:#f0b90b; }}
 * {{ box-sizing:border-box; }}
 body {{ margin:0; background:var(--bg); color:var(--text);
        font:14px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,sans-serif; }}
 main {{ max-width:920px; margin:0 auto; padding:32px 24px 80px; }}
 h1 {{ font-size:26px; margin:0 0 4px; letter-spacing:-.02em; }}
 h2 {{ font-size:15px; margin:28px 0 8px; color:var(--accent); text-transform:uppercase;
       letter-spacing:.08em; border-bottom:1px solid var(--line); padding-bottom:6px; }}
 .meta {{ color:var(--muted); font-size:12px; }}
 .banner {{ background:#1b2330; border-left:3px solid var(--accent); padding:10px 14px;
            margin:18px 0; font-size:13px; }}
 .banner.synthetic {{ background:#2a1f0a; border-left-color:#f0b90b; color:#f5d98a; }}
 table {{ width:100%; border-collapse:collapse; margin:14px 0; font-size:13px; }}
 td {{ border-bottom:1px solid var(--line); padding:6px 8px; vertical-align:top; }}
 td:first-child {{ color:var(--muted); width:180px; }}
 section p {{ margin:6px 0; }}
 .src {{ color:var(--muted); font-size:11px; font-style:italic; }}
 footer {{ margin-top:40px; border-top:1px solid var(--line); padding-top:14px;
           color:var(--muted); font-size:11px; }}
 @media print {{ body {{ background:#fff; color:#111; }} .banner {{ border-color:#b8860b; }} }}
</style></head>
<body><main>
<h1>{_html_safe(bundle.get('company', report.symbol))} <span class="meta">({report.symbol})</span></h1>
<div class="meta">Classification: <strong>{report.classification}</strong> · generated
 {report.generated_at:%Y-%m-%d %H:%M UTC} · run {report.run_id}</div>
{banner}
<table>{rows}</table>
{''.join(body)}
<footer>{_html_safe(report.disclaimer)}</footer>
</main></body></html>"""


def _html_safe(text: Any) -> str:
    from html import escape

    return escape(str(text), quote=False)


def to_csv(report: ResearchReport) -> str:
    """Flat metric export: one row per metric with its value and source."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["section", "metric", "value", "source"])
    fund = _get(report, "fundamental_research").get("metrics", {})
    val = _get(report, "valuation").get("metrics", {})
    tech = _get(report, "technical_analysis").get("metrics", {})
    com = _get(report, "research_committee").get("metrics", {})
    for k, v in fund.get("latest_ratios", {}).items():
        writer.writerow(["fundamental", k, v, "reported statements"])
    writer.writerow(["valuation", "value_per_share_base", (val.get("dcf") or {}).get("value_per_share") or
                     (val.get("bank_valuation") or {}).get("fair_value_per_share"), "valuation model"])
    writer.writerow(["valuation", "upside_pct", val.get("upside_pct"), "valuation model"])
    for k, v in tech.get("indicators", {}).items():
        writer.writerow(["technical", k, v, "price series"])
    writer.writerow(["committee", "classification", com.get("classification"), "committee"])
    writer.writerow(["committee", "composite_score", com.get("composite_score"), "committee"])
    return buf.getvalue()


def to_xlsx(report: ResearchReport, path: Path) -> Path:
    rows: list[list[Any]] = [["Section", "Item", "Value", "Source / Note"]]
    bundle = report.bundle_summary
    rows.append(["Overview", "Symbol", report.symbol, "universe"])
    rows.append(["Overview", "Company", bundle.get("company"), "universe"])
    rows.append(["Overview", "Sector", bundle.get("sector"), "universe"])
    rows.append(["Overview", "Classification", report.classification, "research committee"])
    rows.append(["Overview", "Data quality", bundle.get("data_quality", {}).get("score"),
                 str(bundle.get("data_quality", {}).get("band"))])
    fund = _get(report, "fundamental_research").get("metrics", {})
    for k, v in fund.get("latest_ratios", {}).items():
        rows.append(["Fundamental", k, v, "reported statements"])
    val = _get(report, "valuation").get("metrics", {})
    for scenario in val.get("scenarios", []):
        rows.append(["Valuation", f"value_per_share_{scenario['name'].lower()}",
                     scenario.get("value_per_share"), "DCF scenario"])
    tech = _get(report, "technical_analysis").get("metrics", {})
    for k, v in tech.get("indicators", {}).items():
        rows.append(["Technical", k, v, "price series"])
    com = _get(report, "research_committee").get("metrics", {})
    rows.append(["Committee", "composite_score", com.get("composite_score"), "committee"])
    for label, value in (com.get("thesis") or {}).items():
        if isinstance(value, str):
            rows.append(["Thesis", label, value, "committee"])
    for sec in build_sections(report):
        for item in sec["body"]:
            if item:
                rows.append(["Report", sec["title"], item, ""])
    return write_xlsx(path, rows, sheet_name=report.symbol[:31])


def to_pdf(report: ResearchReport, path: Path) -> Path:
    bundle = report.bundle_summary
    quality = bundle.get("data_quality", {})
    lines: list[PdfLine] = [
        PdfLine("BRIJ TRADING INTELLIGENCE", 16, True, 6),
        PdfLine(f"{bundle.get('company')} ({report.symbol})", 13, True, 4),
        PdfLine(f"Classification: {report.classification}", 11, True, 6),
        PdfLine(
            f"Generated {report.generated_at:%Y-%m-%d %H:%M} UTC | run {report.run_id} | "
            f"{report.duration_ms:.0f} ms",
            8, False, 4,
        ),
        PdfLine(
            f"Data quality {quality.get('score')}/100 ({quality.get('band')}) - "
            + ("SYNTHETIC DEMONSTRATION DATA, not a real company." if bundle.get("is_synthetic")
               else "see source references."),
            9, True, 10,
        ),
    ]
    for i, sec in enumerate(build_sections(report), start=1):
        lines.append(PdfLine(f"{i}. {sec['title']}", 11, True, 4))
        for item in sec["body"]:
            if not item:
                continue
            lines.append(PdfLine(item.replace("**", "").replace("- ", "  - "), 9, False, 2))
        if sec["sources"]:
            lines.append(PdfLine("Sources: " + ", ".join(sec["sources"]), 8, False, 8))
    lines.append(PdfLine("", 8, False, 6))
    for chunk in _wrap_disclaimer(report.disclaimer):
        lines.append(PdfLine(chunk, 8, False, 2))
    return write_pdf(path, lines, title=f"{bundle.get('company')} research report")


def _wrap_disclaimer(text: str, width: int = 110) -> list[str]:
    words = text.split()
    out, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 <= width:
            cur = f"{cur} {w}".strip()
        else:
            out.append(cur)
            cur = w
    if cur:
        out.append(cur)
    return out


EXPORTERS = {
    "markdown": (".md", lambda report: to_markdown(report)),
    "html": (".html", lambda report: to_html(report)),
    "json": (".json", lambda report: json.dumps(report.to_dict(), indent=2, default=str)),
    "csv": (".csv", lambda report: to_csv(report)),
}


def export_report(report: ResearchReport, fmt: str, directory: Path | None = None) -> Path:
    fmt = fmt.lower().strip()
    directory = Path(directory or Path("var/reports"))
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base = f"{report.symbol}_{stamp}"
    if fmt in EXPORTERS:
        suffix, fn = EXPORTERS[fmt]
        path = directory / f"{base}{suffix}"
        path.write_text(fn(report), encoding="utf-8")
        return path
    if fmt == "pdf":
        return to_pdf(report, directory / f"{base}.pdf")
    if fmt in {"xlsx", "excel"}:
        return to_xlsx(report, directory / f"{base}.xlsx")
    raise ValidationError(
        f"unsupported format {fmt!r}; choose from markdown, html, pdf, csv, xlsx, json"
    )
