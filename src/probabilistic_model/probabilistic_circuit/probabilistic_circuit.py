import itertools
import random
from typing import Tuple, Iterable

import networkx as nx
from random_events.events import EncodedEvent, VariableMap, Event
from random_events.variables import Variable
from typing_extensions import List, Optional, Union, Any, Self, Dict

from ..probabilistic_model import ProbabilisticModel, ProbabilisticModelWrapper, OrderType, CenterType, MomentType
from ..utils import SubclassJSONSerializer


def cache_inference_result(func):
    """
    Decorator for caching the result of a function call in a 'ProbabilisticCircuitMixin' object.
    """

    def wrapper(*args, **kwargs):

        self: ProbabilisticCircuitMixin = args[0]

        if not self.cache_result:
            return func(*args, **kwargs)

        if self.result_of_current_query is None:
            self.result_of_current_query = func(*args, **kwargs)
        return self.result_of_current_query

    return wrapper


def graph_inference_caching_wrapper(func):
    """
    Decorator for (re)setting the caching flag and results in a Probabilistic Circuit.
    """
    def wrapper(*args, **kwargs):

        # highlight type of self
        self: ProbabilisticCircuit = args[0]

        # get the root
        root = self.root

        # recursively activate caching
        root.cache_result = True

        # evaluate the function
        result = func(*args, **kwargs)

        # if the result is None, the root has been destroyed
        if result is None:
            return None

        # reset result
        root.reset_result_of_current_query()

        # reset flag
        root.cache_result = False
        return result
    return wrapper


class ProbabilisticCircuitMixin(ProbabilisticModel, SubclassJSONSerializer):
    """
    Mixin class for all components of a probabilistic circuit.
    """

    probabilistic_circuit: 'ProbabilisticCircuit'
    """
    The circuit this component is part of. 
    """

    representation: str = None
    """
    The string representing this component.
    """

    result_of_current_query: Any = None
    """
    Cache of the result of the current query. If the circuit would be queried multiple times,
    this would be returned instead.
    """

    _cache_result = False
    """
    Flag for caching the result of the current query.
    """

    def __init__(self, variables: Optional[Iterable[Variable]] = None):
        super().__init__(variables)
        self.probabilistic_circuit = ProbabilisticCircuit()
        self.probabilistic_circuit.add_node(self)

    def __repr__(self):
        return self.representation

    @property
    def subcircuits(self) -> List['ProbabilisticCircuitMixin']:
        """
        :return: The subcircuits of this unit.
        """
        return list(self.probabilistic_circuit.successors(self))

    @property
    def domain(self) -> Event:
        """
        The domain of the model. The domain describes all events that have :math:`P(event) > 0`.

        :return: An event describing the domain of the model.
        """
        domain = Event()
        for subcircuit in self.subcircuits:
            target_domain = subcircuit.domain
            domain = domain | target_domain
        return domain

    def mount(self, other: 'ProbabilisticCircuitMixin'):
        """
        Mount another unit including its descendants. There will be no edge from `self` to `other`.
        :param other: The other circuit or unit to mount.
        """

        descendants = nx.descendants(other.probabilistic_circuit, other)
        descendants = descendants.union([other])
        subgraph = other.probabilistic_circuit.subgraph(descendants)

        # gather all weighted and non-weighted edges from the subgraph
        weighted_edges = []
        normal_edges = []

        for edge in subgraph.edges:
            edge_ = subgraph.edges[edge]

            if "weight" in edge_.keys():
                weight = edge_["weight"]
                weighted_edges.append((*edge, weight))
            else:
                normal_edges.append(edge)

        self.probabilistic_circuit.add_nodes_from(subgraph.nodes())
        self.probabilistic_circuit.add_edges_from(normal_edges)
        self.probabilistic_circuit.add_weighted_edges_from(weighted_edges)

    @property
    def cache_result(self) -> bool:
        return self._cache_result

    @cache_result.setter
    def cache_result(self, value: bool):
        """
        Set the caching of the result flag in this and every sub-circuit.
        If a sub-circuit has the flag already set to the value, it will not recurse in that sub-circuit.
        :param value: The value to set the flag to.
        """
        self._cache_result = value
        for subcircuit in self.subcircuits:
            if subcircuit.cache_result != value:
                subcircuit.cache_result = value

    def filter_variable_map_by_self(self, variable_map: VariableMap):
        """
        Filter a variable map by the variables of this unit.

        :param variable_map: The map to filter
        :return: The map filtered by the variables of this unit.
        """
        variables = self.variables
        return variable_map.__class__(
            {variable: value for variable, value in variable_map.items() if variable in variables})

    @property
    def variables(self) -> tuple[Variable, ...]:
        variables = set([variable for distribution in self.leaves for variable in distribution.variables])
        return tuple(sorted(variables))

    @property
    def leaves(self) -> List['ProbabilisticCircuitMixin']:
        return [node for node in nx.descendants(self.probabilistic_circuit, self) if
                self.probabilistic_circuit.out_degree(node) == 0]

    def reset_result_of_current_query(self):
        """
        Reset the result of the current query recursively.
        If a sub-circuit has the result already reset, it will not recurse in that sub-circuit.
        """
        self.result_of_current_query = None
        for subcircuit in self.subcircuits:
            if subcircuit.result_of_current_query is not None:
                subcircuit.reset_result_of_current_query()

    def remove_entire_subgraph(self):
        """
        Remove all descendants from this node.
        """
        for node in nx.descendants(self.probabilistic_circuit, self):
            self.probabilistic_circuit.remove_node(node)

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return (isinstance(other, self.__class__)
                and self.subcircuits == other.subcircuits)

    def __copy__(self):
        raise NotImplementedError()

    def empty_copy(self) -> Self:
        """
        Creat a copy of this circuit without any subcircuits. Only the parameters should be copied.
        This is used whenever a new circuit has to be created
        during inference.

        :return: A copy of this circuit without any subcircuits.
        """
        return self.__class__()


