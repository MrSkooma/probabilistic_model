from __future__ import annotations

import itertools
import unittest
from abc import abstractmethod
from functools import cached_property

import queue
import random
from typing import Tuple, Iterable, TYPE_CHECKING

import networkx as nx
import numpy as np
import random_events
from pygments.lexer import default
from random_events.interval import Interval
from random_events.product_algebra import VariableMap, SimpleEvent, Event
from random_events.set import SetElement
from random_events.variable import Variable, Symbolic
from sortedcontainers import SortedSet
from sympy.abc import alpha
from sympy.solvers.diophantine.diophantine import Univariate
import plotly.graph_objects as go
from typing_extensions import List, Optional, Any, Self, Dict, Tuple, Iterable, TYPE_CHECKING
import tqdm

from probabilistic_model.error import IntractableError
from probabilistic_model.probabilistic_model import ProbabilisticModel, OrderType, CenterType, MomentType
from random_events.utils import SubclassJSONSerializer
import matplotlib.pyplot as plt

import matplotlib.pyplot as plt
import os
import PIL

if TYPE_CHECKING:
    from probabilistic_model.probabilistic_circuit.nx.distributions import UnivariateDistribution, SymbolicDistribution, DiscreteDistribution


def cache_inference_result(func):
    """
    Decorator for caching the result of a function call in a 'ProbabilisticCircuitMixin' object.
    """

    def wrapper(*args, **kwargs):

        self: ProbabilisticCircuitMixin = args[0]
        return func(*args, **kwargs)
        # if not self.cache_result:
        #     return func(*args, **kwargs)
        # if self.result_of_current_query is None:
        #     self.result_of_current_query = func(*args, **kwargs)
        # return self.result_of_current_query

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

    probabilistic_circuit: ProbabilisticCircuit
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

    _cache_result: bool = False
    """
    Flag for caching the result of the current query.
    """

    def __init__(self):
        self.probabilistic_circuit = ProbabilisticCircuit()
        self.probabilistic_circuit.add_node(self)

    @property
    def subcircuits(self) -> List[ProbabilisticCircuitMixin]:
        """
        :return: The subcircuits of this unit.
        """
        return list(self.probabilistic_circuit.successors(self))

    def support(self) -> Event:
        return self.support

    @abstractmethod
    @cached_property
    def support(self) -> Event:
        raise NotImplementedError

    @property
    @abstractmethod
    def variables(self) -> SortedSet:
        raise NotImplementedError

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

    @property
    def leaves(self) -> List[UnivariateDistribution]:
        return [node for node in nx.descendants(self.probabilistic_circuit, self) if
                self.probabilistic_circuit.out_degree(node) == 0]

    def update_variables(self, new_variables: VariableMap):
        """
        Update the variables of this unit and its descendants.

        :param new_variables: A map that maps the variables that should be replaced to their new variable.
        """
        for leaf in self.leaves:
            if leaf.variable in new_variables:
                leaf.variable = new_variables[leaf.variable]

    def mount(self, other: ProbabilisticCircuitMixin):
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

    @abstractmethod
    def is_deterministic(self) -> bool:
        """
        Calculate if this circuit is deterministic or not.
        """
        raise NotImplementedError

    def filter_variable_map_by_self(self, variable_map: VariableMap):
        """
        Filter a variable map by the variables of this unit.

        :param variable_map: The map to filter
        :return: The map filtered by the variables of this unit.
        """
        variables = self.variables
        return variable_map.__class__(
            {variable: value for variable, value in variable_map.items() if variable in variables})

    def log_conditional(self, event: Event) -> Tuple[Optional[ProbabilisticCircuitMixin], float]:

        # skip trivial case
        if event.is_empty():
            return None, -np.inf

        # if the event is easy, don't create a proxy node
        elif len(event.simple_sets) == 1:
            return self.log_conditional_of_simple_event(event.simple_sets[0])

        # construct the proxy node
        result = SumUnit()
        total_probability = 0

        for simple_event in event.simple_sets:

            # reset cache
            self.reset_result_of_current_query()

            conditional, log_probability = self.log_conditional_of_simple_event(simple_event)

            # skip if impossible
            if log_probability == -np.inf:
                continue

            probability = np.exp(log_probability)

            total_probability += probability
            result.add_subcircuit(conditional, probability)

        if total_probability == 0:
            return None, -np.inf

        result.normalize()

        return result, np.log(total_probability)

    @abstractmethod
    # @cache_inference_result
    def log_conditional_of_simple_event(self, event: SimpleEvent) -> Tuple[Optional[Self], float]:
        """
        Construct the conditional circuit from a simple event.

        :param: The simple event to condition on.
        :return: the conditional circuit and log(p(event))
        """
        raise NotImplementedError

    def reset_result_of_current_query(self):
        """
        Reset the result of the current query recursively.
        If a sub-circuit has the result already reset, it will not recurse in that sub-circuit.
        """
        self.result_of_current_query = None
        for subcircuit in self.subcircuits:
            if subcircuit.result_of_current_query is not None:
                subcircuit.reset_result_of_current_query()

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.subcircuits == other.subcircuits

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

    def simplify(self) -> Self:
        """
        Simplify the circuit by removing nodes and redirected edges that have no impact.
        Essentially, this method transform the circuit into an alternating order of sum and product units.

        :return: The simplified circuit.
        """
        raise NotImplementedError()

    def plot_structure(self):
        """
        Plot the structure of the circuit.
        """

        # create the subgraph with this node as root
        subgraph = nx.subgraph(self.probabilistic_circuit, list(nx.descendants(self.probabilistic_circuit, self)) +
                               [self])

        # do a layer-wise BFS
        layers = list(nx.bfs_layers(subgraph, [self]))

        # calculate the positions of the nodes
        maximum_layer_width = max([len(layer) for layer in layers])
        positions = {}
        for depth, layer in enumerate(layers):
            number_of_nodes = len(layer)
            positions_in_layer = np.linspace(0, maximum_layer_width, number_of_nodes, endpoint=False)
            positions_in_layer += (maximum_layer_width - len(layer)) / (2 * len(layer))
            for position, node in zip(positions_in_layer, layer):
                positions[node] = (depth, position)

        # draw the edges
        alpha_for_edges = [subgraph.get_edge_data(*edge)["weight"] if subgraph.get_edge_data(*edge) else 1.
                          for edge in subgraph.edges]
        nx.draw_networkx_edges(subgraph, positions, alpha=alpha_for_edges)

        # draw the nodes and labels
        nx.draw_networkx_nodes(subgraph, positions)
        labels = {node: node.representation for node in subgraph.nodes}
        nx.draw_networkx_labels(subgraph, positions, labels)
        plt.show()

    def draw_io_style(self) -> Dict[str, Any]:
        return {
            "style": self.label,
            "width": 30,
            "height": 30,
            "label": self.representation
        }



