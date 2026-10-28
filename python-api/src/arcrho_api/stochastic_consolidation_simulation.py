"""Canonical numeric engine for Arco Stochastic Consolidation methods.

A Stochastic Consolidation combines the simulated reserves of several
Bootstrap methods ("segments") into one total distribution.  It never simulates
reserves itself: each segment's simulations come from
``bootstrap_contract.bootstrap_simulated_reserves``, and this module only
decides how the segments' simulations are paired, then adds them up.

The rules are ResQ's, pinned against the live ResQ COM API in plan steps 1 and 2
(``docs/plans/bootstrap_and_stochastic_consolidation.md``, "How ResQ
consolidates"):

1. A target rank correlation ``rho`` becomes the linear correlation
   ``2*sin(pi*rho/6)`` of a normal copula, whatever the dependency structure.
2. A matrix that is not positive definite has its eigenvalues clipped at
   ``1e-6`` and is rescaled to a unit diagonal.
3. The consolidation draws an ``m x n`` matrix of variates method by method,
   multiplies it by the lower Cholesky factor ``L`` of the adjusted matrix, and
   ranks each row (rank 1 the smallest).  Normal uses standard normals, Uniform
   raw uniforms, Gamma ``-ln U``, and Student's T a multivariate t with one
   chi-square per simulation shared by every method.
4. Consolidated simulation ``s`` takes, from each segment ``c``, the simulation
   whose total-reserve rank is ``ranks[c][s]``, multiplies its reserves by the
   segment's factor, and adds them origin by origin.  Segments with fewer
   origins line up at the latest one and count as zero in the rest; ResQ
   refuses them, and Arco allows them so a ten-year line can join a full-history
   one.

"0% correlated" and "As it comes" both use the identity matrix; "100%
correlated" is the all-ones matrix through the repair in rule 2.

Like ``bootstrap_simulation`` the module is dependency-free, seeded from
``random.Random``: a run is reproducible from its seed, and matches ResQ
exactly only when it is fed ResQ's own ranks (ResQ's uniform generator is not
known), otherwise within sampling error.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .bootstrap_simulation import (
    BST_HISTOGRAM_BINS,
    BST_SUMMARY_PERCENTILES,
    summarize_reserves,
    total_reserve_ranks,
)


SCON_CORRELATION_OPTIONS = ("independent", "fully_correlated", "specified", "as_generated")
SCON_DEPENDENCY_TYPES = ("normal", "uniform", "gamma", "student_t")

#: Floor ResQ clips a non-positive-definite matrix's eigenvalues to.
SCON_MIN_EIGENVALUE = 1e-6

#: Degrees of freedom ResQ offers by default for Student's T.
SCON_DEFAULT_DEGREES_OF_FREEDOM = 20


#: Stand-in for a uniform draw of exactly 0 when taking its logarithm.
_SMALLEST_UNIFORM = 2.0 ** -53


class StochasticConsolidationError(ValueError):
    """A consolidation cannot run on the inputs it was given."""


# ---------------------------------------------------------------------------
# Correlation matrices


def _square(matrix: Sequence[Sequence[Any]], size: int) -> list[list[float]]:
    """Read a ``size x size`` target, mirroring the upper triangle below the diagonal.

    The consolidation page edits the cells above the diagonal and mirrors them,
    so the upper triangle is authoritative; the diagonal is always 1.  Missing
    cells read as 0.
    """

    rows = [list(row) for row in (matrix or [])]
    result = [[0.0] * size for _ in range(size)]
    for i in range(size):
        result[i][i] = 1.0
        for j in range(i + 1, size):
            value = 0.0
            if i < len(rows) and j < len(rows[i]):
                try:
                    value = float(rows[i][j])
                except (TypeError, ValueError):
                    value = 0.0
                if not math.isfinite(value):
                    value = 0.0
            if value < -1.0 or value > 1.0:
                raise StochasticConsolidationError(
                    f"Correlation between segments {i + 1} and {j + 1} is {value:g}; it must lie between -1 and 1."
                )
            result[i][j] = value
            result[j][i] = value
    return result


def target_correlation_matrix(
    correlation_option: str,
    size: int,
    target_correlations: Sequence[Sequence[Any]] | None = None,
) -> list[list[float]]:
    """The target rank-correlation matrix a correlation option stands for."""

    if correlation_option not in SCON_CORRELATION_OPTIONS:
        raise StochasticConsolidationError(f"Unknown correlation option {correlation_option!r}.")
    if correlation_option == "specified":
        return _square(target_correlations or [], size)
    fill = 1.0 if correlation_option == "fully_correlated" else 0.0
    return [[1.0 if i == j else fill for j in range(size)] for i in range(size)]


def symmetric_eigen(matrix: Sequence[Sequence[float]]) -> tuple[list[float], list[list[float]]]:
    """Eigenvalues and eigenvectors of a small symmetric matrix (cyclic Jacobi).

    Returns ``(values, vectors)`` with ``vectors[i][k]`` the i-th component of
    the eigenvector for ``values[k]``.
    """

    size = len(matrix)
    a = [[float(value) for value in row] for row in matrix]
    v = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for _sweep in range(100):
        off = math.fsum(a[i][j] * a[i][j] for i in range(size) for j in range(size) if i != j)
        if off < 1e-30:
            break
        for p in range(size - 1):
            for q in range(p + 1, size):
                if a[p][q] == 0.0:
                    continue
                theta = (a[q][q] - a[p][p]) / (2.0 * a[p][q])
                t = (1.0 if theta >= 0.0 else -1.0) / (abs(theta) + math.sqrt(theta * theta + 1.0))
                c = 1.0 / math.sqrt(t * t + 1.0)
                s = t * c
                for k in range(size):
                    akp, akq = a[k][p], a[k][q]
                    a[k][p] = c * akp - s * akq
                    a[k][q] = s * akp + c * akq
                for k in range(size):
                    apk, aqk = a[p][k], a[q][k]
                    a[p][k] = c * apk - s * aqk
                    a[q][k] = s * apk + c * aqk
                for k in range(size):
                    vkp, vkq = v[k][p], v[k][q]
                    v[k][p] = c * vkp - s * vkq
                    v[k][q] = s * vkp + c * vkq
    return [a[i][i] for i in range(size)], v


def repair_correlation_matrix(
    matrix: Sequence[Sequence[float]],
    *,
    minimum_eigenvalue: float = SCON_MIN_EIGENVALUE,
) -> list[list[float]]:
    """ResQ's repair of a matrix that is not positive definite.

    ``C = V * max(lambda, 1e-6) * V^T``, then ``C[i][j] / sqrt(C[i][i] * C[j][j])``.
    A matrix whose smallest eigenvalue already reaches the floor passes through
    unchanged (clipping it would change nothing).
    """

    size = len(matrix)
    values, vectors = symmetric_eigen(matrix)
    if not size or min(values) >= minimum_eigenvalue:
        return [[float(value) for value in row] for row in matrix]
    clipped = [max(value, minimum_eigenvalue) for value in values]
    rebuilt = [
        [math.fsum(vectors[i][k] * clipped[k] * vectors[j][k] for k in range(size)) for j in range(size)]
        for i in range(size)
    ]
    scale = [math.sqrt(rebuilt[i][i]) for i in range(size)]
    return [
        [1.0 if i == j else rebuilt[i][j] / (scale[i] * scale[j]) for j in range(size)]
        for i in range(size)
    ]


def adjusted_correlation_matrix(target: Sequence[Sequence[float]]) -> list[list[float]]:
    """Convert target rank correlations to the linear correlations actually used.

    Each off-diagonal ``rho`` becomes ``2*sin(pi*rho/6)`` for every dependency
    structure (ResQ's ``MethodCorrelations_Adjusted``), and the result is
    repaired when it is not positive definite.
    """

    size = len(target)
    converted = [
        [1.0 if i == j else 2.0 * math.sin(math.pi * float(target[i][j]) / 6.0) for j in range(size)]
        for i in range(size)
    ]
    return repair_correlation_matrix(converted)


def cholesky_lower(matrix: Sequence[Sequence[float]]) -> list[list[float]]:
    """Lower Cholesky factor ``L`` with ``L * L^T == matrix``."""

    size = len(matrix)
    lower = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(i + 1):
            total = float(matrix[i][j]) - math.fsum(lower[i][k] * lower[j][k] for k in range(j))
            if i == j:
                if total <= 0.0:
                    raise StochasticConsolidationError("The correlation matrix is not positive definite.")
                lower[i][i] = math.sqrt(total)
            else:
                lower[i][j] = total / lower[j][j]
    return lower


# ---------------------------------------------------------------------------
# Rank generation


def _ranks_of_rows(rows: Sequence[Sequence[float]]) -> list[list[int]]:
    return [total_reserve_ranks(row) for row in rows]


def generate_consolidation_ranks(
    adjusted: Sequence[Sequence[float]],
    simulation_count: int,
    random_seed: int,
    *,
    dependency_type: str = "normal",
    degrees_of_freedom: float = SCON_DEFAULT_DEGREES_OF_FREEDOM,
) -> list[list[int]]:
    """The ``m x n`` rank matrix (ResQ's ``ConsolidationRanks``) for an adjusted matrix.

    Variates are drawn method by method (method 1's n draws first), combined as
    ``X = L * V`` with ``L`` the lower Cholesky factor, and each row of ``X`` is
    ranked with rank 1 the smallest.  Student's T divides every simulation's
    column by one shared ``sqrt(W / nu)`` with ``W`` chi-square on ``nu``
    degrees of freedom.  Deterministic for a given seed.
    """

    if dependency_type not in SCON_DEPENDENCY_TYPES:
        raise StochasticConsolidationError(f"Unknown dependency type {dependency_type!r}.")
    count = int(simulation_count)
    if count < 1:
        raise StochasticConsolidationError("A consolidation needs at least one simulation.")
    size = len(adjusted)
    lower = cholesky_lower(adjusted)
    rng = random.Random(int(random_seed))

    if dependency_type == "uniform":
        draw = rng.random
    elif dependency_type == "gamma":
        # Gamma(shape 1) as ResQ builds it, -ln U: decreasing in U, so with an
        # identity matrix its ranks are the reverse of the Uniform ranks.
        draw = lambda: -math.log(rng.random() or _SMALLEST_UNIFORM)  # noqa: E731
    else:
        draw = lambda: rng.gauss(0.0, 1.0)  # noqa: E731
    variates = [[draw() for _ in range(count)] for _ in range(size)]

    divisors: list[float] | None = None
    if dependency_type == "student_t":
        nu = float(degrees_of_freedom)
        if not math.isfinite(nu) or nu <= 0.0:
            raise StochasticConsolidationError("Student's T needs positive degrees of freedom.")
        divisors = [math.sqrt(rng.gammavariate(nu / 2.0, 2.0) / nu) for _ in range(count)]

    combined: list[list[float]] = []
    for i in range(size):
        weights = [(k, lower[i][k]) for k in range(i + 1) if lower[i][k] != 0.0]
        row = []
        for s in range(count):
            value = math.fsum(weight * variates[k][s] for k, weight in weights)
            row.append(value / divisors[s] if divisors is not None else value)
        combined.append(row)
    return _ranks_of_rows(combined)


# ---------------------------------------------------------------------------
# Combination


@dataclass(frozen=True)
class ConsolidationOptions:
    """Everything a consolidation run needs besides its segments' simulations."""

    simulation_count: int
    random_seed: int
    correlation_option: str = "specified"
    dependency_type: str = "normal"
    degrees_of_freedom: float = SCON_DEFAULT_DEGREES_OF_FREEDOM
    target_correlations: Sequence[Sequence[Any]] = field(default_factory=list)
    factors: Sequence[float] = field(default_factory=list)


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    if n < 2:
        return 0.0
    mx = math.fsum(x) / n
    my = math.fsum(y) / n
    sxy = math.fsum((a - mx) * (b - my) for a, b in zip(x, y))
    sxx = math.fsum((a - mx) ** 2 for a in x)
    syy = math.fsum((b - my) ** 2 for b in y)
    return sxy / math.sqrt(sxx * syy) if sxx > 0.0 and syy > 0.0 else 0.0


def _correlation_matrix(rows: Sequence[Sequence[float]]) -> list[list[float]]:
    size = len(rows)
    result = [[1.0 if i == j else 0.0 for j in range(size)] for i in range(size)]
    for i in range(size):
        for j in range(i + 1, size):
            value = _pearson(rows[i], rows[j])
            result[i][j] = value
            result[j][i] = value
    return result


def _segment_block(segment: Mapping[str, Any], basis: str) -> Mapping[str, Any]:
    block = segment.get(basis) if isinstance(segment.get(basis), Mapping) else segment
    if "reserves" not in block:
        raise StochasticConsolidationError("A segment's simulations carry no reserves.")
    return block


def _check_ranks(ranks: Sequence[Sequence[int]], size: int, count: int) -> list[list[int]]:
    if len(ranks) != size:
        raise StochasticConsolidationError(f"Expected {size} rows of ranks, got {len(ranks)}.")
    checked = []
    for row in ranks:
        row = [int(value) for value in row]
        if len(row) != count or sorted(row) != list(range(1, count + 1)):
            raise StochasticConsolidationError("Every row of consolidation ranks must be a permutation of 1..n.")
        checked.append(row)
    return checked


def consolidate_simulations(
    segments: Sequence[Mapping[str, Any]],
    options: ConsolidationOptions,
    *,
    ranks: Sequence[Sequence[int]] | None = None,
    basis: str = "scaled",
) -> dict[str, Any]:
    """Combine the segments' simulations into consolidated simulations.

    ``segments`` are ``bootstrap_simulated_reserves`` results (or any mapping
    whose ``basis`` block holds ``reserves`` as simulation x origin and
    ``total_ranks``).  ``ranks`` overrides the generated ranks, which is how
    ResQ's own ranks reproduce ResQ exactly.  The result is plain data, never
    persisted: the consolidated ``reserves``, ``totals`` and ``total_ranks``,
    the ranks used, each segment's contribution to every consolidated total
    (factor times its total), and the matrices behind them.
    """

    size = len(segments)
    if size < 1:
        raise StochasticConsolidationError("A consolidation needs at least one included bootstrap.")
    count = int(options.simulation_count)
    factors = [float(value) for value in (options.factors or [1.0] * size)]
    if len(factors) != size:
        raise StochasticConsolidationError(f"Expected {size} factors, got {len(factors)}.")

    blocks = [_segment_block(segment, basis) for segment in segments]
    for index, block in enumerate(blocks, start=1):
        if len(block["reserves"]) != count:
            raise StochasticConsolidationError(
                f"Segment {index} has {len(block['reserves'])} simulations; the consolidation runs {count}."
            )
    labels, offsets = _aligned_origins(segments, blocks)
    origin_count = len(labels) if labels is not None else None
    if labels is None:
        for index, block in enumerate(blocks, start=1):
            width = len(block["reserves"][0]) if block["reserves"] else 0
            if origin_count is None:
                origin_count = width
            elif width != origin_count:
                raise StochasticConsolidationError(
                    f"Segment {index} has {width} origin periods; segment 1 has {origin_count}."
                )
        offsets = [0] * size

    target = target_correlation_matrix(options.correlation_option, size, options.target_correlations)
    adjusted = adjusted_correlation_matrix(target)
    if ranks is None:
        used_ranks = generate_consolidation_ranks(
            adjusted,
            count,
            options.random_seed,
            dependency_type=options.dependency_type,
            degrees_of_freedom=options.degrees_of_freedom,
        )
    else:
        used_ranks = _check_ranks(ranks, size, count)

    width = origin_count or 0
    consolidated = [[0.0] * width for _ in range(count)]
    contributions: list[list[float]] = []
    for c, block in enumerate(blocks):
        reserves = block["reserves"]
        segment_ranks = block.get("total_ranks") or total_reserve_ranks([math.fsum(row) for row in reserves])
        simulation_at_rank = [0] * (count + 1)
        for simulation, rank in enumerate(segment_ranks):
            simulation_at_rank[int(rank)] = simulation
        factor = factors[c]
        offset = offsets[c]
        contribution = []
        for s in range(count):
            row = reserves[simulation_at_rank[used_ranks[c][s]]]
            target_row = consolidated[s]
            for w, value in enumerate(row):
                target_row[offset + w] += factor * value
            contribution.append(factor * math.fsum(row))
        contributions.append(contribution)

    totals = [math.fsum(row) for row in consolidated]
    return {
        "simulation_count": count,
        "random_seed": int(options.random_seed),
        "correlation_option": options.correlation_option,
        "dependency_type": options.dependency_type,
        "degrees_of_freedom": options.degrees_of_freedom,
        "factors": factors,
        "origin_labels": labels or [],
        "target_correlations": target,
        "adjusted_correlations": adjusted,
        "ranks": used_ranks,
        "reserves": consolidated,
        "totals": totals,
        "total_ranks": total_reserve_ranks(totals),
        "segment_totals": contributions,
        "origin_offsets": offsets,
        "latest_values": _combined_latest(segments, factors, width, offsets),
    }


def _aligned_origins(
    segments: Sequence[Mapping[str, Any]], blocks: Sequence[Mapping[str, Any]]
) -> tuple[list[str] | None, list[int]]:
    """The consolidation's origins and where each segment's first origin sits in them.

    Segments valued at the same date end at the same origin, so they line up
    at their latest one: the segment with the most origins sets the axis, and
    a shorter one must be its last origins (HO's ten years inside Oil's
    thirty-nine).  A segment counts as zero in every origin it does not have.
    Segments that carry no labels give ``None`` and must share one width.
    """

    labelled = [
        [str(label) for label in segment.get("origin_labels") or []] if isinstance(segment, Mapping) else []
        for segment in segments
    ]
    if not all(labelled):
        return None, []
    for index, (labels, block) in enumerate(zip(labelled, blocks), start=1):
        width = len(block["reserves"][0]) if block["reserves"] else len(labels)
        if width != len(labels):
            raise StochasticConsolidationError(
                f"Segment {index} has {width} origin periods but {len(labels)} origin labels."
            )
    axis = max(labelled, key=len)
    offsets = []
    for index, labels in enumerate(labelled, start=1):
        offset = len(axis) - len(labels)
        if axis[offset:] != labels:
            raise StochasticConsolidationError(
                f"Segment {index}'s origin periods ({labels[0]} to {labels[-1]}) are not the latest "
                f"origins of the consolidation ({axis[0]} to {axis[-1]})."
            )
        offsets.append(offset)
    return list(axis), offsets


def _combined_latest(
    segments: Sequence[Mapping[str, Any]], factors: Sequence[float], width: int, offsets: Sequence[int]
) -> list[float] | None:
    latest = [segment.get("latest_values") for segment in segments]
    if not width or any(not values or offset + len(values) != width for values, offset in zip(latest, offsets)):
        return None
    return [
        math.fsum(
            f * float(values[w - offset] or 0.0)
            for f, values, offset in zip(factors, latest, offsets)
            if w >= offset
        )
        for w in range(width)
    ]


def _standalone(values: Sequence[float]) -> tuple[float, float]:
    n = len(values)
    if not n:
        return 0.0, 0.0
    mean = math.fsum(values) / n
    variance = math.fsum((value - mean) ** 2 for value in values) / n  # ResQ divides by n
    return mean, math.sqrt(variance) if variance > 0.0 else 0.0


def summarize_consolidated_simulations(
    simulations: Mapping[str, Any],
    *,
    percentiles: Sequence[float] = BST_SUMMARY_PERCENTILES,
    histogram_bins: int = BST_HISTOGRAM_BINS,
) -> dict[str, Any]:
    """Reduce ``consolidate_simulations`` output to the consolidation's summary.

    ``scaled`` has the shape of a bootstrap summary block (index 0 the total).
    ``segments`` gives each segment's standalone mean, standard deviation, CV
    and share of the total mean, and ``diversification`` compares the total's
    standard deviation with the sum of the standalone ones.  The achieved rank
    correlation is the Pearson correlation of the ranks used; the achieved
    linear correlation that of the segments' contributions.
    """

    totals = simulations["totals"]
    total_mean, total_sd = _standalone(totals)
    segments = []
    standalone_sd_sum = 0.0
    for c, contribution in enumerate(simulations["segment_totals"]):
        mean, sd = _standalone(contribution)
        standalone_sd_sum += sd
        segments.append({
            "factor": simulations["factors"][c],
            "mean": mean,
            "standard_error": sd,
            "cv": sd / mean if mean else None,
            "share_of_mean": mean / total_mean if total_mean else None,
        })
    return {
        "simulation_count": simulations["simulation_count"],
        "random_seed": simulations["random_seed"],
        "correlation_option": simulations["correlation_option"],
        "dependency_type": simulations["dependency_type"],
        "degrees_of_freedom": simulations["degrees_of_freedom"],
        "target_correlations": simulations["target_correlations"],
        "adjusted_correlations": simulations["adjusted_correlations"],
        "achieved_rank_correlations": _correlation_matrix(simulations["ranks"]),
        "achieved_linear_correlations": _correlation_matrix(simulations["segment_totals"]),
        "scaled": summarize_reserves(
            simulations["reserves"],
            percentiles=percentiles,
            latest_values=simulations.get("latest_values"),
            histogram_bins=histogram_bins,
        ),
        "segments": segments,
        "diversification": {
            "total_standard_error": total_sd,
            "sum_of_standalone_standard_errors": standalone_sd_sum,
            "benefit": standalone_sd_sum - total_sd,
        },
        "latest_values": list(simulations.get("latest_values") or []),
    }


def run_stochastic_consolidation(
    segments: Sequence[Mapping[str, Any]],
    options: ConsolidationOptions,
    *,
    ranks: Sequence[Sequence[int]] | None = None,
) -> dict[str, Any]:
    """Consolidate the segments' scaled simulations and return the summary."""

    return summarize_consolidated_simulations(consolidate_simulations(segments, options, ranks=ranks))
