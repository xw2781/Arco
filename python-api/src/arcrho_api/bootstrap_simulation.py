"""Canonical numeric engine for Arco Bootstrap methods.

This module owns every Bootstrap calculation: the DFM projection the method
bootstraps from, the Over-dispersed Poisson residual grids and scale parameters,
the simulation itself, and the scaling of a simulated reserve distribution onto a
target ultimate.  ``bootstrap_contract`` and every other producer delegate here
so a migrated method, a re-saved method, and a recalculated method share one
implementation.

Every deterministic formula is the ResQ Bootstrap calculation, verified against
the live ResQ COM API to machine precision; see
``frontend/docs/plans/bootstrap_method_plan.md`` for the verification table and
the ResQ technical-note references.

The module is deliberately dependency-free (``arcrho_api`` declares no runtime
dependencies), so the simulation is plain Python seeded from
``random.Random``.  That makes a run bit-reproducible for a given seed, which is
what lets a Bootstrap method persist a seed plus a summary instead of a
multi-megabyte array of simulated reserves.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


BST_MODEL_TYPES = ("mack", "odp_varying_scale", "odp_single_scale")
BST_RESIDUAL_TYPES = (
    "unscaled",
    "unscaled_bias_adjusted",
    "scaled",
    "scaled_bias_adjusted",
    "scaled_bias_adjusted_zero_average",
)
BST_DISTRIBUTIONS = ("none", "resampled", "normal", "log_normal", "gamma", "odp")
BST_SCALING_METHODS = ("unscaled", "additive", "multiplicative", "user_defined", "from_target")
BST_NEGATIVE_MEAN_ACTIONS = ("value_0_01", "normal")
BST_ODP_NEGATIVE_MEAN_ACTIONS = ("odp", "gamma_or_log_normal", "negative_mean")

#: Percentile ladder persisted with a simulation summary, in percent: every half
#: percent from 0 to 100, so the full-ladder view and the 99.5% capital
#: percentile both come from the stored summary without re-simulating.
BST_SUMMARY_PERCENTILES = tuple(step / 2 for step in range(0, 201))

#: Bins in the persisted histogram of the total reserve.
BST_HISTOGRAM_BINS = 40

#: Mean forced onto a non-positive Gamma/LogNormal mean under ``value_0_01``.
_MIN_POSITIVE_MEAN = 0.01

#: Relative size below which ResQ treats a residual as "zero (or very small)"
#: and drops it.  A complete triangle saturates the chain-ladder model at the
#: oldest origin's last column and the newest origin's first column, so the
#: observed and fitted incrementals there agree to within accumulated rounding
#: rather than exactly; a plain ``!= 0`` test keeps those cells and shifts the
#: tail scale parameters.  Genuine residuals sit many orders of magnitude above
#: this threshold.
_ZERO_RESIDUAL_RELATIVE_TOLERANCE = 1e-9


class BootstrapCalculationError(ValueError):
    """Raised when Bootstrap inputs cannot support a calculation."""


def _finite(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _row_values(row: Any) -> list[float | None]:
    if not isinstance(row, (list, tuple)):
        return []
    return [_finite(item) for item in row]


def observed_triangle(values: Any) -> list[list[float]]:
    """Return a ragged cumulative triangle, trimming trailing blank cells.

    Arco stores an absent cell as ``null``, and a row stops at its first one.
    A ``0.0`` is an observation: an old origin can hold zero cumulative losses
    for years, and ResQ bootstraps such a triangle with every cell in place.
    """

    triangle: list[list[float]] = []
    for row in values if isinstance(values, (list, tuple)) else []:
        cells: list[float] = []
        for item in _row_values(row):
            if item is None:
                break
            cells.append(item)
        triangle.append(cells)
    return triangle


@dataclass(frozen=True)
class BootstrapFit:
    """The DFM projection a Bootstrap method resamples around."""

    observed_cumulative: list[list[float]]
    observed_incremental: list[list[float]]
    fitted_cumulative: list[list[float]]
    fitted_incremental: list[list[float]]
    latest_values: list[float]
    latest_column: list[int]
    selected_ratios: list[float]
    total_development_periods: int

    @property
    def origin_count(self) -> int:
        return len(self.observed_cumulative)

    @property
    def observed_columns(self) -> int:
        return max((len(row) for row in self.observed_cumulative), default=0)

    @property
    def dfm_reserves(self) -> list[float]:
        last = self.total_development_periods - 1
        return [
            self.fitted_cumulative[w][last] - self.latest_values[w]
            for w in range(self.origin_count)
        ]


def fit_dfm_projection(
    observed_cumulative: Sequence[Sequence[float]],
    selected_ratios: Sequence[float],
    total_development_periods: int,
) -> BootstrapFit:
    """Back-fit and project the DFM around the observed latest diagonal.

    Reproduces ResQ ``xDFMMethod.PredictedValues`` to 1.8e-16: every origin is
    anchored on its own latest observed cumulative, back-fitted through the
    selected ratios for earlier periods and projected forward for later ones.
    """

    triangle = [list(row) for row in observed_cumulative]
    if not triangle or not any(triangle):
        raise BootstrapCalculationError("Bootstrap requires a non-empty DFM triangle.")
    ratios = [_finite(value) for value in selected_ratios]
    periods = int(total_development_periods)
    if periods < 1:
        raise BootstrapCalculationError("Bootstrap requires at least one development period.")
    if len(ratios) < periods - 1 or any(value is None or value == 0 for value in ratios[: periods - 1]):
        raise BootstrapCalculationError(
            "Bootstrap requires a non-zero selected ratio for every development period."
        )
    ratios = [float(value) for value in ratios[: periods - 1]]

    fitted: list[list[float]] = []
    latest: list[float] = []
    latest_column: list[int] = []
    for row in triangle:
        if not row:
            raise BootstrapCalculationError(
                "Bootstrap requires at least one observed cell in every origin period."
            )
        anchor = len(row) - 1
        if anchor >= periods:
            raise BootstrapCalculationError(
                "Bootstrap triangle has more observed columns than development periods."
            )
        cells = [0.0] * periods
        cells[anchor] = row[anchor]
        for column in range(anchor - 1, -1, -1):
            cells[column] = cells[column + 1] / ratios[column]
        for column in range(anchor, periods - 1):
            cells[column + 1] = cells[column] * ratios[column]
        fitted.append(cells)
        latest.append(row[anchor])
        latest_column.append(anchor)

    fitted_incremental = [
        [cells[0]] + [cells[c] - cells[c - 1] for c in range(1, periods)] for cells in fitted
    ]
    observed_incremental = [
        ([row[0]] + [row[c] - row[c - 1] for c in range(1, len(row))]) if row else []
        for row in triangle
    ]
    return BootstrapFit(
        observed_cumulative=triangle,
        observed_incremental=observed_incremental,
        fitted_cumulative=fitted,
        fitted_incremental=fitted_incremental,
        latest_values=latest,
        latest_column=latest_column,
        selected_ratios=ratios,
        total_development_periods=periods,
    )


@dataclass(frozen=True)
class BootstrapResiduals:
    """ODP residual grids, scale parameters, and the counts behind them."""

    model_type: str
    unscaled: list[list[float | None]]
    grids: dict[str, list[list[float | None]]]
    scale_unsmoothed: list[float]
    residual_adjustment: float
    bias_factor: float
    data_point_count: int
    parameter_count: int
    excluded: list[list[bool]]

    @property
    def pool(self) -> list[float]:
        """The residuals a ``resampled`` simulation draws from."""

        grid = self.grids["scaled_bias_adjusted_zero_average"]
        return [value for row in grid for value in row if value is not None]


def _is_excluded(excluded: Sequence[Sequence[Any]] | None, origin: int, column: int) -> bool:
    if not excluded or origin >= len(excluded):
        return False
    row = excluded[origin]
    if not isinstance(row, (list, tuple)) or column >= len(row):
        return False
    return bool(row[column])


def calculate_residuals(
    fit: BootstrapFit,
    *,
    model_type: str = "odp_single_scale",
    excluded_data_cells: Sequence[Sequence[Any]] | None = None,
    excluded_ratios: Sequence[Sequence[Any]] | None = None,
) -> BootstrapResiduals:
    """Return every ResQ residual type plus the scale parameters behind them.

    Verified exactly against ResQ ``ResidualsByType`` for both ODP models.  Two
    details are load-bearing and easy to get wrong:

    * ``|m|`` under the root.  An incurred triangle that develops downwards has
      negative fitted incrementals; ResQ keeps the sign of the numerator and
      takes the root of the magnitude rather than dropping the cell.
    * ``n`` and ``n_d`` count observed *data cells*, including cells whose
      residual is exactly zero and therefore excluded from every sum.  For the
      reference method that is 55 and not 53; using the residual count moves the
      scale parameter by 5%.

    ``excluded_data_cells`` marks *input triangle* cells the DFM excludes or
    that are missing.  Those cells are neither residuals nor data points, and a
    simulation substitutes their fitted value.  It is not the DFM's link-ratio
    exclusion grid, which belongs to :class:`BootstrapRefitRules` instead.

    ResQ also leaves a cell out, as neither residual nor data point, when its
    cumulative or the cumulative before it is zero, or when the DFM excludes the
    link ratio into it (``excluded_ratios[w][c - 1]``).  The parameter count then
    covers only origins with a non-zero fitted level and development periods
    that keep a data point.  Both were pinned cell by cell against ResQ's
    ``HPPREF\\HO+DF\\NJ\\OIL`` bootstrap (780 cells, 524 residuals, scale
    15.689308) on 2026-10-27.
    """

    if model_type not in BST_MODEL_TYPES:
        raise BootstrapCalculationError(f"Unsupported Bootstrap model type: {model_type!r}.")
    if model_type == "mack":
        raise BootstrapCalculationError(
            "The Mack Bootstrap model is not implemented yet; use an Over-dispersed Poisson model."
        )

    periods = fit.total_development_periods
    origins = fit.origin_count
    observed_columns = fit.observed_columns

    excluded = [[False] * periods for _ in range(origins)]
    unscaled: list[list[float | None]] = [[None] * periods for _ in range(origins)]
    data_point_count = 0
    column_cells = [0] * periods
    for w in range(origins):
        row = fit.observed_incremental[w]
        cumulative = fit.observed_cumulative[w]
        for c in range(len(row)):
            if (
                _is_excluded(excluded_data_cells, w, c)
                or cumulative[c] == 0.0
                or (c > 0 and (cumulative[c - 1] == 0.0 or _is_excluded(excluded_ratios, w, c - 1)))
            ):
                excluded[w][c] = True
                continue
            data_point_count += 1
            column_cells[c] += 1
            fitted = fit.fitted_incremental[w][c]
            if fitted == 0.0:
                continue
            difference = row[c] - fitted
            scale = max(abs(fitted), abs(row[c]))
            if abs(difference) <= _ZERO_RESIDUAL_RELATIVE_TOLERANCE * scale:
                continue
            unscaled[w][c] = difference / math.sqrt(abs(fitted))

    fitted_origins = sum(1 for cells in fit.fitted_cumulative if any(cells))
    parameter_count = fitted_origins + sum(1 for cells in column_cells[:observed_columns] if cells) - 1
    degrees_of_freedom = data_point_count - parameter_count
    if degrees_of_freedom <= 0:
        raise BootstrapCalculationError(
            "Bootstrap has no residual degrees of freedom: the triangle is fully parameterised."
        )
    bias_factor = math.sqrt(data_point_count / degrees_of_freedom)

    if model_type == "odp_single_scale":
        total = sum(v * v for row in unscaled for v in row if v is not None)
        scale = math.sqrt(total / degrees_of_freedom)
        scale_unsmoothed = [scale] * periods
    else:
        scale_unsmoothed = []
        for c in range(periods):
            column = [unscaled[w][c] for w in range(origins) if unscaled[w][c] is not None]
            if column and column_cells[c]:
                variance = (
                    sum(v * v for v in column)
                    / column_cells[c]
                    * (data_point_count / degrees_of_freedom)
                )
                scale_unsmoothed.append(math.sqrt(variance))
            elif len(scale_unsmoothed) >= 2:
                # ResQ: "where there are insufficient points in the tail use the
                # lower of the previous two values".
                scale_unsmoothed.append(min(scale_unsmoothed[-2:]))
            elif scale_unsmoothed:
                scale_unsmoothed.append(scale_unsmoothed[-1])
            else:
                raise BootstrapCalculationError(
                    "Bootstrap cannot derive a scale parameter for the first development period."
                )

    def _blank_grid() -> list[list[float | None]]:
        return [[None] * periods for _ in range(origins)]

    grids: dict[str, list[list[float | None]]] = {
        "unscaled": [list(row) for row in unscaled],
        "unscaled_bias_adjusted": _blank_grid(),
        "scaled": _blank_grid(),
        "scaled_bias_adjusted": _blank_grid(),
        "scaled_bias_adjusted_zero_average": _blank_grid(),
    }
    for w in range(origins):
        for c in range(periods):
            value = unscaled[w][c]
            if value is None:
                continue
            grids["unscaled_bias_adjusted"][w][c] = value * bias_factor
            scaled = value / scale_unsmoothed[c] if scale_unsmoothed[c] else None
            grids["scaled"][w][c] = scaled
            if scaled is not None:
                grids["scaled_bias_adjusted"][w][c] = scaled * bias_factor

    adjusted = [v for row in grids["scaled_bias_adjusted"] for v in row if v is not None]
    residual_adjustment = sum(adjusted) / len(adjusted) if adjusted else 0.0
    for w in range(origins):
        for c in range(periods):
            value = grids["scaled_bias_adjusted"][w][c]
            if value is not None:
                grids["scaled_bias_adjusted_zero_average"][w][c] = value - residual_adjustment

    return BootstrapResiduals(
        model_type=model_type,
        unscaled=unscaled,
        grids=grids,
        scale_unsmoothed=scale_unsmoothed,
        residual_adjustment=residual_adjustment,
        bias_factor=bias_factor,
        data_point_count=data_point_count,
        parameter_count=parameter_count,
        excluded=excluded,
    )


def selected_scale_values(
    unsmoothed: Sequence[float],
    *,
    smoothed: Sequence[Any] | None = None,
    user_entry: Sequence[Any] | None = None,
) -> list[float]:
    """Resolve ResQ's Selected scale row: User Entry, else Smoothed, else Unsmoothed."""

    selected: list[float] = []
    for index, base in enumerate(unsmoothed):
        entry = _finite(user_entry[index]) if user_entry and index < len(user_entry) else None
        if entry is not None:
            selected.append(entry)
            continue
        smooth = _finite(smoothed[index]) if smoothed and index < len(smoothed) else None
        selected.append(smooth if smooth is not None else float(base))
    return selected


