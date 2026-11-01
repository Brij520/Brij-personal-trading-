"""AGENT 09 — Forensic Accounting.

Looks for *inconsistencies inside the reported numbers* rather than opinions
about the company. Each check states what would count as a red flag, the
observed value, and the threshold used. Fewer false positives matters more than
catching everything: a flag here is a reason to read the annual report, not a
conclusion of fraud.

Checks implemented
------------------
1.  Revenue growth vs receivables growth (channel stuffing indicator).
2.  Revenue growth vs inventory growth (unsold-goods indicator).
3.  CFO vs PAT across the series (earnings quality / accrual gap).
4.  Cash-flow identity: CFO should be positive in most years.
5.  Effective tax rate dispersion (tax-rate games).
6.  Debt growth vs EBITDA growth (leverage creep).
7.  Promoter pledge, auditor changes/qualification, related-party intensity,
    contingent liabilities, equity dilution, capex anomaly.
8.  Margin volatility versus revenue volatility (margin smoothing).
"""

from __future__ import annotations

import numpy as np

from backend.agents.base import AgentContext, AgentFinding, BaseAgent, Evidence
from backend.agents.helpers import bundle_from
from backend.core.provenance import Freshness, Verification


class ForensicAccountingAgent(BaseAgent):
    name = "forensic_accounting"
    responsibility = "Accounting red flags and earnings-quality investigation"
    requires = ("statements", "holdings", "auditor")

    SEVERITY_POINTS = {"CRITICAL": -30, "HIGH": -18, "MEDIUM": -9, "LOW": -4}

    def run(self, ctx: AgentContext) -> AgentFinding:
        bundle = bundle_from(ctx)
        f = bundle.fundamentals
        a = bundle.analysis
        is_syn = bundle.is_synthetic
        freshness = Freshness.SYNTHETIC if is_syn else Freshness.EOD
        verification = (
            Verification.UNVERIFIED_SYNTHETIC if is_syn else Verification.VERIFIED_PRIMARY
        )

        flags: list[dict[str, object]] = []
        clean_checks: list[str] = []
        evidence: list[Evidence] = []

        def add_flag(check: str, severity: str, detail: str, observed: float, threshold: str) -> None:
            flags.append(
                {
                    "check": check,
                    "severity": severity,
                    "detail": detail,
                    "observed": round(float(observed), 2),
                    "threshold": threshold,
                }
            )
            evidence.append(
                Evidence(
                    claim=f"{check}: {detail}",
                    value=round(float(observed), 2),
                    source=f.provenance.source,
                    as_of=f.provenance.reporting_period,
                    freshness=freshness,
                    verification=verification,
                    is_synthetic=is_syn,
                )
            )

        annual = f.annual
        if len(annual) < 3:
            return AgentFinding(
                agent=self.name,
                symbol=bundle.symbol,
                headline="Insufficient statement history for forensic checks",
                stance="INSUFFICIENT_DATA",
                score=0.0,
                confidence=0.1,
                limitations=["Need at least three fiscal years of statements."],
                data_quality=bundle.data_quality,
                metrics={"flags": [], "clean_checks": []},
            )

        cur, prev = annual[-1], annual[-2]

        # 1. receivables vs revenue
        rev_g = (cur.revenue / prev.revenue - 1) if prev.revenue else 0.0
        rec_g = (cur.receivables / prev.receivables - 1) if prev.receivables else 0.0
        if cur.receivables and abs(rev_g) > 1e-6 and rec_g - rev_g > 0.15:
            add_flag(
                "Receivables growing faster than revenue",
                "HIGH" if rec_g - rev_g > 0.30 else "MEDIUM",
                f"receivables {rec_g * 100:+.1f}% vs revenue {rev_g * 100:+.1f}%",
                (rec_g - rev_g) * 100,
                "gap > 15pp",
            )
        else:
            clean_checks.append("Receivables growth in line with revenue growth.")

        # 2. inventory vs revenue
        if cur.inventory and prev.inventory:
            inv_g = cur.inventory / prev.inventory - 1
            if inv_g - rev_g > 0.25:
                add_flag(
                    "Inventory building ahead of sales",
                    "MEDIUM",
                    f"inventory {inv_g * 100:+.1f}% vs revenue {rev_g * 100:+.1f}%",
                    (inv_g - rev_g) * 100,
                    "gap > 25pp",
                )
            else:
                clean_checks.append("Inventory growth consistent with revenue.")
        else:
            clean_checks.append("No inventory line (service or lending business).")

        # 3/4. accrual quality over the whole series
        cfo_pat = [x.cfo / x.pat for x in annual if x.pat > 0]
        if cfo_pat:
            mean_cfo_pat = float(np.mean(cfo_pat))
            if mean_cfo_pat < 0.7:
                add_flag(
                    "Cumulative cash conversion weak",
                    "HIGH" if mean_cfo_pat < 0.5 else "MEDIUM",
                    f"average CFO/PAT {mean_cfo_pat:.2f} over {len(cfo_pat)} years",
                    mean_cfo_pat,
                    "< 0.70",
                )
            else:
                clean_checks.append(f"Average CFO/PAT {mean_cfo_pat:.2f} — earnings cash-backed.")
        negative_cfo = sum(1 for x in annual if x.cfo < 0)
        if negative_cfo >= 2:
            add_flag(
                "Repeated negative operating cash flow",
                "HIGH",
                f"{negative_cfo} of {len(annual)} years had negative CFO",
                negative_cfo,
                ">= 2 years",
            )

        # 5. tax rate dispersion
        tax_rates = []
        for x in annual:
            if x.ebit and x.ebit > 0 and x.pat:
                rate = 1 - x.pat / (x.ebit - x.interest_expense)
                if 0 < rate < 0.6:
                    tax_rates.append(rate)
        if len(tax_rates) >= 3 and float(np.std(tax_rates)) > 0.08:
            add_flag(
                "Volatile effective tax rate",
                "LOW",
                f"effective tax rate standard deviation {np.std(tax_rates) * 100:.1f}pp",
                float(np.std(tax_rates)) * 100,
                "> 8pp",
            )

        # 6. debt creep
        if prev.total_debt and prev.ebitda and cur.ebitda:
            debt_g = cur.total_debt / prev.total_debt - 1
            ebitda_g = cur.ebitda / prev.ebitda - 1
            if debt_g - ebitda_g > 0.25:
                add_flag(
                    "Debt rising faster than EBITDA",
                    "MEDIUM",
                    f"debt {debt_g * 100:+.1f}% vs EBITDA {ebitda_g * 100:+.1f}%",
                    (debt_g - ebitda_g) * 100,
                    "gap > 25pp",
                )

        # 7. governance / disclosure flags
        if f.promoter_pledge_pct > 15:
            add_flag("High promoter pledge", "CRITICAL",
                     f"{f.promoter_pledge_pct:.1f}% of promoter holding pledged",
                     f.promoter_pledge_pct, "> 15%")
        elif f.promoter_pledge_pct > 5:
            add_flag("Promoter pledge present", "MEDIUM",
                     f"{f.promoter_pledge_pct:.1f}% of promoter holding pledged",
                     f.promoter_pledge_pct, "> 5%")
        if f.auditor_qualification:
            add_flag("Auditor qualification", "CRITICAL", f.auditor_qualification, 1, "any")
        if f.auditor_changes_5y >= 2:
            add_flag("Frequent auditor changes", "HIGH",
                     f"{f.auditor_changes_5y} auditor changes in five years",
                     f.auditor_changes_5y, ">= 2")
        if f.related_party_txn_pct_revenue > 10:
            add_flag("Heavy related-party transactions", "MEDIUM",
                     f"{f.related_party_txn_pct_revenue:.1f}% of revenue",
                     f.related_party_txn_pct_revenue, "> 10%")
        if f.contingent_liabilities_pct_equity > 25:
            add_flag("Large contingent liabilities", "MEDIUM",
                     f"{f.contingent_liabilities_pct_equity:.1f}% of equity",
                     f.contingent_liabilities_pct_equity, "> 25%")
        if f.equity_dilution_pct_3y > 10:
            add_flag("Equity dilution", "MEDIUM",
                     f"{f.equity_dilution_pct_3y:.1f}% share count increase over three years",
                     f.equity_dilution_pct_3y, "> 10%")

        # 8. capex anomaly
        capex_ratio = cur.capex / cur.revenue if cur.revenue else 0
        hist_ratio = float(np.median([x.capex / x.revenue for x in annual[:-1] if x.revenue]))
        if hist_ratio > 0 and capex_ratio > hist_ratio * 2 and capex_ratio > 0.08:
            add_flag("Capex spike", "MEDIUM",
                     f"capex {capex_ratio * 100:.1f}% of revenue vs {hist_ratio * 100:.1f}% median",
                     capex_ratio * 100, "> 2x median")

        # 9. margin smoothing
        margins = [x.ebitda / x.revenue for x in annual if x.revenue]
        rev_growths = [annual[i].revenue / annual[i - 1].revenue - 1 for i in range(1, len(annual))]
        if len(margins) >= 3 and float(np.std(rev_growths, ddof=1)) > 0.12 and float(np.std(margins, ddof=1)) < 0.008:
            add_flag("Unusually stable margins in volatile revenue", "LOW",
                     "margin volatility far below revenue volatility",
                     float(np.std(margins, ddof=1)) * 100, "< 0.8pp")

        if not flags:
            evidence.append(
                Evidence(
                    claim=(
                        "No material inconsistency across the "
                        f"{len(clean_checks)} checks performed "
                        "(cash conversion, receivables, inventory, leverage, "
                        "governance inputs)"
                    ),
                    source=f.provenance.source,
                    as_of=f.provenance.reporting_period,
                    freshness=freshness,
                    verification=verification,
                    is_synthetic=is_syn,
                )
            )
        penalty = sum(self.SEVERITY_POINTS[str(fl["severity"])] for fl in flags)
        score = float(np.clip(penalty, -100, 0))
        critical = [fl for fl in flags if fl["severity"] in {"CRITICAL", "HIGH"}]
        if critical:
            stance = "BEARISH"
        elif flags:
            stance = "NEUTRAL"
        else:
            stance = "NEUTRAL"

        headline = (
            f"{len(flags)} forensic flag(s) — "
            + (
                ", ".join(str(fl["check"]) for fl in flags[:2])
                if flags
                else "no material accounting inconsistency detected in the reported numbers"
            )
        )

        limitations = [
            "Only reported statements are examined: notes to accounts, contingent "
            "liability detail, related-party schedules and segment disclosures are "
            "not parsed.",
            "A flag is an inconsistency requiring investigation, not evidence of fraud.",
            "Benford's-law and journal-entry testing need transaction-level data that "
            "is not available.",
        ]
        if a.is_financial:
            limitations.append(
                "Lending businesses need provisioning and NPA ageing analysis, which is "
                "not in this dataset."
            )
        if is_syn:
            limitations.append("All statements are synthetic demonstration data.")

        return AgentFinding(
            agent=self.name,
            symbol=bundle.symbol,
            headline=headline,
            stance=stance if not critical else "BEARISH",
            score=score,
            confidence=self._quality_cap(bundle.data_quality["score"]) * (0.9 if flags else 0.7),
            evidence=evidence,
            risks=[str(fl["detail"]) for fl in flags],
            limitations=limitations,
            data_quality=bundle.data_quality,
            metrics={
                "flags": flags,
                "clean_checks": clean_checks,
                "flag_count": len(flags),
                "critical_count": len(critical),
                "cfo_pat_mean": None if not cfo_pat else round(float(np.mean(cfo_pat)), 2),
                "governance": {
                    "promoter_holding_pct": f.promoter_holding_pct,
                    "promoter_pledge_pct": f.promoter_pledge_pct,
                    "auditor_changes_5y": f.auditor_changes_5y,
                    "auditor_qualification": f.auditor_qualification,
                    "related_party_pct_revenue": f.related_party_txn_pct_revenue,
                    "contingent_liab_pct_equity": f.contingent_liabilities_pct_equity,
                    "equity_dilution_pct_3y": f.equity_dilution_pct_3y,
                },
            },
            warnings=[
                "Forensic scores are negative-only by design: this agent can lower "
                "confidence but never adds credit for 'looking clean'."
            ],
        )
