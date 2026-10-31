# ai_intelligence/domain/policies.py
"""
Centralized, non-negotiable rules for the AI layer - the single source of
truth so every prompt (chat today; future portfolio-summary narration,
future RAG answers) states the same rules instead of each prompt file
keeping its own copy that can quietly drift out of sync.

IMPORTANT DISTINCTION, read before adding to this file:

PROMPT-LEVEL RULES (below) are instructions GIVEN TO the model. They shape
its behavior but are not an airtight guarantee - a sufficiently adversarial
input could in principle get a model to ignore them. They are the right tool
for "don't recommend buying a fund," "don't guess a number you weren't
given" - judgment calls about HOW the model should talk.

SECURITY INVARIANTS (below) are enforced in CODE - never by asking the model
nicely. "Never show user A's portfolio to user B" is NOT a prompt rule in
this app; it's a structural fact about how every query is scoped. No prompt
instruction is a substitute for an invariant that belongs here.
"""

# ---------------------------------------------------------------------------
# PROMPT-LEVEL RULES
# ---------------------------------------------------------------------------

NO_FINANCIAL_ADVICE_RULE = (
    "Do not recommend buying, selling, switching, or redeeming any specific fund. "
    "Do not call a fund \"good\" or \"bad\" in absolute terms. Do not predict future "
    "returns or guarantee performance. You analyze and explain information that is "
    "given to you - you do not give personalized investment advice."
)

GROUNDED_ONLY_RULE = (
    "Use ONLY the verified data provided to you. Never invent holdings, values, "
    "NAVs, transactions, returns, or scheme details that aren't given to you. If "
    "something needed to answer is missing or not computed, say so plainly instead "
    "of guessing or estimating it."
)

FACTS_VS_INTERPRETATION_RULE = (
    "Clearly distinguish between (a) facts and numbers from the data provided, and "
    "(b) your own interpretation or explanation of those facts."
)

CONCISE_RULE = "Keep answers concise and focused on what was actually asked."

ALL_RULES = [NO_FINANCIAL_ADVICE_RULE, GROUNDED_ONLY_RULE, FACTS_VS_INTERPRETATION_RULE, CONCISE_RULE]


# Shown alongside every generated report so the dashboard always displays it -
# a code-level constant, not something the model is trusted to remember to say.
DISCLAIMER = (
    "This report is an automated analysis of the statements you uploaded. It is "
    "educational information, not investment advice, and does not recommend buying, "
    "selling or switching any fund."
)


def render_rules() -> str:
    """Renders ALL_RULES as a bulleted list for inclusion in any system prompt -
    chat today, and later the portfolio-summary narration and RAG-answer
    prompts should call this too, instead of restating the rules themselves."""
    return "\n".join(f"- {rule}" for rule in ALL_RULES)


# ---------------------------------------------------------------------------
# SECURITY INVARIANTS - enforced in CODE. Documented here as a checklist for
# every new endpoint/service added to this app; the code does not read this
# file at runtime, this is the standard every PR against ai_intelligence
# should be checked against.
# ---------------------------------------------------------------------------

SECURITY_INVARIANTS = """
1. Every AI endpoint requires IsAuthenticated - no anonymous access.
2. The user whose data is used is ALWAYS request.user - never a user id taken
   from the request body, query params, headers, or any other client-supplied
   value. A conversation/analysis/memory id in a URL is data to look up, not
   proof of ownership - it must always be combined with a filter on
   request.user before anything is read, updated, or deleted.
3. build_portfolio_snapshot(user) and every portfolio.services function it
   calls are scoped to one user via their own queryset filters
   (folio__statement__user=user). There is no code path in this app that can
   query another user's CASStatement/CASFolio/CASSchemeHolding/CASTransaction.
4. Error responses never include another user's data, another user's id, or
   internal stack traces - views.py returns generic messages and logs detail
   server-side only.
5. Future RAG/document retrieval (deferred) must apply the same rule:
   access-control filtering happens in the query, before content reaches the
   model - never "ask the model not to use document X."
"""