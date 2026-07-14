# 2026-07-13 (P4): "Data point A and data point X move together — why?"
#
# This is the feature that turns a statistic into an insight, and it is also the easiest place in
# the whole app to do harm. A confident-sounding causal story attached to a correlation is exactly
# what a data-mining tool should never produce. So the prompt is built to force the opposite:
# every answer must offer competing explanations, must name a plausible confounder, and must state
# what evidence would distinguish them. The output is labelled a hypothesis in the UI, never a
# conclusion.
#
# Only the finding's *summary statistics* are sent — the column names, the effect size, the
# headline. No rows, at any privacy level, because this call goes out to a web-search-enabled
# model and the search query itself would otherwise be a leak.

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from prospectra.core.llm.base import Citation, LLMError, Message, Provider
from prospectra.core.mining import Finding

logger = logging.getLogger(__name__)

SYSTEM = """You explain why two things in a dataset might move together.

You will be given ONE statistical finding: the columns involved, the kind of relationship, and how
strong it is. You will NOT be given the underlying data, and you must not ask for it.

Your job:
1. Offer 2-4 competing explanations for the pattern. For each, say plainly what would have to be
   true for it to be the right one.
2. At least one explanation must be a CONFOUNDER — a third factor that would produce this exact
   pattern with no causal link between the two columns at all. If a confounder is obvious, name it
   first.
3. Where a real-world mechanism is involved, search the web and cite what you find. Cite sources
   for claims about the world; do not cite anything for claims about the user's data.
4. Say what evidence would tell these explanations apart — what to measure, what to control for,
   what an experiment would look like.

Rules:
- These are HYPOTHESES. Never assert that one column causes another. The data cannot show that,
  and neither can you.
- Say when you don't know. A short honest answer beats a long confident one.
- Plain English. The reader is smart but is not a statistician.
"""

USER = """Finding from the dataset "{dataset}":

{headline}

Details:
- Columns involved: {columns}
- Kind: {kind}
- Effect size: {effect:.3f} ({effect_name})
- Statistical significance after multiple-testing correction: q = {q_value:.2e}
- Rows analysed: {n:,}
{extra}
Why might these move together? Remember to include a confounder and to cite real-world claims."""


@dataclass
class Hypotheses:
    finding_title: str
    text: str
    citations: list[Citation] = field(default_factory=list)
    searched_web: bool = False

    @property
    def disclaimer(self) -> str:
        return (
            "These are hypotheses, not conclusions. The statistics show an association; they "
            "cannot show what causes it."
        )


def explain_finding(
    provider: Provider,
    finding: Finding,
    dataset_name: str = "your data",
    column_context: dict[str, str] | None = None,
) -> Hypotheses:
    """Ask the model why a finding might hold, grounded in cited sources where possible."""
    extra = ""
    if column_context:
        described = "\n".join(f"- {name}: {desc}" for name, desc in column_context.items())
        extra = f"\nWhat the columns mean:\n{described}\n"

    question = USER.format(
        dataset=dataset_name,
        headline=finding.headline,
        columns=", ".join(finding.columns),
        kind=finding.kind,
        effect=finding.effect,
        effect_name=finding.effect_name,
        q_value=finding.q_value,
        n=finding.n,
        extra=extra,
    )

    use_web = provider.supports_web_search
    if not use_web:
        logger.info(
            "%s has no web search in this build — hypotheses will be uncited.",
            provider.display_name,
        )

    try:
        reply = provider.complete(
            SYSTEM, [Message(role="user", text=question)], tools=None, web_search=use_web
        )
    except LLMError:
        raise
    return Hypotheses(
        finding_title=finding.title,
        text=reply.text,
        citations=list(reply.citations),
        searched_web=use_web,
    )