class SmoothSumUnit(ProbabilisticCircuitMixin):
    representation = "+"

    @property
    def weighted_subcircuits(self) -> List[Tuple[float, 'ProbabilisticCircuitMixin']]:
        """
        :return: The weighted subcircuits of this unit.
        """
        return [(self.probabilistic_circuit.edges[self, subcircuit]["weight"], subcircuit)
                for subcircuit in self.subcircuits]

    @property
    def weights(self) -> List[float]:
        """
        :return: The weights of the subcircuits of this unit.
        """
        return [weight for weight, _ in self.weighted_subcircuits]

    @cache_inference_result
    def _likelihood(self, event: Iterable) -> float:

        result = 0.

        for weight, subcircuit in self.weighted_subcircuits:
            result += weight * subcircuit._likelihood(event)

        return result

    @cache_inference_result
    def _probability(self, event: EncodedEvent) -> float:

        result = 0.

        for weight, subcircuit in self.weighted_subcircuits:
            result += weight * subcircuit._probability(event)

        return result

    @cache_inference_result
    def _conditional(self, event: EncodedEvent) -> Tuple[Optional[Self], float]:

        subcircuit_probabilities = []
        conditional_subcircuits = []
        total_probability = 0

        result = self.empty_copy()

        for weight, subcircuit in self.weighted_subcircuits:
            conditional, subcircuit_probability = subcircuit._conditional(event)

            if subcircuit_probability == 0:
                continue

            subcircuit_probability *= weight
            total_probability += subcircuit_probability
            subcircuit_probabilities.append(subcircuit_probability)
            conditional_subcircuits.append(conditional)

        if total_probability == 0:
            return None, 0

        # normalize probabilities
        normalized_probabilities = [p/total_probability for p in subcircuit_probabilities]

        # add edges and subcircuits
        for weight, subcircuit in zip(normalized_probabilities, conditional_subcircuits):
            result.mount(subcircuit)
            result.probabilistic_circuit.add_edge(result, subcircuit, weight=weight)

        return result, total_probability

    @cache_inference_result
    def sample(self, amount: int) -> Iterable:
        """
        Sample from the sum node using the latent variable interpretation.
        """

        weights, subcircuits = zip(*self.weighted_subcircuits)

        # sample the latent variable
        states = random.choices(list(range(len(weights))), weights=weights, k=amount)

        # sample from the children
        result = []
        for index, subcircuit in enumerate(self.subcircuits):
            result.extend(subcircuit.sample(states.count(index)))
        return result

    @cache_inference_result
    def moment(self, order: OrderType, center: CenterType) -> MomentType:
        # create a map for orders and centers
        order_of_self = self.filter_variable_map_by_self(order)
        center_of_self = self.filter_variable_map_by_self(center)

        # initialize result
        result = VariableMap({variable: 0 for variable in order_of_self})

        # for every weighted child
        for weight, subcircuit in self.weighted_subcircuits:

            # calculate the moment of the child
            sub_circuit_moment = subcircuit.moment(order_of_self, center_of_self)

            # add up the linear combination of the child moments
            for variable, moment in sub_circuit_moment.items():
                result[variable] += weight * moment

        return result

    def marginal(self, variables: Iterable[Variable]) -> Optional[Self]:

        # if this node has no variables that are required in the marginal, remove it.
        if set(self.variables).intersection(set(variables)) == set():
            return None

        result = self.empty_copy()

        # propagate to sub-circuits
        for weight, subcircuit in self.weighted_subcircuits:
            marginal = subcircuit.marginal(variables)

            if marginal is None:
                continue

            result.mount(marginal)
            result.probabilistic_circuit.add_edge(result, marginal, weight=weight)
        return result

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return (isinstance(other, self.__class__)
                and self.weighted_subcircuits == other.weighted_subcircuits)

    def to_json(self):
        return {
            **super().to_json(),
            "weighted_subcircuits": [(weight, subcircuit.to_json())
                                     for weight, subcircuit in self.weighted_subcircuits]
        }

    @classmethod
    def _from_json(cls, data: Dict[str, Any]) -> Self:
        result = cls()
        for weight, subcircuit_data in data["weighted_subcircuits"]:
            subcircuit = ProbabilisticCircuitMixin.from_json(subcircuit_data)
            result.mount(subcircuit)
            result.probabilistic_circuit.add_edge(result, subcircuit, weight=weight)
        return result

    def __copy__(self):
        result = self.empty_copy()
        for weight, subcircuit in self.weighted_subcircuits:
            copied_subcircuit = subcircuit.__copy__()
            result.mount(copied_subcircuit)
            result.probabilistic_circuit.add_edge(result, copied_subcircuit, weight=weight)
        return result