@dataclass
class BootstrapSimulationOptions:
    """Everything the Simulation tab owns."""

    simulation_count: int = 10000
    random_seed: int = 0
    estimation_variance: str = "gamma"
    process_variance: str = "gamma"
    prevent_negative_data: bool = True
    negative_mean_action: str = "normal"
    odp_negative_mean_action: str = "negative_mean"

    def validate(self) -> None:
        if self.simulation_count < 1:
            raise BootstrapCalculationError("Bootstrap simulation count must be at least 1.")
        for name, value, allowed in (
            ("estimation_variance", self.estimation_variance, BST_DISTRIBUTIONS),
            ("process_variance", self.process_variance, BST_DISTRIBUTIONS),
            ("negative_mean_action", self.negative_mean_action, BST_NEGATIVE_MEAN_ACTIONS),
            (
                "odp_negative_mean_action",
                self.odp_negative_mean_action,
                BST_ODP_NEGATIVE_MEAN_ACTIONS,
            ),
        ):
            if value not in allowed:
                raise BootstrapCalculationError(f"Unsupported Bootstrap {name}: {value!r}.")


@dataclass
class BootstrapRefitRules:
    """Which development ratios a simulation re-estimates, and how.

    ``refit`` is False for a ratio ResQ would not re-estimate — a tail factor, a
    User Entry column, or a benchmark — because a manual value carries no
    estimation error.
    """

    refit: list[bool] = field(default_factory=list)
    base: list[str] = field(default_factory=list)          # "volume" | "simple"
    periods: list[int | None] = field(default_factory=list)  # None = all
    exclude_high_low: list[bool] = field(default_factory=list)
    excluded_ratios: list[list[bool]] = field(default_factory=list)

    def for_column(self, column: int) -> tuple[bool, str, int | None, bool]:
        def _at(values: Sequence[Any], default: Any) -> Any:
            return values[column] if column < len(values) else default

        return (
            bool(_at(self.refit, False)),
            str(_at(self.base, "volume")),
            _at(self.periods, None),
            bool(_at(self.exclude_high_low, False)),
        )

    def ratio_excluded(self, origin: int, column: int) -> bool:
        return _is_excluded(self.excluded_ratios, origin, column)


