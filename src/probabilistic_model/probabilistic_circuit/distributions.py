import copy
import random
from typing import Iterable, Tuple, Union, List, Optional, Any

import portion
from random_events.events import EncodedEvent, VariableMap, Event
from random_events.variables import Variable, Continuous, Symbolic, Integer, Discrete
from typing_extensions import Self

from probabilistic_model.probabilistic_circuit.units import Unit, DeterministicSumUnit
from probabilistic_model.probabilistic_model import OrderType, CenterType, MomentType


class UnivariateDistribution(Unit):

    def __init__(self, variable: Variable, parent: 'Unit' = None):
        super().__init__([variable], parent)

    @property
    def variable(self) -> Variable:
        return self.variables[0]

    def _pdf(self, value: Union[float, int]) -> float:
        """
        Evaluate the probability density function at the encoded `value`.
        :param value: The encoded value to evaluate the pdf on.
        :return: The density
        """
        raise NotImplementedError

    def _likelihood(self, event: Iterable) -> float:
        return self._pdf(list(event)[0])

    def pdf(self, value: Any) -> float:
        """
        Evaluate the probability density function at `value`.
        :param value: The value to evaluate the pdf on.
        :return: The density
        """
        return self._pdf(self.variable.encode(value))

    def likelihood(self, event: Iterable) -> float:
        return self.pdf(list(event)[0])

    def _parameter_copy(self):
        return copy.copy(self)

    def is_decomposable(self) -> bool:
        return True

    def is_smooth(self) -> bool:
        return True

    def is_deterministic(self) -> bool:
        return True

    def maximize_expressiveness(self) -> Self:
        return copy.copy(self)


class ContinuousDistribution(UnivariateDistribution):
    """
    Abstract base class for continuous distributions.
    """

    variables: Tuple[Continuous]

    @property
    def variable(self) -> Continuous:
        return self.variables[0]

    def _cdf(self, value: float) -> float:
        """
        Evaluate the cumulative distribution function at the encoded `value`.
        :param value: The encoded value to evaluate the cdf on.
        :return: The cumulative probability.
        """
        raise NotImplementedError

    def cdf(self, value: Any):
        """
        Evaluate the cumulative distribution function at `value`.
        :param value: The value to evaluate the cdf on.
        :return: The cumulative probability.
        """
        return self._cdf(self.variable.encode(value))


class UnivariateDiscreteDistribution(UnivariateDistribution):
    """
    Abstract base class for univariate discrete distributions.
    """
    variables: Tuple[Discrete]

    weights: List[float]
    """
    The probability of each value.
    """

    def __init__(self, variable: Discrete, weights: Iterable[float], parent=None):
        super().__init__(variable, parent)
        self.weights = list(weights)

        if len(self.weights) != len(self.variable.domain):
            raise ValueError("The number of weights has to be equal to the number of values of the variable.")

    def __repr__(self):
        return f"Categorical()"

    @property
    def domain(self) -> Event:
        return Event(
            {self.variable: [value for value, weight in zip(self.variable.domain, self.weights) if weight > 0]})

    @property
    def variable(self) -> Discrete:
        return self.variables[0]

    def _pdf(self, value: int) -> float:
        """
        Calculate the probability of a value.
        :param value: The index of the value to calculate the probability of.
        :return: The probability of the value.
        """
        return self.weights[value]

    def _probability(self, event: EncodedEvent) -> float:
        return sum(self._pdf(value) for value in event[self.variable])

    def _mode(self) -> Tuple[List[EncodedEvent], float]:
        maximum_weight = max(self.weights)
        mode = EncodedEvent(
            {self.variable: [index for index, weight in enumerate(self.weights) if weight == maximum_weight]})

        return [mode], maximum_weight

    def _conditional(self, event: EncodedEvent) -> Tuple[Self, float]:
        unnormalized_weights = [weight if index in event[self.variable] else 0. for index, weight in
                                enumerate(self.weights)]
        probability = sum(unnormalized_weights)

        if probability == 0:
            return None, 0

        normalized_weights = [weight / probability for weight in unnormalized_weights]
        return self.__class__(self.variable, normalized_weights), probability

    def __eq__(self, other):
        if not isinstance(other, SymbolicDistribution):
            return False
        return self.variable == other.variable and self.weights == other.weights

    def sample(self, amount: int) -> Iterable:
        return [random.choices(self.variable.domain, self.weights) for _ in range(amount)]

    def __copy__(self):
        return self.__class__(self.variable, self.weights)


class SymbolicDistribution(UnivariateDiscreteDistribution):
    """
    Class for symbolic (categorical) distributions.
    """

    variables: Tuple[Symbolic]

    @property
    def variable(self) -> Symbolic:
        return self.variables[0]

    def moment(self, order: OrderType, center: CenterType) -> MomentType:
        return VariableMap()


class IntegerDistribution(UnivariateDiscreteDistribution, ContinuousDistribution):
    """
    Abstract base class for integer distributions. Integer distributions also implement the methods of continuous
    distributions.
    """
    variables: Tuple[Integer]

    @property
    def variable(self) -> Integer:
        return self.variables[0]

    def _cdf(self, value: int) -> float:
        """
        Calculate the cumulative distribution function at `value`.
        :param value: The value to evaluate the cdf on.
        :return: The cumulative probability.
        """
        return sum(self._pdf(value) for value in range(value))

    def moment(self, order: OrderType, center: CenterType) -> MomentType:
        order = order[self.variable]
        center = center[self.variable]
        result = sum([self.pdf(value) * (value - center) ** order for value in self.variable.domain])
        return VariableMap({self.variable: result})