def nodes_weights(circuit: ProbabilisticCircuit) -> dict:
    node_weights = {hash(circuit.root): [1]}
    seen_nodes = set()
    seen_nodes.add(hash(circuit.root))
    to_visit_nodes = queue.Queue()

    to_visit_nodes.put(circuit.root)
    while not to_visit_nodes.empty():
        node = to_visit_nodes.get()
        succ_iter = circuit.successors(node)
        for succ in succ_iter:
            if circuit.has_edge(node, succ):
                weight = circuit.get_edge_data(node, succ)["weight"]
                node_weights[hash(succ)] = [old * weight for old in node_weights[hash(node)]] + node_weights.get(
                    hash(succ), [])
                if hash(succ) not in seen_nodes:
                    seen_nodes.add(hash(succ))
                    to_visit_nodes.put(succ)
    return node_weights


class SumUnit(ProbabilisticCircuitMixin):
    label = 'shape=stencil(tZVtb4MgEMc/DW8XHmLSt43bvgdTOkkpEKBr9+2LoGvxgXULGqPh/tzPu5MDQGrbUc0Ahh0grwBjBKF/+vFlMqZWs8ZF44FfWRvN1hl1ZBfeugHAZccMd71K3gDc+zn9TepGSekJXEmbKA+6h1EuvS+8Rtjw7e9kpD3/xBwzQ4TRCvD789iXahsw2ijeFDtGXzzecuA0YrTVjysGRv/Hktpb1hY3qT9oc/w06izbudeqdlCGLQg/MhciNl4mzTihUUIZb4jvkAfABIYrX6bHzvbbwb3Dcd5P037iTBjlk/pi97pXk4VS5dgjQnC5jtg9hUijQOmqqrKVWY5i9xdE+PkrdRoLX6rCi1toPjMmBNf2N8b0gJgeIEVTD26zrgjWeIAFww0=);whiteSpace=wrap;html=1;labelPosition=center;verticalLabelPosition=bottom;align=center;verticalAlign=top;'
    image = os.path.join(os.path.dirname(__file__), "../../../", "resources", "icons", "Smoothsum.png")

    @property
    def representation(self) -> str:
        return "+"

    @property
    def weighted_subcircuits(self) -> List[Tuple[float, 'ProbabilisticCircuitMixin']]:
        """
        :return: The weighted subcircuits of this unit.
        """
        return [(self.probabilistic_circuit.edges[self, subcircuit]["weight"], subcircuit) for subcircuit in
                self.subcircuits]

    @property
    def variables(self) -> SortedSet:
        return self.subcircuits[0].variables

    @property
    def latent_variable(self) -> Symbolic:
        name = f"{hash(self)}.latent"
        enum_elements = {"EMPTY_SET": -1}
        enum_elements.update({str(hash(subcircuit)): index for index, subcircuit in enumerate(self.subcircuits)})
        domain = SetElement(name, enum_elements)
        return Symbolic(name, domain)

    def add_subcircuit(self, subcircuit: ProbabilisticCircuitMixin, weight: float):
        """
        Add a subcircuit to the children of this unit.

        .. note::

            This method does not normalize the edges to the subcircuits.


        :param subcircuit: The subcircuit to add.
        :param weight: The weight of the subcircuit.
        """
        self.mount(subcircuit)
        self.probabilistic_circuit.add_edge(self, subcircuit, weight=weight)

    @cached_property
    def support(self) -> Event:
        support = self.subcircuits[0].support
        for subcircuit in self.subcircuits[1:]:
            support |= subcircuit.support
        return support

    @property
    def weights(self) -> np.array:
        """
        :return: The weights of the subcircuits.
        """
        return np.array([weight for weight, _ in self.weighted_subcircuits])

    @cache_inference_result
    def log_likelihood(self, events: np.array) -> np.array:
        result = np.zeros(len(events))
        for weight, subcircuit in self.weighted_subcircuits:
            subcircuit_likelihood = subcircuit.likelihood(events)
            result += weight * subcircuit_likelihood
        return np.log(result)

    def cdf(self, events: np.array) -> np.array:
        result = np.zeros(len(events))
        for weight, subcircuit in self.weighted_subcircuits:
            subcircuit_cdf = subcircuit.cdf(events)
            result += weight * subcircuit_cdf
        return result

    @cache_inference_result
    def probability_of_simple_event(self, event: SimpleEvent) -> float:
        return sum([weight * subcircuit.probability_of_simple_event(event) for weight, subcircuit in
                    self.weighted_subcircuits])

    def log_conditional_of_simple_event(self, event: SimpleEvent) -> Tuple[Optional[Self], float]:
        # initialize result
        result = self.empty_copy()

        # for every weighted subcircuit
        for weight, subcircuit in self.weighted_subcircuits:

            # condition the subcircuit
            conditional, subcircuit_log_probability = subcircuit.log_conditional_of_simple_event(event)

            # skip impossible subcircuits
            if conditional is None:
                continue

            subcircuit_probability = np.exp(subcircuit_log_probability)
            # add subcircuit
            result.add_subcircuit(conditional, weight * subcircuit_probability)

        # check if the result is valid
        total_probability = sum(result.weights)
        if total_probability == 0:
            return None, -np.inf

        # normalize probabilities
        result.normalize()

        return result, np.log(total_probability)

    def sample(self, amount: int) -> np.array:
        """
        Sample from the sum node using the latent variable interpretation.
        """
        weights, subcircuits = self.weights, self.subcircuits

        # pseudo sample the latent variables by evaluating the events w. r. t. their probabilities (histogram)
        counts = np.floor(weights * amount).astype(int)

        # if any samples are missing
        missing_samples = amount - counts.sum()
        if missing_samples > 0:

            # sample the missing latent states using actual randomness
            states = np.random.choice(np.arange(len(self.weights)), size=missing_samples, p=weights)
            unique_values, missing_counts = np.unique(states, return_counts=True)
            counts[unique_values] += missing_counts

        # sample from the children
        result = self.subcircuits[0].sample(counts[0])
        for amount, subcircuit in zip(counts[1:], self.subcircuits[1:]):
            result = np.concatenate((result, subcircuit.sample(amount)))
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

    @cache_inference_result
    def marginal(self, variables: Iterable[Variable]) -> Optional[Self]:

        # if this node has no variables that are required in the marginal, remove it.
        if set(self.variables).intersection(set(variables)) == set():
            return None

        result = self.empty_copy()

        # propagate to sub-circuits
        for weight, subcircuit in self.weighted_subcircuits:
            result.add_subcircuit(subcircuit.marginal(variables), weight)
        return result

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return isinstance(other, self.__class__) and self.weighted_subcircuits == other.weighted_subcircuits

    def to_json(self):
        return {**super().to_json(), "weighted_subcircuits": [(weight, subcircuit.to_json()) for weight, subcircuit in
                                                              self.weighted_subcircuits]}

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

    def mount_with_interaction_terms(self, other: 'SumUnit', interaction_model: ProbabilisticModel):
        """
        Create a distribution that factorizes as follows:

        .. math::
            p(self.latent\_variable) \cdot p(self.variables | self.latent\_variable) \cdot
            p(other.latent\_variable | self.latent\_variable) \cdot p(other.variables | other.latent\_variable)

        where `self.latent_variable` and `other.latent_variable` are the results of the latent variable interpretation
        of mixture models.

        :param other: The other distribution to mount at this distribution children level.
        :param interaction_model: The interaction probabilities between both latent variables
        """
        assert set(self.variables).intersection(set(other.variables)) == set()
        assert set(interaction_model.variables) == {self.latent_variable, other.latent_variable}

        own_latent_variable = self.latent_variable
        other_latent_variable = other.latent_variable
        own_subcircuits = self.subcircuits
        other_subcircuits = other.subcircuits

        for own_index, own_subcircuit in zip(own_latent_variable.domain.simple_sets, own_subcircuits):

            # create denominator of weight
            condition = SimpleEvent({own_latent_variable: own_index}).as_composite_set()
            p_condition = interaction_model.probability(condition)

            # skip iterations that are impossible
            if p_condition == 0:
                continue

            # create proxy nodes for mounting
            proxy_product_node = ProductUnit()
            proxy_sum_node = other.empty_copy()
            self.probabilistic_circuit.add_nodes_from([proxy_product_node, proxy_sum_node])

            # remove edge to old child and replace it by product proxy
            self.probabilistic_circuit.remove_edge(self, own_subcircuit)
            self.add_subcircuit(proxy_product_node, p_condition)

            # mount current child on the product proxy
            proxy_product_node.add_subcircuit(own_subcircuit)

            # mount the proxy for the children from other in the product proxy
            proxy_product_node.add_subcircuit(proxy_sum_node)

            for other_index, other_subcircuit in zip(other_latent_variable.domain, other_subcircuits):

                # create numerator of weight
                query = SimpleEvent({other_latent_variable: other_index}).as_composite_set() & condition
                p_query = interaction_model.probability(query)

                # skip iterations that are impossible
                if p_query == 0:
                    continue

                # calculate conditional probability
                weight = p_query / p_condition

                # create edge from proxy to subcircuit
                proxy_sum_node.add_subcircuit(other_subcircuit, weight=weight)

    def mount_from_bayesian_network(self, other: 'SumUnit'):
        """
        Mount a distribution from tge `to_probabilistic_circuit` method in bayesian networks.
        The distribution is mounted as follows:


        :param other: The other distribution to mount at this distribution children level.
        :return:
        """
        assert set(self.variables).intersection(set(other.variables)) == set()
        assert len(self.subcircuits) == len(other.subcircuits)
        # mount the other subcircuit

        for (own_weight, own_subcircuit), other_subcircuit in zip(self.weighted_subcircuits, other.subcircuits):

            # create proxy nodes for mounting
            proxy_product_node = ProductUnit()
            self.probabilistic_circuit.add_node(proxy_product_node)

            # remove edge to old child and replace it by product proxy
            self.probabilistic_circuit.remove_edge(self, own_subcircuit)
            self.add_subcircuit(proxy_product_node, own_weight)
            proxy_product_node.add_subcircuit(own_subcircuit)
            proxy_product_node.add_subcircuit(other_subcircuit)

    @cache_inference_result
    def simplify(self) -> Self:

        # if this has only one child
        if len(self.subcircuits) == 1:
            return self.subcircuits[0].simplify()

        # create empty copy
        result = self.empty_copy()

        # for every subcircuit
        for weight, subcircuit in self.weighted_subcircuits:

            # if the weight is 0, skip this subcircuit
            if weight == 0:
                continue

            # simplify the subcircuit
            simplified_subcircuit = subcircuit.simplify()

            # if the simplified subcircuit is of the same type as this
            if type(simplified_subcircuit) is type(self):

                # type hinting
                simplified_subcircuit: Self

                # mount the children of that circuit directly
                for sub_weight, sub_subcircuit in simplified_subcircuit.weighted_subcircuits:
                    new_weight = sub_weight * weight
                    if new_weight > 0:
                        result.add_subcircuit(sub_subcircuit, new_weight)

            # if this cannot be simplified
            else:

                # mount the simplified subcircuit
                result.add_subcircuit(simplified_subcircuit, weight)

        return result

    def normalize(self):
        """
        Normalize the weights of the subcircuits such that they sum up to 1 inplace.
        """
        total_weight = sum([weight for weight, _ in self.weighted_subcircuits])
        for subcircuit in self.subcircuits:
            self.probabilistic_circuit.edges[self, subcircuit]["weight"] /= total_weight

    def is_deterministic(self) -> bool:
        # for every unique combination of subcircuits
        for subcircuit_a, subcircuit_b in itertools.combinations(self.subcircuits, 2):
            # check if they intersect
            if not subcircuit_a.support.intersection_with(subcircuit_b.support).is_empty():
                return False

        # if none intersect, the subcircuit is deterministic
        return True

    def log_mode(self) -> Tuple[Event, float]:

        if not self.is_deterministic():
            raise IntractableError("The mode of a non-deterministic sum unit cannot be calculated efficiently.")

        modes = []
        log_likelihoods = []

        # gather all modes from the children
        for weight, subcircuit in self.weighted_subcircuits:
            mode, log_likelihood = subcircuit.log_mode()
            modes.append(mode)
            log_likelihoods.append(np.log(weight) + log_likelihood)

        # get the most likely result
        maximum_log_likelihood = max(log_likelihoods)
        result = Event()

        # gather all results that are maximum likely
        for mode, likelihood in zip(modes, log_likelihoods):
            if likelihood == maximum_log_likelihood:
                result |= mode

        return result, maximum_log_likelihood

    def sub_circuit_index_of_samples(self, samples: np.array) -> np.array:
        """
        :return: the index of the subcircuit where p(sample) > 0 and None if p(sample) = 0 for all subcircuits.
        """
        result = np.full(len(samples), np.nan)
        for index, subcircuit in enumerate(self.subcircuits):
            likelihood = subcircuit.likelihood(samples)
            result[likelihood > 0] = index
        return result