@dataclass(frozen=True)
class BootstrapSimulationResult:
    """Per-origin simulated reserves plus the diagnostics ResQ reports."""

    reserves: list[list[float]]           # simulation x origin
    totals: list[float]                   # simulation
    negative_data_pseudo: int
    negative_data_forecast: int
    negative_mean_pseudo: int
    negative_mean_forecast: int


def _moments(values: Sequence[float], *, ddof: int = 0) -> tuple[float, float]:
    """Return the mean and standard deviation of a simulated column.

    Shifted, compensated summation rather than the textbook two-pass formula.
    A Bootstrap origin can be fully developed, in which case every simulation
    returns the identical reserve; summing those directly leaves the mean a few
    ulps off each observation and reports a standard deviation around 1e-10
    where the honest answer is exactly zero.  Shifting by the first observation
    makes a degenerate column collapse to zero exactly and improves accuracy for
    every tightly clustered column.
    """

    count = len(values)
    if not count:
        return 0.0, 0.0
    origin = values[0]
    mean = origin + math.fsum(value - origin for value in values) / count
    if count - ddof <= 0:
        return mean, 0.0
    variance = math.fsum((value - mean) ** 2 for value in values) / (count - ddof)
    return mean, math.sqrt(variance) if variance > 0.0 else 0.0