class DeterministicSumUnit(SmoothSumUnit):
    """
    Deterministic Sum Units for Probabilistic Circuits
    """

    representation = "⊕"

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

    @cache_inference_result
    def _mode(self) -> Tuple[Iterable[EncodedEvent], float]:
        modes = []
        likelihoods = []

        # gather all modes from the children
        for weight, subcircuit in self.weighted_subcircuits:
            mode, likelihood = subcircuit._mode()
            modes.append(mode)
            likelihoods.append(weight * likelihood)

        # get the most likely result
        maximum_likelihood = max(likelihoods)

        result = []

        # gather all results that are maximum likely
        for mode, likelihood in zip(modes, likelihoods):
            if likelihood == maximum_likelihood:
                result.extend(mode)

        modes = self.merge_modes_if_one_dimensional(result)
        return modes, maximum_likelihood


class DecomposableProductUnit(ProbabilisticCircuitMixin):
    """
    Decomposable Product Units for Probabilistic Circuits
    """

    representation = "⊗"

    @cache_inference_result
    def _likelihood(self, event: Iterable) -> float:

        variables = self.variables

        result = 1.

        for subcircuit in self.subcircuits:
            subcircuit_variables = subcircuit.variables
            partial_event = [event[variables.index(variable)] for variable in subcircuit_variables]
            result *= subcircuit._likelihood(partial_event)

        return result

    @cache_inference_result
    def _probability(self, event: EncodedEvent) -> float:

        result = 1.

        for subcircuit in self.subcircuits:

            # load variables of this subcircuit
            subcircuit_variables = subcircuit.variables

            # construct partial event for child
            subcircuit_event = EncodedEvent({variable: event[variable] for variable in subcircuit_variables})

            # multiply results
            result *= subcircuit._probability(subcircuit_event)

        return result

    @cache_inference_result
    def _mode(self) -> Tuple[Iterable[EncodedEvent], float]:

        modes = []
        resulting_likelihood = 1.

        # gather all modes from the children
        for subcircuit in self.subcircuits:
            mode, likelihood = subcircuit._mode()
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

    @cache_inference_result
    def _conditional(self, event: EncodedEvent) -> Tuple[Self, float]:
        # initialize probability
        probability = 1.

        # create new node with new circuit attached to it
        resulting_node =  self.empty_copy()

        for subcircuit in self.subcircuits:

            # get conditional child and probability in pre-order
            conditional_subcircuit, conditional_probability = subcircuit._conditional(event)

            # if any is 0, the whole probability is 0
            if conditional_probability == 0:
                return None, 0

            resulting_node.mount(conditional_subcircuit)
            resulting_node.probabilistic_circuit.add_edge(resulting_node, conditional_subcircuit)
            # update probability and children
            probability *= conditional_probability

        return resulting_node, probability

    @cache_inference_result
    def sample(self, amount: int) -> List[List[Any]]:

        variables = self.variables
        # list for the samples content in the same order as self.variables
        rearranged_sample = [[None] * len(variables)] * amount

        for subcircuit in self.subcircuits:
            sample_subset = subcircuit.sample(amount)

            for sample_index in range(amount):
                for child_variable_index, variable in enumerate(subcircuit.variables):
                    rearranged_sample[sample_index][variables.index(variable)] = sample_subset[sample_index][
                        child_variable_index]

        return rearranged_sample

    @cache_inference_result
    def moment(self, order: OrderType, center: CenterType) -> MomentType:

        # initialize result
        result = VariableMap()

        for subcircuit in self.subcircuits:
            # calculate the moment of the child
            child_moment = subcircuit.moment(order, center)

            result = VariableMap({**result, **child_moment})

        return result

    def marginal(self, variables: Iterable[Variable]) -> Optional[Self]:
        # if this node has no variables that are required in the marginal, remove it.
        if set(self.variables).intersection(set(variables)) == set():
            return None

        result = self.empty_copy()

        # propagate to sub-circuits
        for subcircuit in self.subcircuits:
            marginal = subcircuit.marginal(variables)

            if marginal is None:
                continue

            result.mount(marginal)
            result.probabilistic_circuit.add_edge(result, marginal)
        return result

    def to_json(self) -> Dict[str, Any]:
        return {
            **super().to_json(),
            "subcircuits": [subcircuit.to_json() for subcircuit in self.subcircuits]
        }

    @classmethod
    def _from_json(cls, data: Dict[str, Any]) -> Self:
        result = cls()
        for subcircuit_data in data["subcircuits"]:
            subcircuit = ProbabilisticCircuitMixin.from_json(subcircuit_data)
            result.mount(subcircuit)
            result.probabilistic_circuit.add_edge(result, subcircuit)
        return result

    def __copy__(self):
        result = self.__class__()
        for subcircuit in self.subcircuits:
            copied_subcircuit = subcircuit.__copy__()
            result.mount(copied_subcircuit)
            result.probabilistic_circuit.add_edge(result, copied_subcircuit)
        return result


