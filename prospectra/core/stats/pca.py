# 2026-07-13 (P3): Principal Component Analysis, with a narrative that explains what it actually
# tells you.
#
# WHAT PCA IS: it finds the directions along which your columns vary together. With 20 correlated
# columns, the first few components often capture most of the variation, so you can look at 3
# numbers instead of 20.
#
# WHAT PCA IS NOT: it is *unsupervised* — it never looks at your target. It cannot tell you "what
# drives sales." A component can carry 60% of the variance and have nothing to do with sales. For
# "what drives X", the regression ladder (`regression.py`) and the multivariate model
# (`multivariate.py`) are the tools. The UI repeats this warning; so does `narrative()`.
#
# Columns are standardized first (mean 0, sd 1), otherwise a column measured in dollars would
# dominate one measured in degrees purely because its numbers are bigger.

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.decomposition import PCA as SkPCA
from sklearn.preprocessing import StandardScaler

MIN_ROWS = 10
MIN_COLUMNS = 3
STRONG_LOADING = 0.35  # |loading| worth naming in the narrative


@dataclass(frozen=True)
class Component:
    index: int  # 1-based: PC1, PC2, …
    explained: float  # share of total variance (0..1)
    cumulative: float
    loadings: dict[str, float]  # column -> loading on this component

    @property
    def label(self) -> str:
        return f"PC{self.index}"

    def drivers(self, limit: int = 3) -> list[tuple[str, float]]:
        ranked = sorted(self.loadings.items(), key=lambda kv: abs(kv[1]), reverse=True)
        return [(name, value) for name, value in ranked[:limit] if abs(value) >= STRONG_LOADING]


@dataclass(frozen=True)
class PCAResult:
    columns: list[str]
    n: int
    components: list[Component]
    scores: list[list[float]]  # rows x components (first two, for the biplot)
    narrative: str

    @property
    def components_for_90pct(self) -> int:
        for component in self.components:
            if component.cumulative >= 0.90:
                return component.index
        return len(self.components)


def run_pca(frame: pd.DataFrame, numeric: list[str], max_components: int = 8) -> PCAResult | None:
    usable = [c for c in numeric if frame[c].notna().sum() > 0]
    if len(usable) < MIN_COLUMNS:
        return None
    data = frame[usable].dropna()
    if len(data) < MIN_ROWS:
        return None
    # Drop zero-variance columns: they carry no information and break standardization.
    varying = [c for c in usable if float(data[c].std()) > 0]
    if len(varying) < MIN_COLUMNS:
        return None
    data = data[varying]

    scaled = StandardScaler().fit_transform(data.to_numpy(dtype=float))
    n_components = min(len(varying), max_components, len(data))
    model = SkPCA(n_components=n_components).fit(scaled)
    scores = model.transform(scaled)

    components: list[Component] = []
    cumulative = 0.0
    for i, ratio in enumerate(model.explained_variance_ratio_):
        cumulative += float(ratio)
        components.append(
            Component(
                index=i + 1,
                explained=float(ratio),
                cumulative=min(cumulative, 1.0),
                loadings={
                    name: float(value)
                    for name, value in zip(varying, model.components_[i], strict=True)
                },
            )
        )

    return PCAResult(
        columns=varying,
        n=len(data),
        components=components,
        scores=[[float(v) for v in row[:2]] for row in scores],
        narrative=narrative(components, varying),
    )


def _describe(name: str, loading: float) -> str:
    return f"{name} ({loading:+.2f})"


def narrative(components: list[Component], columns: list[str]) -> str:
    """Plain-English reading of the components — written for someone who has never used PCA."""
    if not components:
        return ""
    lines: list[str] = [
        f"PCA looked at {len(columns)} numeric columns together and found the directions your "
        "data varies in most. Each 'component' is a blend of columns that tend to move as a group.",
        "",
    ]
    for component in components[:3]:
        drivers = component.drivers()
        if drivers:
            same_sign = len({value > 0 for _n, value in drivers}) == 1
            blend = ", ".join(_describe(name, value) for name, value in drivers)
            movement = (
                "these move together"
                if same_sign
                else "these move in opposite directions (the sign says which way)"
            )
            lines.append(
                f"{component.label} captures {component.explained:.0%} of the variation, driven "
                f"mostly by {blend} — {movement}."
            )
        else:
            lines.append(
                f"{component.label} captures {component.explained:.0%} of the variation, spread "
                "thinly across many columns rather than driven by a few."
            )

    for component in components:
        if component.cumulative >= 0.90:
            lines.append("")
            lines.append(
                f"The first {component.index} component(s) account for "
                f"{component.cumulative:.0%} of all variation — that is how much of this dataset "
                f"you can summarize with {component.index} number(s) instead of {len(columns)}."
            )
            break

    lines.append("")
    lines.append(
        "Important: PCA never looked at your target column. It describes how your columns vary "
        "together, NOT what causes or predicts an outcome. For that, use the 'What drives…' tab."
    )
    return "\n".join(lines)