def _lognormal_parameters(mean: float, sd: float) -> tuple[float, float]:
    variance = sd * sd
    sigma_squared = math.log(1.0 + variance / (mean * mean))
    return math.log(mean) - 0.5 * sigma_squared, math.sqrt(sigma_squared)


def _make_sampler(distribution: str, options: BootstrapSimulationOptions, pool: Sequence[float]):
    """Return ``sample(mean, phi, rng) -> (value, negative_mean_hit)``."""

    negative_action = options.negative_mean_action
    odp_action = options.odp_negative_mean_action
    pool_size = len(pool)

    def _negative(mean: float, phi: float, rng: random.Random, kind: str) -> float:
        if kind == "odp":
            if odp_action == "negative_mean":
                return mean
            if odp_action == "odp":
                return mean
            kind = "gamma"
        if negative_action == "normal":
            return rng.gauss(mean, math.sqrt(phi * abs(mean)))
        forced = _MIN_POSITIVE_MEAN
        if kind == "log_normal":
            mu, sigma = _lognormal_parameters(forced, math.sqrt(phi * forced))
            return math.exp(rng.gauss(mu, sigma))
        return rng.gammavariate(forced / phi, phi) if phi > 0 else forced

    if distribution == "none":
        def sample(mean, phi, rng):
            return mean, False
        return sample

    if distribution == "resampled":
        if not pool_size:
            raise BootstrapCalculationError(
                "A resampled Bootstrap needs at least one usable residual."
            )

        def sample(mean, phi, rng):
            return mean + pool[int(rng.random() * pool_size)] * math.sqrt(phi * abs(mean)), False
        return sample

    if distribution == "normal":
        def sample(mean, phi, rng):
            return rng.gauss(mean, math.sqrt(phi * abs(mean))), False
        return sample

    if distribution == "log_normal":
        def sample(mean, phi, rng):
            if mean <= 0.0 or phi <= 0.0:
                return _negative(mean, phi, rng, "log_normal"), mean <= 0.0
            mu, sigma = _lognormal_parameters(mean, math.sqrt(phi * mean))
            return math.exp(rng.gauss(mu, sigma)), False
        return sample

    if distribution == "gamma":
        def sample(mean, phi, rng):
            if mean <= 0.0 or phi <= 0.0:
                return _negative(mean, phi, rng, "gamma"), mean <= 0.0
            # mean = shape * scale and variance = shape * scale^2 = mean * phi.
            return rng.gammavariate(mean / phi, phi), False
        return sample

    if distribution == "odp":
        def sample(mean, phi, rng):
            if mean <= 0.0 or phi <= 0.0:
                return _negative(mean, phi, rng, "odp"), mean <= 0.0
            return phi * _poisson(mean / phi, rng), False
        return sample

    raise BootstrapCalculationError(f"Unsupported Bootstrap distribution: {distribution!r}.")