class ProbabilisticCircuit(ProbabilisticModel, nx.DiGraph, SubclassJSONSerializer):
    """
    Probabilistic Circuits as a directed, rooted, acyclic graph.
    """

    def __init__(self):
        super().__init__(None)
        nx.DiGraph.__init__(self)

    @property
    def variables(self) -> tuple[Variable, ...]:
        return self.root.variables

    @property
    def leaves(self) -> List[ProbabilisticCircuitMixin]:
        return self.root.leaves

    def is_valid(self) -> bool:
        """
        Check if this graph is:

        - acyclic
        - connected

        :return: True if the graph is valid, False otherwise.
        """
        return nx.is_directed_acyclic_graph(self) and nx.is_weakly_connected(self)

    def add_node(self, node: ProbabilisticCircuitMixin, **attr):

        # write self as the nodes circuit
        node.probabilistic_circuit = self

        # call super
        super().add_node(node, **attr)

    def add_nodes_from(self, nodes_for_adding, **attr):
        for node in nodes_for_adding:
            self.add_node(node, **attr)

    @property
    def root(self) -> ProbabilisticCircuitMixin:
        """
        The root of the circuit is the node with in-degree 0.
        This is the output node, that will perform the final computation.

        :return: The root of the circuit.
        """
        possible_roots = [node for node in self.nodes() if self.in_degree(node) == 0]
        if len(possible_roots) > 1:
            raise ValueError(f"More than one root found. Possible roots are {possible_roots}")

        return possible_roots[0]

    @graph_inference_caching_wrapper
    def _likelihood(self, event: Iterable) -> float:
        return self.root._likelihood(event)

    @graph_inference_caching_wrapper
    def _probability(self, event: EncodedEvent) -> float:
        return self.root._probability(event)

    @graph_inference_caching_wrapper
    def _mode(self) -> Tuple[Iterable[EncodedEvent], float]:
        return self.root._mode()

    @graph_inference_caching_wrapper
    def _conditional(self, event: EncodedEvent) -> Tuple[Optional[Self], float]:
        conditional, probability = self.root._conditional(event)
        if conditional is None:
            return None, 0
        return conditional.probabilistic_circuit, probability

    @graph_inference_caching_wrapper
    def marginal(self, variables: Iterable[Variable]) -> Optional[Self]:
        root = self.root
        result = self.root.marginal(variables)
        if result is None:
            return None
        root.reset_result_of_current_query()
        return result.probabilistic_circuit

    @graph_inference_caching_wrapper
    def sample(self, amount: int) -> Iterable:
        return self.root.sample(amount)

    @graph_inference_caching_wrapper
    def moment(self, order: OrderType, center: CenterType) -> MomentType:
        return self.root.moment(order, center)

    @property
    def domain(self) -> Event:
        root = self.root
        result = self.root.domain
        root.reset_result_of_current_query()
        return result

    def __eq__(self, other: 'ProbabilisticCircuit'):
        return self.root == other.root

    def to_json(self) -> Dict[str, Any]:
        return {
            **super().to_json(),
            "root": self.root.to_json()
        }

    @classmethod
    def _from_json(cls, data: Dict[str, Any]) -> Self:
        root = ProbabilisticCircuitMixin.from_json(data["root"])
        return root.probabilistic_circuit