import itertools
import random
from typing import Iterable, Tuple, List

from anytree import NodeMixin
from random_events.events import EncodedEvent
from random_events.variables import Variable

from probabilistic_model.probabilistic_model import ProbabilisticModel


class Unit(ProbabilisticModel, NodeMixin):
    """
    Abstract class for nodes used in a probabilistic circuit
    """

    def __init__(self, variables: Iterable[Variable], parent: 'Unit' = None):
        self.parent = parent
        super().__init__(variables)
        NodeMixin.__init__(self)

    def variable_indices_of_child(self, child: 'Unit') -> List[int]:
        """
        Get the list of the variables' indices in self that are also in child.

        :param child: The child to check for.
        :return: The indices
        """
        return list(index for index, variable in enumerate(self.variables) if variable in child.variables)

    def __add__(self, other) -> 'SumUnit':
        if not isinstance(other, Unit):
            raise ValueError(f"Cannot add a Probabilistic Circuit with {type(other)}.")

        joined_variables = set(self.variables).union(other.variables)
        result = SumUnit(variables=sorted(joined_variables), weights=[.5, .5])
        result.children = [self, other]
        return result

    def __mul__(self, other) -> 'ProductUnit':
        if not isinstance(other, Unit):
            raise ValueError(f"Cannot add a Probabilistic Circuit with {type(other)}.")

        joined_variables = set(self.variables).union(other.variables)

        # check if product is decomposable
        if set(self.variables).intersection(other.variables) == set():
            result = DecomposableProductUnit(variables=sorted(joined_variables))
        else:
            result = ProductUnit(variables=sorted(joined_variables))
        result.children = [self, other]
        return result


class SumUnit(Unit):
    """
    Sum node used in a probabilistic circuit
    """

    weights: Iterable
    """The weights of the convex sum unit."""

    def __init__(self, variables: Iterable[Variable], weights: Iterable, parent: 'Unit' = None):
        super().__init__(variables, parent)
        self.weights = weights

    def _likelihood(self, event: Iterable) -> float:
        return sum([weight * child._likelihood(event) for weight, child in zip(self.weights, self.children)])

    def _probability(self, event: EncodedEvent) -> float:
        return sum([weight * child._probability(event) for weight, child in zip(self.weights, self.children)])

    def sample(self, amount: int) -> Iterable:
        """
        Sample from the sum node using the latent variable interpretation.
        """

        # sample the latent variable
        states = random.choices(list(range(len(self.children))), weights=self.weights, k=amount)

        # sample from the children
        result = []
        for index, child in self.children:
            result.extend(child.sample(states.count(index)))
        return result


class DeterministicSumUnit(SumUnit):
    """
    Deterministic sum node used in a probabilistic circuit
    """

    def merge_modes_if_one_dimensional(self, modes: List[EncodedEvent]) -> List[EncodedEvent]:
        """
        Merge the modes in `modes` to one mode if the model is one dimensional.

        :param modes: The modes to merge.
        :return: The (possibly) merged modes.
        """
        if len(self.variables) > 1:
            return modes

        # merge modes
        mode = modes[0]

        for mode_ in modes[1:]:
            mode = mode | mode_

        return [mode]

    def _mode(self) -> Tuple[Iterable[EncodedEvent], float]:
        """
        Calculate the mode of the model.
        As there may exist multiple modes, this method returns an Iterable of modes and their likelihood.

        :return: The internal representation of the mode and the likelihood.
        """
        modes = []
        likelihoods = []

        # gather all modes from the children
        for weight, child in zip(self.weights, self.children):
            mode, likelihood = child._mode()
            modes.append(mode)
            likelihoods.append(weight * likelihood)

        # get the most likely result
        maximum_likelihood = max(likelihoods)

        result = []

        # gather all results that are maximum likely
        for mode, likelihood in zip(modes, likelihoods):
            if likelihood == maximum_likelihood:
                result.extend(mode)

        return self.merge_modes_if_one_dimensional(result), maximum_likelihood

    @staticmethod
    def from_sum_unit(unit: SumUnit) -> 'DeterministicSumUnit':
        """
        Downcast a sum unit to a deterministic sum unit.

        :param unit: The sum unit to downcast.
        """
        result = DeterministicSumUnit(variables=unit.variables, weights=unit.weights)
        result.children = unit.children
        return result


class ProductUnit(Unit):
    """
    Product node used in a probabilistic circuit
    """


class DecomposableProductUnit(ProductUnit):
    """
    Decomposable product node used in a probabilistic circuit
    """

    def _likelihood(self, event: Iterable) -> float:
        result = 1.

        for child in self.children:
            indices = self.variable_indices_of_child(child)

            partial_event = [event[index] for index in indices]

            result = result * child._likelihood(partial_event)

        return result

    def _probability(self, event: EncodedEvent) -> float:
        result = 1.

        for child in self.children:
            # construct partial event for child
            result = result * child._probability(EncodedEvent({variable: event[variable] for variable in
                                                               self.variables}))

        return result

    def _mode(self) -> Tuple[Iterable[EncodedEvent], float]:
        """
        Calculate the mode of the model.
        As there may exist multiple modes, this method returns an Iterable of modes and their likelihood.

        :return: The internal representation of the mode and the likelihood.
        """
        modes = []
        resulting_likelihood = 1.

        # gather all modes from the children
        for child in self.children:
            mode, likelihood = child._mode()
            modes.append(mode)
            resulting_likelihood *= likelihood

        result = []

        # perform the cartesian product of all modes
        for mode_combination in itertools.product(*modes):

            # form the intersection of the modes inside one cartesian product mode
            mode = mode_combination[0]
            for mode_ in mode_combination[1:]:
                mode = mode | mode_

            result.append(mode)

        return result, resulting_likelihood