def _poisson(mean: float, rng: random.Random) -> int:
    """Knuth for small means, normal approximation for large ones."""

    if mean < 30.0:
        limit = math.exp(-mean)
        count = 0
        product = rng.random()
        while product > limit:
            count += 1
            product *= rng.random()
        return count
    value = rng.gauss(mean, math.sqrt(mean))
    return max(0, int(round(value)))


def _refit_ratio(
    pseudo: list[list[float]],
    fit: BootstrapFit,
    rules: BootstrapRefitRules,
    column: int,
) -> float | None:
    """Re-estimate one development ratio from a pseudo triangle."""

    refit, base, periods, exclude_high_low = rules.for_column(column)
    if not refit:
        return None
    rows = [
        w
        for w in range(fit.origin_count)
        if len(fit.observed_cumulative[w]) > column + 1 and not rules.ratio_excluded(w, column)
    ]
    if periods:
        rows = rows[-int(periods):]
    if not rows:
        return None
    if base == "simple" or exclude_high_low:
        values = []
        for w in rows:
            denominator = pseudo[w][column]
            if denominator == 0.0:
                continue
            values.append(pseudo[w][column + 1] / denominator)
        if exclude_high_low and len(values) > 2:
            values = sorted(values)[1:-1]
        if not values:
            return None
        if base == "simple":
            return sum(values) / len(values)
        # Volume weighted with dynamic hi/lo exclusion is not reachable from the
        # DFM contract today; fall back to the simple mean of the kept ratios.
        return sum(values) / len(values)
    denominator = sum(pseudo[w][column] for w in rows)
    if denominator == 0.0:
        return None
    return sum(pseudo[w][column + 1] for w in rows) / denominator