class ProductUnit(ProbabilisticCircuitMixin):
    """
    Decomposable Product Units for Probabilistic Circuits
    """

    label = 'shape=stencil(tZXbboQgEIafhtsGIY3XjW3fg+psJcsCAbe7ffsiSFc8dduiMZqZYT5/BgcQrWzLNCCCW0SfESEFxu7p7MvEZlZD3QXngV+hCW7bGXWEC2+6AcBlC4Z3fZS+IPzkxvQ3rWolpSNwJW0SGcUdjHHpcvE1wIZvfyaWdvwTdGAGhcGLyOv92IfHfcDFTnpTbFSfXW8+cKq42GvhsoGLv2Np5TxrPzet3lh9fDfqLJt51mrsoAwsBL7DXIjQeBvTDANqJZRxjvD280CEYn9tl2nc2W47uHU42c7TrB84C8TwSX3Are4kXc9oLrMjQnA5QpQporwLkaoo/6+C/EaFX/yVOsXC56rw4ha6PTMQgmv7E2N6QEwPkKxT92mzrvDecIB5xxc=);whiteSpace=wrap;html=1;labelPosition=center;verticalLabelPosition=bottom;align=center;verticalAlign=top;'
    representation = "⊗"
    image = os.path.join(os.path.dirname(__file__),"../../../", "resources", "icons", 'DecomposableProductUnit.png')

    @property
    def variables(self) -> SortedSet:
        result = SortedSet()
        for subcircuit in self.subcircuits:
            result = result.union(subcircuit.variables)
        return result

    @cached_property
    def support(self) -> Event:
        support = self.subcircuits[0].support
        for subcircuit in self.subcircuits[1:]:
            support &= subcircuit.support
        return support

    def add_subcircuit(self, subcircuit: ProbabilisticCircuitMixin):
        """
        Add a subcircuit to the children of this unit.

        :param subcircuit: The subcircuit to add.
        """
        self.mount(subcircuit)
        self.probabilistic_circuit.add_edge(self, subcircuit)

    @cache_inference_result
    def log_likelihood(self, events: np.array) -> np.array:
        variables = self.variables
        result = np.zeros(len(events))
        for subcircuit in self.subcircuits:
            subcircuit_variables = subcircuit.variables
            variable_indices_in_events = np.array([variables.index(variable) for variable in subcircuit_variables])
            result += subcircuit.log_likelihood(events[:, variable_indices_in_events])
        return result

    @cache_inference_result
    def cdf(self, events: np.array) -> np.array:
        variables = self.variables
        result = np.zeros(len(events))
        for subcircuit in self.subcircuits:
            subcircuit_variables = subcircuit.variables
            variable_indices_in_events = np.array([variables.index(variable) for variable in subcircuit_variables])
            result += subcircuit.cdf(events[:, variable_indices_in_events])
        return result

    @cache_inference_result
    def probability_of_simple_event(self, event: SimpleEvent) -> float:
        result = 1.
        for subcircuit in self.subcircuits:
            result *= subcircuit.probability_of_simple_event(event)
            if result == 0:
                return 0.
        return result

    def is_deterministic(self) -> bool:
        return True

    def is_decomposable(self):
        for index, subcircuit in enumerate(self.subcircuits):
            variables = subcircuit.variables
            for subcircuit_ in self.subcircuits[index+1:]:
                if len(set(subcircuit_.variables).intersection(set(variables))) > 0:
                    return False
        return True

    @cache_inference_result
    def log_mode(self) -> Tuple[Event, float]:

        # initialize mode and log likelihood
        mode, log_likelihood = self.subcircuits[0].log_mode()

        # gather all modes from the children
        for subcircuit in self.subcircuits[1:]:
            subcircuit_mode, subcircuit_log_likelihood = subcircuit.log_mode()
            mode &= subcircuit_mode
            log_likelihood += subcircuit_log_likelihood

        return mode, log_likelihood

    # @cache_inference_result
    def log_conditional_of_simple_event(self, event: SimpleEvent) -> Tuple[Optional[Self], float]:
        # initialize probability
        log_probability = 0.

        # create a new node with new circuit attached to it
        resulting_node = self.empty_copy()

        for subcircuit in self.subcircuits:

            # get conditional child and probability in pre-order
            conditional_subcircuit, conditional_log_probability = subcircuit.log_conditional_of_simple_event(event)

            # if any is 0, the whole probability is 0
            if conditional_subcircuit is None:
                return None, -np.inf

            # update probability and children
            resulting_node.add_subcircuit(conditional_subcircuit)
            log_probability += conditional_log_probability

        return resulting_node, log_probability

    @cache_inference_result
    def sample(self, amount: int) -> np.array:

        # load on variables
        variables = self.variables

        # list for the samples content in the same order as self.variables
        rearranged_samples = np.full((amount, len(variables)), np.nan)

        # for every subcircuit
        for subcircuit in self.subcircuits:

            # calculate the indices of the variables
            variable_indices_in_events = np.array([variables.index(variable) for variable in subcircuit.variables])

            # sample from the subcircuit
            sample_subset = subcircuit.sample(amount)
            np.random.shuffle(sample_subset)
            rearranged_samples[:, variable_indices_in_events] = sample_subset

        return rearranged_samples

    @cache_inference_result
    def moment(self, order: OrderType, center: CenterType) -> MomentType:

        # initialize result
        result = VariableMap()

        for subcircuit in self.subcircuits:
            # calculate the moment of the child
            child_moment = subcircuit.moment(order, center)

            result = VariableMap({**result, **child_moment})

        return result

    @cache_inference_result
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

            result.add_subcircuit(marginal)

        return result

    def to_json(self) -> Dict[str, Any]:
        return {**super().to_json(), "subcircuits": [subcircuit.to_json() for subcircuit in self.subcircuits]}

    @classmethod
    def _from_json(cls, data: Dict[str, Any]) -> Self:
        result = cls()
        for subcircuit_data in data["subcircuits"]:
            subcircuit = ProbabilisticCircuitMixin.from_json(subcircuit_data)
            result.add_subcircuit(subcircuit)
        return result

    def __copy__(self):
        result = self.__class__()
        for subcircuit in self.subcircuits:
            copied_subcircuit = subcircuit.__copy__()
            result.add_subcircuit(copied_subcircuit)
        return result

    @cache_inference_result
    def simplify(self) -> Self:
        # if this has only one child
        if len(self.subcircuits) == 1:
            return self.subcircuits[0].simplify()

        # create empty copy
        result = self.empty_copy()

        # for every subcircuit
        for subcircuit in self.subcircuits:

            # simplify the subcircuit
            simplified_subcircuit = subcircuit.simplify()

            # if the simplified subcircuit is of the same type as this
            if type(simplified_subcircuit) is type(self):

                # type hinting
                simplified_subcircuit: Self

                # mount the children of that circuit directly
                for sub_subcircuit in simplified_subcircuit.subcircuits:
                    result.add_subcircuit(sub_subcircuit)

            # if this cannot be simplified
            else:
                # mount the simplified subcircuit
                result.add_subcircuit(simplified_subcircuit)

        return result


