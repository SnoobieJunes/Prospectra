# 2026-07-13 (P4): The hypothesis engine — takes a finding and asks "why might this be?", using
# web search to ground the answer in citable sources.
from prospectra.core.explain.hypothesis import Hypotheses, explain_finding

__all__ = ["Hypotheses", "explain_finding"]