def simulate_bootstrap(
    fit: BootstrapFit,
    residuals: BootstrapResiduals,
    options: BootstrapSimulationOptions,
    *,
    residual_scale: Sequence[float] | None = None,
    forecast_scale: Sequence[float] | None = None,
    refit_rules: BootstrapRefitRules | None = None,
) -> BootstrapSimulationResult:
    """Run the ResQ Over-dispersed Poisson bootstrap.

    Each simulation builds a pseudo incremental triangle around the DFM fitted
    values, re-estimates the development ratios from it, then projects forward
    **from the pseudo latest diagonal** adding process variance.  Anchoring on
    the pseudo rather than the observed diagonal is what produces the newest
    origin's variance: with the observed diagonal the reference method's total
    prediction error falls from 9,304 to 6,852.  Every future cell's mean is
    the chain-ladder incremental of that diagonal, independent of the cells
    simulated before it.
    """

    options.validate()
    periods = fit.total_development_periods
    origins = fit.origin_count
    phi_r = [float(v) ** 2 for v in (residual_scale or residuals.scale_unsmoothed)]
    phi_f = [float(v) ** 2 for v in (forecast_scale or residual_scale or residuals.scale_unsmoothed)]
    if len(phi_r) < periods or len(phi_f) < periods:
        raise BootstrapCalculationError(
            "Bootstrap needs a scale parameter for every development period."
        )
    rules = refit_rules or default_refit_rules(fit)
    pool = residuals.pool

    draw_pseudo = _make_sampler(options.estimation_variance, options, pool)
    draw_forecast = _make_sampler(options.process_variance, options, pool)
    rng = random.Random(int(options.random_seed) & 0xFFFFFFFF)
    prevent_negative = bool(options.prevent_negative_data)

    fitted = fit.fitted_incremental
    latest_column = fit.latest_column
    observed_len = [len(row) for row in fit.observed_cumulative]
    base_ratios = fit.selected_ratios

    reserves: list[list[float]] = []
    totals: list[float] = []
    neg_pseudo = neg_forecast = 0
    mean_pseudo = mean_forecast = 0

    for _ in range(int(options.simulation_count)):
        # 1. pseudo incremental triangle, cumulated as we go.
        pseudo: list[list[float]] = []
        for w in range(origins):
            row = [0.0] * periods
            running = 0.0
            for c in range(observed_len[w]):
                if residuals.excluded[w][c]:
                    value = fitted[w][c]
                else:
                    value, hit = draw_pseudo(fitted[w][c], phi_r[c], rng)
                    if hit:
                        mean_pseudo += 1
                running += value
                if prevent_negative and running < 0.0:
                    running = 0.0
                    neg_pseudo += 1
                row[c] = running
            pseudo.append(row)

        # 2. re-estimate the development ratios from the pseudo triangle.
        ratios = list(base_ratios)
        for c in range(periods - 1):
            refitted = _refit_ratio(pseudo, fit, rules, c)
            if refitted is not None:
                ratios[c] = refitted

        # 3. project from the pseudo latest diagonal, adding process variance.
        # Each future cell's mean is the chain-ladder incremental of the pseudo
        # latest diagonal (``expected``), not of the cumulative already
        # simulated, as ResQ does: building each mean on earlier simulated
        # cells widens (or, for downward development, narrows) the later
        # origins' ranges.
        cumulative = [pseudo[w][latest_column[w]] for w in range(origins)]
        expected = list(cumulative)
        reserve = [0.0] * origins
        for c in range(periods - 1):
            factor = ratios[c] - 1.0
            phi = phi_f[c + 1]
            for w in range(origins):
                if latest_column[w] > c:
                    continue
                mean = expected[w] * factor
                expected[w] += mean
                if mean == 0.0:
                    continue
                increment, hit = draw_forecast(mean, phi, rng)
                if hit:
                    mean_forecast += 1
                total = cumulative[w] + increment
                if prevent_negative and total < 0.0:
                    increment = -cumulative[w]
                    total = 0.0
                    neg_forecast += 1
                cumulative[w] = total
                reserve[w] += increment
        reserves.append(reserve)
        totals.append(sum(reserve))

    return BootstrapSimulationResult(
        reserves=reserves,
        totals=totals,
        negative_data_pseudo=neg_pseudo,
        negative_data_forecast=neg_forecast,
        negative_mean_pseudo=mean_pseudo,
        negative_mean_forecast=mean_forecast,
    )