class ProbabilisticCircuit(ProbabilisticModel, nx.DiGraph, SubclassJSONSerializer):
    """
    Probabilistic Circuits as a directed, rooted, acyclic graph.
    """

    def __init__(self):
        super().__init__(None)
        nx.DiGraph.__init__(self)

    @property
    def variables(self) -> SortedSet:
        return self.root.variables

    @property
    def leaves(self) -> List[UnivariateDistribution]:
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

        # write self as the nodes' circuit
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
    def log_likelihood(self, events: np.array) -> np.array:
        return self.root.log_likelihood(events)

    @graph_inference_caching_wrapper
    def probability_of_simple_event(self, event: SimpleEvent) -> float:
        return self.root.probability_of_simple_event(event)

    @graph_inference_caching_wrapper
    def log_mode(self) -> Tuple[Event, float]:
        return self.root.log_mode()

    # @graph_inference_caching_wrapper
    def log_conditional(self, event: Event) -> Tuple[Optional[Self], float]:
        conditional, log_probability = self.root.log_conditional(event)
        if conditional is None:
            return conditional, log_probability
        return conditional.probabilistic_circuit, log_probability

    @graph_inference_caching_wrapper
    def marginal(self, variables: Iterable[Variable]) -> Optional[Self]:
        root = self.root
        result = self.root.marginal(variables)
        if result is None:
            return None
        root.reset_result_of_current_query()
        return result.probabilistic_circuit

    def sample(self, amount: int) -> np.array:
        return self.root.sample(amount)

    @graph_inference_caching_wrapper
    def moment(self, order: OrderType, center: CenterType) -> MomentType:
        return self.root.moment(order, center)

    @graph_inference_caching_wrapper
    def simplify(self) -> Self:
        return self.root.simplify().probabilistic_circuit

    @property
    def support(self) -> Event:
        return self.root.support

    def is_decomposable(self) -> bool:
        """
        Check if the whole circuit is decomposed.

        A circuit is decomposed if all its product units are decomposed.

        :return: if the whole circuit is decomposed
        """
        return all([subcircuit.is_decomposable() for subcircuit in self.leaves if
                    isinstance(subcircuit, ProductUnit)])

    def __eq__(self, other: 'ProbabilisticCircuit'):
        return self.root == other.root

    def to_json(self) -> Dict[str, Any]:

        # get super result
        result = super().to_json()

        hash_to_node_map = dict()

        for node in self.nodes:
            node_json = node.empty_copy().to_json()
            hash_to_node_map[hash(node)] = node_json

        unweighted_edges = [(hash(source), hash(target)) for source, target
                            in self.unweighted_edges]
        weighted_edges = [(hash(source), hash(target), weight)
                          for source, target, weight in self.weighted_edges]
        result["hash_to_node_map"] = hash_to_node_map
        result["unweighted_edges"] = unweighted_edges
        result["weighted_edges"] = weighted_edges
        return result

    @classmethod
    def _from_json(cls, data: Dict[str, Any]) -> Self:
        result = ProbabilisticCircuit()
        hash_remap: Dict[int, ProbabilisticCircuitMixin] = dict()

        for hash_, node_data in data["hash_to_node_map"].items():
            node = ProbabilisticCircuitMixin.from_json(node_data)
            hash_remap[int(hash_)] = node
            result.add_node(node)

        for source_hash, target_hash in data["unweighted_edges"]:
            result.add_edge(hash_remap[source_hash], hash_remap[target_hash])

        for source_hash, target_hash, weight in data["weighted_edges"]:
            result.add_edge(hash_remap[source_hash], hash_remap[target_hash], weight=weight)

        return result

    def update_variables(self, new_variables: VariableMap):
        """
        Update the variables of this unit and its descendants.

        :param new_variables: The new variables to set.
        """
        self.root.update_variables(new_variables)

    @property
    def weighted_edges(self):
        """
        :return: All weighted edges of the circuit.
        """

        # gather all weighted and non-weighted edges from the subgraph
        weighted_edges = []

        for edge in self.edges:
            edge_ = self.edges[edge]

            if "weight" in edge_.keys():
                weight = edge_["weight"]
                weighted_edges.append((*edge, weight))

        return weighted_edges

    @property
    def unweighted_edges(self):
        """
        :return: All unweighted edges of the circuit.
        """
        # gather all weighted and non-weighted edges from the subgraph
        unweighted_edges = []

        for edge in self.edges:
            edge_ = self.edges[edge]

            if "weight" not in edge_.keys():
                unweighted_edges.append(edge)

        return unweighted_edges


    def plot(self):
        return self.root.plot()

    def plotly_layout(self):
        return self.root.plotly_layout()

    def is_deterministic(self) -> bool:
        """
        :return: Whether, this circuit is deterministic or not.
        """
        return all(node.is_deterministic() for node in self.nodes if isinstance(node, SumUnit))

    def plot(self, **kwargs):
        return self.root.plot(**kwargs)

    def plotly_layout(self, **kwargs):
        return self.root.plotly_layout()


    def nodes_weights(self) -> dict:
        """
        """
        node_weights = {hash(self.root): [1]}
        seen_nodes = set()
        seen_nodes.add(hash(self.root))
        import queue
        to_visit_nodes = queue.Queue()

        to_visit_nodes.put(self.root)
        while not to_visit_nodes.empty():
            node = to_visit_nodes.get()
            succ_iter = self.successors(node)
            for succ in succ_iter:
                if self.has_edge(node, succ):
                    weight = self.get_edge_data(node, succ).get("weight", 1)
                    node_weights[hash(succ)] = [old * weight for old in node_weights[hash(node)]] + node_weights.get(
                        hash(succ), [])
                    if hash(succ) not in seen_nodes:
                        seen_nodes.add(hash(succ))
                        to_visit_nodes.put(succ)
        return node_weights

    def replace_discrete_distribution_with_deterministic_sum(self):
        from probabilistic_model.probabilistic_circuit.nx.distributions import DiscreteDistribution
        old_leafs = self.leaves
        for leaf in old_leafs:
            if isinstance(leaf, DiscreteDistribution):
                leaf: DiscreteDistribution
                sum_leaf = leaf.as_deterministic_sum()
                old_predecessors = list(self.predecessors(leaf))
                for predecessor in old_predecessors:
                    weight = self.get_edge_data(predecessor, leaf).get("weight", -1)
                    if weight == -1:
                        predecessor.add_subcircuit(sum_leaf)
                    else:
                        predecessor.add_subcircuit(sum_leaf, weight=weight)
                    self.remove_edge(predecessor, leaf)
                self.remove_node(leaf)



