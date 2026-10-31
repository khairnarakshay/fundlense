# ai_intelligence/prompts/portfolio_report.py
"""
Prompt for the dashboard portfolio report (structured, multi-section) - as
opposed to prompts/system.py's freeform chat prompt. Both share the same
policy rules (domain/policies.py) and the same grounding block, so the facts
the model sees are identical in both places.
"""
from langchain_core.messages import HumanMessage, SystemMessage

from ai_intelligence.domain.policies import render_rules
from ai_intelligence.domain.schemas import PortfolioAnalysisResult
from ai_intelligence.prompts.system import build_grounding_context

REPORT_INSTRUCTIONS = (
    "You are writing the portfolio report shown on the investor's Fundlense dashboard. "
    "Write a detailed, plain-language report using ONLY the verified data below, and "
    "fill every field of the requested structure.\n\n"
    "Rules you must follow:\n" + render_rules() + "\n"
    "- Do NOT perform any new calculation. Quote numbers exactly as given below.\n\n"
    "What each field should contain:\n"
    "- overview: total value, amount invested, gain or loss and gain %, number of holdings, and the as-of date.\n"
    "- performance: which holdings contribute most to gains and to losses (use the per-holding gain figures). "
    "Mention a fund's 1Y return / 3Y CAGR where given, and state clearly that these describe the FUND's market "
    "performance, not the investor's personal return (personal XIRR is not available).\n"
    "- allocation_and_diversification: asset-type and AMC allocation, and what the concentration index indicates.\n"
    "- concentration_and_risk: largest holding and largest AMC exposure. The volatility figure is a value-weighted "
    "average of each fund's own volatility, not true portfolio volatility - say so if you mention it.\n"
    "- cost_observations: the weighted expense ratio, and any holdings whose expense ratio is notably higher or "
    "lower than the others (facts only).\n"
    "- data_quality_notes: every warning and every 'not computed' item that affects how much weight the reader "
    "should put on this report.\n"
    "- points_to_review: 2 to 5 neutral observations or questions the investor may want to look into themselves "
    "(for example 'X% of the value sits in one fund'). Never phrase them as instructions to buy, sell, switch or redeem."
)


def build_report_messages(analysis: PortfolioAnalysisResult) -> list:
    system_content = REPORT_INSTRUCTIONS + "\n\n" + build_grounding_context(analysis)
    return [SystemMessage(content=system_content), HumanMessage(content="Write the portfolio report.")]