def default_refit_rules(fit: BootstrapFit) -> BootstrapRefitRules:
    """Re-estimate every ratio inside the observed triangle, hold the tail fixed."""

    count = fit.total_development_periods - 1
    observed_ratios = max(fit.observed_columns - 1, 0)
    return BootstrapRefitRules(
        refit=[index < observed_ratios for index in range(count)],
        base=["volume"] * count,
        periods=[None] * count,
        exclude_high_low=[False] * count,
        excluded_ratios=[],
    )


def scale_simulated_reserves(
    reserves: Sequence[Sequence[float]],
    *,
    target_means: Sequence[Any],
    scaling_methods: Sequence[str],
    target_cvs: Sequence[Any] | None = None,
) -> list[list[float]]:
    """Apply ResQ technical note 8 scaling to a simulated reserve distribution.

    Additive scaling shifts the distribution and leaves every standard deviation
    untouched, which is why the ResQ Scaled Results standard deviations equal the
    Unscaled ones exactly.
    """

    if not reserves:
        return []
    origins = len(reserves[0])
    count = len(reserves)
    means: list[float] = []
    sds: list[float] = []
    for w in range(origins):
        mean, sd = _moments([row[w] for row in reserves])
        means.append(mean)
        sds.append(sd)

    scaled = [[0.0] * origins for _ in range(count)]
    for w in range(origins):
        method = scaling_methods[w] if w < len(scaling_methods) else "unscaled"
        if method not in BST_SCALING_METHODS:
            raise BootstrapCalculationError(f"Unsupported Bootstrap scaling method: {method!r}.")
        if method == "unscaled":
            for s in range(count):
                scaled[s][w] = reserves[s][w]
            continue
        target = _finite(target_means[w]) if w < len(target_means) else None
        if target is None:
            for s in range(count):
                scaled[s][w] = reserves[s][w]
            continue
        mean, sd = means[w], sds[w]
        if method == "multiplicative" and mean != 0.0:
            target_sd = abs(sd / mean * target)
        elif method == "user_defined":
            cv = _finite(target_cvs[w]) if target_cvs and w < len(target_cvs) else None
            target_sd = abs((cv or 0.0) * target)
        else:  # additive, from_target, or multiplicative with a zero mean
            target_sd = sd
        for s in range(count):
            z = (reserves[s][w] - mean) / sd if sd else 0.0
            scaled[s][w] = z * target_sd + target
    return scaled


def percentile(sorted_values: Sequence[float], fraction: float) -> float:
    """ResQ's percentile of an already sorted sample: no interpolation.

    ResQ's ``PercentileValue(p)`` is the sorted sample at 0-based position
    ``floor(p * n)``, capped at the maximum, so 0 is the minimum and 1 the
    maximum.  This matched all 253 percentiles captured from the reference
    segment and consolidation runs exactly (plan step 4).  The small guard keeps
    a fraction such as 0.29, whose product with n lands a hair under an
    integer, on the order statistic it names.
    """

    if not sorted_values:
        return 0.0
    count = len(sorted_values)
    position = int(math.floor(max(0.0, min(1.0, fraction)) * count + 1e-9))
    return float(sorted_values[min(position, count - 1)])