class UniformDistribution(ContinuousDistribution):
    """
    Class for uniform distributions over the half open interval [lower, upper).
    """

    lower: float
    """
    The included lower bound of the interval.
    """

    upper: float
    """
    The excluded upper bound of the interval.
    """

    def __init__(self, variable: Continuous, lower: float, upper: float, parent=None):
        super().__init__(variable, parent)
        if lower >= upper:
            raise ValueError("upper has to be greater than lower. lower: {}; upper: {}")
        self.lower = lower
        self.upper = upper

    @property
    def domain(self) -> Event:
        return Event({self.variable: portion.closedopen(self.lower, self.upper)})

    def pdf_value(self) -> float:
        """
        Calculate the density of the uniform distribution.
        """
        return 1 / (self.upper - self.lower)

    def _pdf(self, value: float) -> float:
        if value in self.domain[self.variable]:
            return self.pdf_value()
        else:
            return 0

    def _cdf(self, value: float) -> float:
        if value < self.lower:
            return 0
        elif value > self.upper:
            return 1
        else:
            return (value - self.lower) / (self.upper - self.lower)

    def _probability(self, event: EncodedEvent) -> float:
        interval: portion.Interval = event[self.variable]
        probability = 0.

        for interval_ in interval:
            probability += self.cdf(interval_.upper) - self.cdf(interval_.lower)

        return probability

    def _mode(self):
        return [self.domain.encode()], self.pdf_value()

    def sample(self, amount: int) -> List[List[float]]:
        return [[random.uniform(self.lower, self.upper)] for _ in range(amount)]

    def _conditional(self, event: EncodedEvent) -> Tuple[Optional[Union[DeterministicSumUnit, Self]], float]:
        interval = event[self.variable]
        resulting_distributions = []
        resulting_probabilities = []

        for interval_ in interval:

            # calculate the probability of the interval
            probability = self._probability(EncodedEvent({self.variable: interval_}))

            # if the probability is 0, skip this interval
            if probability == 0:
                continue

            resulting_probabilities.append(probability)
            intersection = self.domain[self.variable] & interval_
            resulting_distributions.append(UniformDistribution(self.variable, intersection.lower, intersection.upper))

        # if there is only one interval, don't create a deterministic sum
        if len(resulting_distributions) == 1:
            return resulting_distributions[0], resulting_probabilities[0]

        # if there are multiple intersections almost surely, create a deterministic sum
        elif len(resulting_distributions) > 1:
            deterministic_sum = DeterministicSumUnit(self.variables, resulting_probabilities)
            deterministic_sum.children = resulting_distributions
            return deterministic_sum.normalize(), sum(resulting_probabilities)

        else:
            return None, 0

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
        if not isinstance(other, UniformDistribution):
            return False
        return self.variable == other.variable and self.lower == other.lower and self.upper == other.upper

    def __repr__(self):
        return f"U{self.lower, self.upper}"

    def __copy__(self):
        return self.__class__(self.variable, self.lower, self.upper)


class DiracDeltaDistribution(ContinuousDistribution):
    """
    Class for Dirac delta distributions.
    """

    location: float
    """
    The location of the Dirac delta distribution.
    """

    density_cap: float
    """
    The density cap of the Dirac delta distribution.
    This value will be used to replace infinity in likelihood.
    """

    def __init__(self, variable: Continuous, location: float, density_cap: float = float("inf"), parent=None):
        super().__init__(variable, parent)
        self.location = location
        self.density_cap = density_cap

    @property
    def domain(self) -> Event:
        return Event({self.variable: portion.singleton(self.location)})

    def _pdf(self, value: float) -> float:
        if value == self.location:
            return self.density_cap
        else:
            return 0

    def _cdf(self, value: float) -> float:
        if value < self.location:
            return 0
        else:
            return 1

    def _probability(self, event: EncodedEvent) -> float:
        if self.location in event[self.variable]:
            return 1
        else:
            return 0

    def _mode(self):
        return [self.domain.encode()], self.density_cap

    def sample(self, amount: int) -> List[List[float]]:
        return [[self.location] for _ in range(amount)]

    def _conditional(self, event: EncodedEvent) -> Tuple[Optional[Union[DeterministicSumUnit, Self]], float]:
        if self.location in event[self.variable]:
            return self.__copy__(), 1
        else:
            return None, 0

    def moment(self, order: OrderType, center: CenterType) -> MomentType:
        order = order[self.variable]
        center = center[self.variable]

        if order == 1:
            return VariableMap({self.variable: self.location - center})
        elif order == 2:
            return VariableMap({self.variable: (self.location - center) ** 2})
        else:
            return VariableMap({self.variable: 0})

    def __eq__(self, other):
        if not isinstance(other, DiracDeltaDistribution):
            return False
        return (self.variable == other.variable and
                self.location == other.location and
                self.density_cap == other.density_cap)

    def __repr__(self):
        return f"DiracDelta({self.location}, {self.density_cap})"

    def __copy__(self):
        return self.__class__(self.variable, self.location, self.density_cap)
