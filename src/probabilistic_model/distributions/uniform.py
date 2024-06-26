import numpy as np

from .distributions import *
from ..constants import PADDING_FACTOR_FOR_X_AXIS_IN_PLOT


class UniformDistribution(ContinuousDistributionWithFiniteSupport):
    """
    Class for uniform distributions over the half-open interval [lower, upper).
    """

    def __init__(self, variable: Continuous, interval: SimpleInterval):
        super().__init__()
        self.variable = variable
        self.interval = interval

    def log_likelihood_without_bounds_check(self, x: np.array) -> np.array:
        return np.full((len(x),), self.log_pdf_value())

    def cdf(self, x: np.array) -> np.array:
        result = (x - self.lower) / (self.upper - self.lower)
        result = np.minimum(1, np.maximum(0, result))
        return result[:, 0]

    def univariate_log_mode(self) -> Tuple[AbstractCompositeSet, float]:
        return self.interval.as_composite_set(), self.log_pdf_value()

    def log_conditional_from_non_singleton_simple_interval(self, interval: SimpleInterval) -> Tuple[Self, float]:
        probability = self.probability_of_simple_event(SimpleEvent({self.variable: interval}))
        return self.__class__(self.variable, interval), np.log(probability)

    def sample(self, amount: int) -> np.array:
        return np.random.uniform(self.lower, self.upper, (amount, 1))

    def pdf_value(self) -> float:
        """
        Calculate the density of the uniform distribution.
        """
        return np.exp(self.log_pdf_value())

    def log_pdf_value(self) -> float:
        """
        Calculate the log-density of the uniform distribution.
        """
        return -np.log(self.upper - self.lower)

    def moment(self, order: OrderType, center: CenterType) -> MomentType:

        order = order[self.variable]
        center = center[self.variable]

        def evaluate_integral_at(x) -> float:
            r"""
            Helper method to calculate

            .. math::

                    \int_{-\infty}^{\infty} (x - center)^{order} pdf(x) dx = \frac{p(x-center)^(1+order)}{1+order}

            """
            return (self.pdf_value() * (x - center) ** (order + 1)) / (order + 1)

        result = evaluate_integral_at(self.upper) - evaluate_integral_at(self.lower)

        return VariableMap({self.variable: result})

    def __eq__(self, other):
        return (isinstance(other, UniformDistribution) and self.interval == other.interval
                and self.variable == other.variable)

    @property
    def representation(self):
        return f"U({self.variable.name} | {self.interval})"

    def __copy__(self):
        return self.__class__(self.variable, self.interval)

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "interval": self.interval.to_json()}

    @classmethod
    def _from_json(cls, data: Dict[str, Any]) -> Self:
        variable = Continuous.from_json(data["variable"])
        interval = SimpleInterval.from_json(data["interval"])
        return cls(variable, interval)

    def x_axis_points_for_plotly(self) -> List[Union[None, float]]:
        interval_size = self.upper - self.lower
        x = [self.lower - interval_size * PADDING_FACTOR_FOR_X_AXIS_IN_PLOT, self.lower, None,
             self.lower, self.upper, None,
             self.upper, self.upper + interval_size * PADDING_FACTOR_FOR_X_AXIS_IN_PLOT]
        return x

    def pdf_trace(self) -> go.Scatter:
        pdf_values = [0, 0, None, self.pdf_value(), self.pdf_value(), None, 0, 0]
        pdf_trace = go.Scatter(x=self.x_axis_points_for_plotly(),
                               y=pdf_values, mode='lines', name="Probability Density Function")
        return pdf_trace

    def cdf_trace(self) -> go.Scatter:
        x = self.x_axis_points_for_plotly()
        cdf_values = [value if value is None else self.cdf(np.array([[value]])) for value in x]
        cdf_trace = go.Scatter(x=x, y=cdf_values, mode='lines', name="Cumulative Distribution Function")
        return cdf_trace

    def plot(self, **kwargs) -> List:
        pdf_trace = self.pdf_trace()
        cdf_trace = self.cdf_trace()

        height = self.pdf_value() * SCALING_FACTOR_FOR_EXPECTATION_IN_PLOT

        mode_trace = (go.Scatter(x=[self.lower, self.lower, self.upper, self.upper],
                                 y=[0, height, height, 0], mode='lines+markers',
                                 name="Mode", fill="toself"))

        expectation = self.expectation([self.variable])[self.variable]
        expectation_trace = (
            go.Scatter(x=[expectation, expectation], y=[0, height], mode='lines+markers',
                       name="Expectation"))
        return [pdf_trace, cdf_trace, mode_trace, expectation_trace]

    def __hash__(self):
        return hash((self.variable.name, hash(self.interval)))