def percentile_key(step: float) -> str:
    """The summary key of a percentile given in percent: 5 -> "5", 99.5 -> "99.5"."""

    value = float(step)
    return str(int(value)) if value.is_integer() else f"{value:g}"


def total_reserve_ranks(totals: Sequence[float]) -> list[int]:
    """Rank every simulation by its total reserve, 1 for the smallest.

    ResQ's ``TotalRank`` convention: the ranks are a permutation of 1..n, so a
    tie goes to the earlier simulation rather than sharing a rank.
    """

    order = sorted(range(len(totals)), key=lambda index: (totals[index], index))
    ranks = [0] * len(totals)
    for rank, index in enumerate(order, start=1):
        ranks[index] = rank
    return ranks


def reserve_histogram(values: Sequence[float], bins: int = BST_HISTOGRAM_BINS) -> dict[str, Any]:
    """Count a simulated sample into ``bins`` equal-width bins from its minimum to its maximum.

    The last bin is closed, so the maximum is counted; a sample with no spread
    puts every simulation in the first bin.
    """

    bins = max(1, int(bins))
    if not values:
        return {"lower": 0.0, "upper": 0.0, "counts": []}
    lower = float(min(values))
    upper = float(max(values))
    counts = [0] * bins
    width = (upper - lower) / bins
    for value in values:
        index = int((value - lower) / width) if width > 0.0 else 0
        counts[min(max(index, 0), bins - 1)] += 1
    return {"lower": lower, "upper": upper, "counts": counts}


def summarize_reserves(
    reserves: Sequence[Sequence[float]],
    *,
    percentiles: Iterable[float] = BST_SUMMARY_PERCENTILES,
    latest_values: Sequence[float] | None = None,
    histogram_bins: int = BST_HISTOGRAM_BINS,
) -> dict[str, Any]:
    """Reduce a simulated reserve array to the persisted summary.

    Index 0 of every returned vector is the all-origin total, matching ResQ's
    ``xStochasticReserves`` convention where origin index 0 means "Total".
    Percentile keys are percent text (``percentile_key``).  With
    ``latest_values`` the summary also carries the mean and standard deviation
    of the simulated ultimates (latest plus reserve); the histogram is of the
    total reserve.
    """

    if not reserves:
        return {
            "mean": [],
            "standard_error": [],
            "minimum": [],
            "maximum": [],
            "percentiles": {},
            "ultimate_mean": [],
            "ultimate_standard_error": [],
            "histogram": reserve_histogram([], histogram_bins),
        }
    origins = len(reserves[0])
    columns: list[list[float]] = [[sum(row) for row in reserves]]
    for w in range(origins):
        columns.append([row[w] for row in reserves])

    means: list[float] = []
    errors: list[float] = []
    minima: list[float] = []
    maxima: list[float] = []
    ladders: dict[str, list[float]] = {}
    sorted_columns = [sorted(column) for column in columns]
    for index, column in enumerate(columns):
        # ResQ reports the population standard deviation (divisor n).
        mean, sd = _moments(column)
        means.append(mean)
        errors.append(sd)
        minima.append(sorted_columns[index][0])
        maxima.append(sorted_columns[index][-1])
    for step in percentiles:
        ladders[percentile_key(step)] = [
            percentile(column, float(step) / 100.0) for column in sorted_columns
        ]

    ultimate_means: list[float] = []
    ultimate_errors: list[float] = []
    if latest_values is not None:
        latest = [float(_finite(value) or 0.0) for value in latest_values][:origins]
        latest.extend([0.0] * (origins - len(latest)))
        offsets = [math.fsum(latest)] + latest
        for index, column in enumerate(columns):
            mean, sd = _moments([offsets[index] + value for value in column])
            ultimate_means.append(mean)
            ultimate_errors.append(sd)
    return {
        "mean": means,
        "standard_error": errors,
        "minimum": minima,
        "maximum": maxima,
        "percentiles": ladders,
        "ultimate_mean": ultimate_means,
        "ultimate_standard_error": ultimate_errors,
        "histogram": reserve_histogram(columns[0], histogram_bins),
    }
