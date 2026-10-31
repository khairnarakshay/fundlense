# ai_intelligence/prompts/system.py
"""
Static instructions given TO the LLM, and the template that grounds them in one
user's verified PortfolioAnalysisResult (Phase 3). No LLM-generated content ever
lives in this file - only what we tell the model, built fresh per request.
"""
from ai_intelligence.domain.policies import render_rules
from ai_intelligence.domain.schemas import PortfolioAnalysisResult

BASE_SYSTEM_PROMPT = (
    "You are a portfolio assistant for Fundlense, a mutual fund portfolio tracking platform.\n\n"
    "Rules you must follow:\n" + render_rules() + "\n"
    "- If the portfolio has no holdings, or the data is insufficient to answer the question, say that directly."
)


def build_grounding_context(analysis: PortfolioAnalysisResult) -> str:
    """
    Renders a PortfolioAnalysisResult as a compact, labeled text block - every
    number here is copied verbatim from `analysis`, never rephrased or
    recalculated, so the model has no room to quietly drift from the
    deterministic figures Phase 3 computed.
    """
    lines = [f"PORTFOLIO DATA (as of {analysis.as_of.isoformat()}):"]

    if analysis.holdings_count == 0:
        lines.append("This user currently has no holdings on record.")
        return "\n".join(lines)

    lines.append(f"- Total current value: {analysis.total_value}")
    lines.append(f"- Total invested (cost): {analysis.total_cost}")
    gain_line = f"- Total gain: {analysis.total_gain}"
    if analysis.total_gain_percent is not None:
        gain_line += f" ({analysis.total_gain_percent}%)"
    lines.append(gain_line)
    lines.append(f"- Number of holdings: {analysis.holdings_count}")
    if analysis.expense_ratio_weighted is not None:
        lines.append(f"- Value-weighted expense ratio: {analysis.expense_ratio_weighted}%")

    if analysis.allocation_by_asset_type:
        lines.append("Allocation by asset type:")
        lines += [f"  - {a.label}: {a.percent}%" for a in analysis.allocation_by_asset_type]

    if analysis.allocation_by_amc:
        lines.append("Allocation by AMC:")
        lines += [f"  - {a.label}: {a.percent}%" for a in analysis.allocation_by_amc]

    c = analysis.concentration
    if c.top_holding_name:
        lines.append(f"- Largest single holding: {c.top_holding_name} ({c.top_holding_percent}% of portfolio)")
    if c.top_amc_name:
        lines.append(f"- Largest AMC exposure: {c.top_amc_name} ({c.top_amc_percent}% of portfolio)")
    if c.herfindahl_index is not None:
        lines.append(f"- Concentration index (HHI): {c.herfindahl_index} - {c.herfindahl_label}")

    if analysis.holdings:
        lines.append("Holdings (largest first). Return figures are the FUND's own market "
                     "performance, NOT this investor's personal return:")
        for h in analysis.holdings:
            meta = h.amc_name + (f", {h.category}" if h.category else "")
            if h.weight_percent is None:
                lines.append(f"  - {h.scheme_name} ({meta}): no live price available, "
                             f"excluded from value-based figures")
                continue
            parts = [f"value {h.market_value}", f"weight {h.weight_percent}%"]
            if h.cost_basis is not None:
                parts.append(f"cost {h.cost_basis}")
            if h.gain is not None:
                gain_text = f"gain {h.gain}"
                if h.gain_percent is not None:
                    gain_text += f" ({h.gain_percent}%)"
                parts.append(gain_text)
            if h.ret_1y is not None:
                parts.append(f"fund 1Y return {h.ret_1y}%")
            if h.cagr_3y is not None:
                parts.append(f"fund 3Y CAGR {h.cagr_3y}%")
            if h.expense_ratio is not None:
                parts.append(f"expense ratio {h.expense_ratio}%")
            lines.append(f"  - {h.scheme_name} ({meta}): " + ", ".join(parts))

    if analysis.portfolio_weighted_volatility_1y is not None:
        lines.append(f"- Value-weighted 1Y volatility (proxy, NOT true portfolio volatility - correlation "
                     f"between funds isn't factored in): {analysis.portfolio_weighted_volatility_1y}%")

    if analysis.warnings:
        lines.append("Data warnings (mention these if relevant to the question):")
        lines += [f"  - {w.message}" for w in analysis.warnings]

    if analysis.not_computed:
        lines.append(f"NOT available / not computed yet: {', '.join(analysis.not_computed)}. "
                     f"If the question needs one of these, say it isn't available instead of estimating it.")

    return "\n".join(lines)