#from probabilistic_model.probabilistic_circuit.exporter import draw_io_expoter
#from probabilistic_model.probabilistic_circuit.exporter.draw_io_expoter import DrawIoExporter
class ShallowProbabilisticCircuit(ProbabilisticCircuit):
    @classmethod
    def from_probabilistic_circuit(cls, probabilistic_circuit: ProbabilisticCircuit):

        # diagram = DrawIoExporter(probabilistic_circuit).export()
        # diagram.dump_file("test.drawio")
        result = cls()
        shallow_pc = probabilistic_circuit
        cls.shallowing(result, node=shallow_pc.root, presucc=None)
        result.add_nodes_from(shallow_pc.nodes)
        result.add_edges_from(shallow_pc.edges)
        result.add_weighted_edges_from(shallow_pc.weighted_edges)

        return result

    def shallowing(self, node: ProbabilisticCircuitMixin, presucc: ProbabilisticCircuitMixin | None):
        probabilistic_circuit = node.probabilistic_circuit
        succ_list: List = list(probabilistic_circuit.successors(node))
        if not isinstance(node, SumUnit) and not isinstance(node, ProductUnit):
            sum_unit = SumUnit()
            product_unit = ProductUnit()
            probabilistic_circuit.add_node(sum_unit)
            probabilistic_circuit.add_node(product_unit)
            probabilistic_circuit.add_edge(product_unit, node)
            probabilistic_circuit.add_edge(sum_unit, product_unit, weight=1)
            if presucc is not None:
                data = probabilistic_circuit.get_edge_data(presucc, node, {"weight": 1})
                probabilistic_circuit.add_edge(presucc, sum_unit, **data)
                probabilistic_circuit.remove_edge(presucc, node)
            return
        elif isinstance(node, SumUnit) or isinstance(node, SumUnit):
            for succ in succ_list:
                self.shallowing(succ, presucc=node)
            new_succ_list = list(probabilistic_circuit.successors(node))
            for sum_succ in new_succ_list:
                first_weight = probabilistic_circuit.get_edge_data(node, sum_succ, {"weight": 1}).get("weight", 1)
                for succ_succ in list(probabilistic_circuit.successors(sum_succ)):
                    second_weight = probabilistic_circuit.get_edge_data(sum_succ, succ_succ, {"weight": 1}).get("weight", 1)
                    probabilistic_circuit.add_edge(node, succ_succ, weight=first_weight * second_weight)
                probabilistic_circuit.remove_edge(node, sum_succ)
                if len(list(probabilistic_circuit.predecessors(sum_succ))) == 0:
                    self.remove_node_and_successor_structure(sum_succ)
            return

        elif isinstance(node, ProductUnit):
            for succ in succ_list:
                self.shallowing(succ, presucc=node)
            new_succ_list = list(probabilistic_circuit.successors(node))
            combination_li = list()
            sum_unit = SumUnit()
            probabilistic_circuit.add_node(sum_unit)
            if presucc is not None:
                data = probabilistic_circuit.get_edge_data(presucc, node, {"weight": 1})
                probabilistic_circuit.add_edge(presucc, sum_unit, **data)
                probabilistic_circuit.remove_edge(presucc, node)
                if len(list(probabilistic_circuit.predecessors(node))) == 0:
                    probabilistic_circuit.remove_node(node)
            for sum_succ in new_succ_list:
                pro_li = []
                for pro_succ in list(probabilistic_circuit.successors(sum_succ)):
                    data = probabilistic_circuit.get_edge_data(sum_succ, pro_succ, {"weight": 1})
                    pro_li.append((pro_succ, data.get("weight", 1)))
                combination_li.append(pro_li)
            for combination in itertools.product(*combination_li):
                product_unit = ProductUnit()
                probabilistic_circuit.add_node(product_unit)
                total_weight = 1
                for pro_tuple in combination:
                    under_node, weight = pro_tuple[0], pro_tuple[1]
                    total_weight *= weight
                    under_succ_li = probabilistic_circuit.successors(under_node)
                    for under_succ in under_succ_li:
                        data = probabilistic_circuit.get_edge_data(under_node, under_succ, {"weight": 1})
                        probabilistic_circuit.add_edge(product_unit, under_succ, **data)
                probabilistic_circuit.add_edge(sum_unit, product_unit, weight=total_weight)
            for sum_succ in new_succ_list:
                if len(list(probabilistic_circuit.predecessors(sum_succ))) == 0:
                    self.remove_node_and_successor_structure(sum_succ)
            return

        else:
            raise TypeError(f"{type(node)} is not supported")

    def events_of_higher_density_product_swag(self, other: Self, own_pro_unit, other_pro_unit, tolerance: float = 10e-8):
        """
        Construct E_p of a product unit in a shallow context.
        """
        supp_own = own_pro_unit.support
        supp_other = other_pro_unit.support
        intersection: Event = (supp_own & supp_other)
        if intersection.is_empty():
            return Event()

        center = np.array([assignment.simple_sets[0].center() if isinstance(assignment, Interval)
                                 else assignment.simple_sets[0] for variable, assignment in intersection.simple_sets[0].items()]).reshape(1, -1)
        likelihood_own = self.likelihood(center)
        likelihood_other = other.likelihood(center)
        diff = likelihood_own - likelihood_other

        if diff > tolerance:
            return intersection
        else:
            return Event()

    def events_of_higher_density_sum_swag(self, other: Self, tolerance: float = 10e-8):

        progress_bar = tqdm.tqdm(total=len(self.root.subcircuits) * len(other.root.subcircuits))
        result = self.support - other.support
        for own_prod, other_prod in itertools.product(self.root.subcircuits, other.root.subcircuits):
            result |= self.events_of_higher_density_product_swag(other, own_prod, other_prod, tolerance)
            progress_bar.update()
        return result


    def events_of_higher_density_product(self, other: Self, own_pro_unit, other_pro_unit, own_node_weights, other_node_weights,
                                         progress_bar: tqdm.tqdm):
        own_result = Event()
        other_result = Event()
        combination_map = {}

        for own_univariate_unit in own_pro_unit.subcircuits:
            other_univariate_unit = [s for s in other_pro_unit.subcircuits if s.variables == own_univariate_unit.variables][0]
            variable = own_univariate_unit.variables[0]
            if isinstance(variable, random_events.variable.Continuous):
                all_mixture_points = own_univariate_unit.all_union_of_mixture_points_with(other_univariate_unit)
                #print(all_mixture_points)
                # go.Figure(own_univariate_unit.plot()).show()
                # go.Figure(other_univariate_unit.plot()).show()
                combination_map[variable] = all_mixture_points
            elif isinstance(variable, random_events.variable.Symbolic):
                support = own_univariate_unit.support | other_univariate_unit.support
                combination_map[variable] = support
            elif isinstance(variable, random_events.variable.Integer):
                points = [i.lower for i in own_univariate_unit.support.simple_sets[0][variable] | other_univariate_unit.support.simple_sets[0][variable]]
                combination_map[variable] = points
            else:
                raise NotImplementedError("Unknown Node Type")
            progress_bar.update()

        own_weight = sum(own_node_weights.get(hash(own_pro_unit)))
        other_weight = sum(other_node_weights.get(hash(other_pro_unit)))
        #for combination in itertools.product(*combination_map.values()):
        for combination in itertools.product(*[v for _, v in sorted(combination_map.items())]):
            full_evidence_state = list()
            # full_evidence_state = list(
            #     ((element.simple_sets[-1].upper - element.simple_sets[0].lower) / 2) + element.simple_sets[
            #         0].lower if isinstance(element, random_events.interval.Interval) else element
            #     for element in combination)
            for element in combination:
                if isinstance(element, random_events.interval.Interval):
                    full_evidence_state.append(((element.simple_sets[-1].upper - element.simple_sets[0].lower) / 2) + element.simple_sets[0].lower)
                elif isinstance(element, random_events.variable.Symbolic):
                    full_evidence_state.append(element)
                elif isinstance(element, int):
                    full_evidence_state.append(element)
                else:
                    raise ValueError(f"Unknown Node Type {type(element)}")

            likelihood_in_self = np.round(self.likelihood(np.array([full_evidence_state])),5)
            # likelihood_in_self = np.round(self.likelihood(np.array([full_evidence_state])) * own_weight, 4)
            likelihood_in_other = np.round(other.likelihood(np.array([full_evidence_state])),5)
            # likelihood_in_other = np.round(other.likelihood(np.array([full_evidence_state])) * other_weight, 4)

            event_dic = {}
            for variable, value in zip(self.variables, combination):
                value = random_events.interval.singleton(value) if isinstance(value, int) else value
                event_dic.update({variable: value})
            #print(event_dic)
            if likelihood_in_self > likelihood_in_other:
                # if not own_result:
                #     own_result = Event({variable: value for variable, value in zip(self.variables, combination)})
                # else:
                #
                #     own_result = own_result.union_with(SimpleEvent({variable: value for variable, value in
                #                                                     zip(self.variables,
                #                                                         combination)}).as_composite_set())
                own_result |= SimpleEvent(event_dic).as_composite_set()
            elif likelihood_in_other > likelihood_in_self:
                # if not other_result:
                #     other_result = Event({variable: value for variable, value in zip(other.variables, combination)})
                # else:
                #     other_result = other_result.union_with(SimpleEvent({variable: value for variable, value in
                #                                                         zip(other.variables,
                #                                                             combination)}).as_composite_set())
                other_result |= SimpleEvent(event_dic).as_composite_set()
        return own_result, other_result

    def events_of_higher_density_sum(self, other: Self,):
        progress_bar = tqdm.tqdm(total=len(self.root.subcircuits) * len(other.root.subcircuits) * len(self.variables))

        own_node_weights = self.root.probabilistic_circuit.nodes_weights()
        other_node_weights = other.root.probabilistic_circuit.nodes_weights()
        own_result = Event()
        other_result = Event()
        for own_pro_unit in self.root.subcircuits:
            own_pro_unit: ProductUnit
            for other_pro_unit in other.root.subcircuits:
                other_pro_unit: ProductUnit
                own_result_part, other_result_part = self.events_of_higher_density_product(other ,own_pro_unit, other_pro_unit,
                                                                                           own_node_weights,
                                                                                        other_node_weights, progress_bar)
                own_result |= own_result_part
                other_result |= other_result_part
                # if own_result.is_empty():
                #     own_result = own_result_part
                # elif not other_result_part.is_empty():
                #     own_result = own_result.union_with(own_result_part)
                # if other_result.is_empty():
                #     other_result = other_result_part
                # elif not other_result_part.is_empty():
                #     other_result = other_result.union_with(other_result_part)
        return own_result, other_result

    def events_of_higher_density_cool(self, other: Self):
        points_dict = {}
        own_result = Event()
        other_result = Event()
        for own_pro_unit in self.root.subcircuits:
            own_pro_unit: ProductUnit
            for other_pro_unit in other.root.subcircuits:
                other_pro_unit: ProductUnit
                for own_univariate_unit in own_pro_unit.subcircuits:
                    other_univariate_unit = [s for s in other_pro_unit.subcircuits if s.variables == own_univariate_unit.variables][0]
                    variable = own_univariate_unit.variables[0]
                    if isinstance(variable, random_events.variable.Continuous):
                        all_mixture_points = own_univariate_unit.all_union_of_mixture_points_with(other_univariate_unit)
                        var_value = points_dict.get(variable, [])
                        var_value.extend(all_mixture_points)
                        points_dict[variable] = var_value
                    elif isinstance(variable, random_events.variable.Symbolic):
                        support = own_univariate_unit.support | other_univariate_unit.support
                        var_value = points_dict.get(variable, [])
                        var_value.extend(support)
                        points_dict[variable] = var_value
                    elif isinstance(variable, random_events.variable.Integer):
                        points = [i.lower for i in own_univariate_unit.support.simple_sets[0][variable] |
                                  other_univariate_unit.support.simple_sets[0][variable]]
                        var_value = points_dict.get(variable, [])
                        var_value.extend(points)
                        points_dict[variable] = var_value
                    else:
                        raise NotImplementedError("Unknown Node Type")
        for variable, value in points_dict.items():
            points_dict[variable] = list(set(value))
        for combination in itertools.product(*[v for _, v in sorted(points_dict.items())]):
            full_evidence_state = list()
            for element in combination:
                if isinstance(element, random_events.interval.Interval):
                    full_evidence_state.append(((element.simple_sets[-1].upper - element.simple_sets[0].lower) / 2) + element.simple_sets[0].lower)
                elif isinstance(element, random_events.variable.Symbolic):
                    full_evidence_state.append(element)
                elif isinstance(element, int):
                    full_evidence_state.append(element)
                else:
                    raise ValueError(f"Unknown Node Type {type(element)}")

            likelihood_in_self = np.round(self.likelihood(np.array([full_evidence_state])), 4)
            # likelihood_in_self = np.round(self.likelihood(np.array([full_evidence_state])) * own_weight, 4)
            likelihood_in_other = np.round(other.likelihood(np.array([full_evidence_state])), 4)
            # likelihood_in_other = np.round(other.likelihood(np.array([full_evidence_state])) * other_weight, 4)
            event_dic = {}
            for variable, value in zip(self.variables, combination):
                value = random_events.interval.singleton(value) if isinstance(value, int) else value
                event_dic.update({variable: value})
            if likelihood_in_self > likelihood_in_other:
                own_result |= SimpleEvent(event_dic).as_composite_set()
            elif likelihood_in_other > likelihood_in_self:
                other_result |= SimpleEvent(event_dic).as_composite_set()
        return own_result, other_result

    def l1_cool(self, other: Self)-> float:
        p_event, q_event = self.events_of_higher_density_cool(other)
        # p_event, q_event = self.event_of_higher_density_cool(other)
        print("l1",p_event, q_event)
        go.Figure(p_event.plot()).show()
        go.Figure(q_event.plot()).show()
        result = (self.probability(p_event) - other.probability(p_event)
                  + other.probability(q_event) - self.probability(q_event))

        return result

    def l1_swag(self, other: Self, tolerance: float = 10e-8)-> float:
        e = self.events_of_higher_density_sum_swag(other, tolerance)
        #go.Figure(e.plot()).show()
        p_e = self.probability(e)
        q_e = other.probability(e)
        
        return 2*(p_e - q_e)

    def area_validation_metric(self, other: Self) -> float:

        p_event, q_event = self.events_of_higher_density_sum(other)
        # p_event, q_event = self.event_of_higher_density_cool(other)
        print("avm",p_event, q_event)
        go.Figure(p_event.plot()).show()
        go.Figure(q_event.plot()).show()
        result = (self.probability(p_event) - other.probability(p_event)
                  + other.probability(q_event) - self.probability(q_event))

        return result

    def remove_node_and_successor_structure(self, node: ProbabilisticCircuitMixin):
        probabilistic_circuit = node.probabilistic_circuit
        succ_list: List = list(probabilistic_circuit.successors(node))
        probabilistic_circuit.remove_node(node)
        for succ in succ_list:
            if len(list(probabilistic_circuit.predecessors(succ))) == 0:
                self.remove_node_and_successor_structure(succ)
