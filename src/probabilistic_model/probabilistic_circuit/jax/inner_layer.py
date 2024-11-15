from __future__ import annotations

import inspect
import math
from abc import abstractmethod, ABC
from collections import defaultdict
from dataclasses import dataclass
from functools import cached_property

import jax
from jax.typing import ArrayLike
from jaxtyping import Array, Float, Int
from jax import numpy as jnp, tree_flatten
import equinox as eqx
from jax.experimental.sparse import BCOO, bcoo_concatenate, bcoo_reduce_sum, bcoo_multiply_dense
from random_events.utils import recursive_subclasses
from sortedcontainers import SortedSet
from typing_extensions import List, Iterator, Tuple, Union, Type, Dict, Any

from . import create_sparse_array_indices_from_row_lengths
from .utils import copy_bcoo
from ..nx.probabilistic_circuit import SumUnit, ProductUnit, ProbabilisticCircuitMixin
import tqdm


def inverse_class_of(clazz: Type[ProbabilisticCircuitMixin]) -> Type[Layer]:
    for subclass in recursive_subclasses(Layer):
        if not inspect.isabstract(subclass):
            if issubclass(clazz, subclass.nx_classes()):
                return subclass

    raise TypeError(f"Could not find class for {clazz}")


class Layer(eqx.Module, ABC):
    """
    Abstract class for Layers of a layered circuit.

    Layers have the same scope (set of variables) for every node in them.
    """

    @abstractmethod
    def log_likelihood_of_nodes_single(self, x: jnp.array) -> jnp.array:
        """
        Calculate the log-likelihood of the distribution.

        .. Note::
            The shape of the log likelihood depends on the number of samples and nodes.
            The shape of the result is (#samples, #nodes).
        """
        raise NotImplementedError

    def log_likelihood_of_nodes(self, x: jnp.array) -> jnp.array:
        return jax.vmap(self.log_likelihood_of_nodes_single)(x)

    def validate(self):
        """
        Validate the parameters and their layouts.
        """
        raise NotImplementedError

    @property
    def number_of_nodes(self) -> int:
        """
        :return: The number of nodes in the layer.
        """
        raise NotImplementedError

    def all_layers(self) -> List[Layer]:
        """
        :return: A list of all layers in the circuit.
        """
        return [self]

    def all_layers_with_depth(self, depth: int = 0) -> List[Tuple[int, Layer]]:
        """
        :return: A list of tuples of all layers in the circuit with their depth.
        """
        return [(depth, self)]

    @property
    @abstractmethod
    def variables(self) -> jax.Array:
        """
        :return: The variable indices of this layer.
        """
        raise NotImplementedError

    def __deepcopy__(self) -> 'Layer':
        """
        Create a deep copy of the layer.
        """
        raise NotImplementedError

    @classmethod
    def nx_classes(cls) -> Tuple[Type, ...]:
        """
        :return: The tuple of matching classes of the layer in the probabilistic_model.probabilistic_circuit.nx package.
        """
        return tuple()

    @staticmethod
    def create_layers_from_nodes(nodes: List[ProbabilisticCircuitMixin], child_layers: List[NXConverterLayer],
                                 progress_bar: bool = True) \
            -> List[NXConverterLayer]:
        """
        Create a layer from a list of nodes.
        """
        result = []

        unique_types = set(type(node) for node in nodes)
        for unique_type in unique_types:
            nodes_of_current_type = [node for node in nodes if isinstance(node, unique_type)]
            layer_type = inverse_class_of(unique_type)
            scopes = [tuple(node.variables) for node in nodes_of_current_type]
            unique_scopes = set(scopes)
            for scope in unique_scopes:
                nodes_of_current_type_and_scope = [node for node in nodes_of_current_type if
                                                   tuple(node.variables) == scope]
                layer = layer_type.create_layer_from_nodes_with_same_type_and_scope(nodes_of_current_type_and_scope,
                                                                                    child_layers, progress_bar)
                result.append(layer)

        return result

    @classmethod
    @abstractmethod
    def create_layer_from_nodes_with_same_type_and_scope(cls, nodes: List[ProbabilisticCircuitMixin],
                                                         child_layers: List[NXConverterLayer],
                                                         progress_bar: bool = True) -> \
            NXConverterLayer:
        """
        Create a layer from a list of nodes with the same type and scope.
        """
        raise NotImplementedError

    def partition(self) -> Tuple[Any, Any]:
        """
        Partition the layer into the parameters and the static structure.
        :return: A tuple containing the parameters and the static structure as pytrees.
        """
        return eqx.partition(self, eqx.is_inexact_array)

    @property
    def number_of_trainable_parameters(self):
        """
        :return: The trainable parameters of the layer and all child layers.
        """
        parameters, _ = self.partition()
        flattened_parameters, _ = tree_flatten(parameters)
        number_of_parameters = sum([len(p) for p in flattened_parameters])
        return number_of_parameters

    def sample_from_frequencies(self, frequencies: jax.Array, key: jax.random.PRNGKey) -> BCOO:
        raise NotImplementedError

class InnerLayer(Layer, ABC):
    """
    Abstract Base Class for inner layers
    """

    child_layers: List[Layer]
    """
    The child layers of this layer.
    """

    def __init__(self, child_layers: List[Layer]):
        super().__init__()
        self.child_layers = child_layers

    @property
    @abstractmethod
    def variables(self) -> jax.Array:
        raise NotImplementedError

    def all_layers(self) -> List[Layer]:
        """
        :return: A list of all layers in the circuit.
        """
        result = [self]
        for child_layer in self.child_layers:
            result.extend(child_layer.all_layers())
        return result

    def all_layers_with_depth(self, depth: int = 0) -> List[Tuple[int, Layer]]:
        """
        :return: A list of tuples of all layers in the circuit with their depth.
        """
        result = [(depth, self)]
        for child_layer in self.child_layers:
            result.extend(child_layer.all_layers_with_depth(depth + 1))
        return result


class InputLayer(Layer, ABC):
    """
    Abstract base class for univariate input units.

    Input layers contain only one type of distribution such that the vectorization of the log likelihood
    calculation works without bottleneck statements like if/else or loops.
    """

    _variables: jnp.array = eqx.field(static=True)
    """
    The variable indices of the layer.
    """

    def __init__(self, variable: int):
        super().__init__()
        self._variables = jnp.array([variable])

    @property
    def variables(self) -> jax.Array:
        return self._variables


class SumLayer(InnerLayer):

    log_weights: List[BCOO]
    child_layers: Union[List[[ProductLayer]], List[InputLayer]]

    def __init__(self, child_layers: List[Layer], log_weights: List[BCOO]):
        super().__init__(child_layers)
        self.log_weights = log_weights

    def validate(self):
        for log_weights in self.log_weights:
            assert log_weights.shape[0] == self.number_of_nodes, "The number of nodes must match the number of weights."

        for log_weights, child_layer in self.log_weighted_child_layers:
            assert log_weights.shape[
                       1] == child_layer.number_of_nodes, "The number of nodes must match the number of weights."

    @cached_property
    def variables(self) -> jax.Array:
        return self.child_layers[0].variables

    @classmethod
    def nx_classes(cls) -> Tuple[Type, ...]:
        return SumUnit,

    @property
    def log_weighted_child_layers(self) -> Iterator[Tuple[BCOO, Layer]]:
        """
        :returns: Yields log weights and the child layers zipped together.
        """
        yield from zip(self.log_weights, self.child_layers)

    @property
    def number_of_nodes(self) -> int:
        return self.log_weights[0].shape[0]

    @property
    def concatenated_log_weights(self) -> BCOO:
        """
        :return: The concatenated weights of the child layers for each node.
        """
        return bcoo_concatenate(self.log_weights, dimension=1)

    @property
    def log_normalization_constants(self) -> jax.Array:
        result = self.concatenated_log_weights
        result.data = jnp.exp(result.data)
        result = result.sum(1).todense()
        return jnp.log(result)

    @property
    def normalized_weights(self):
        """
        :return: The normalized weights of the child layers for each node.
        """
        result = self.concatenated_log_weights
        z = self.log_normalization_constants
        result.data = jnp.exp(result.data - z[result.indices[:, 0]])
        return result

    def log_likelihood_of_nodes_single(self, x: jax.Array) -> jax.Array:
        result = jnp.zeros(self.number_of_nodes)

        for log_weights, child_layer in self.log_weighted_child_layers:
            # get the log likelihoods of the child nodes
            child_layer_log_likelihood = child_layer.log_likelihood_of_nodes_single(x)

            # weight the log likelihood of the child nodes by the weight for each node of this layer
            cloned_log_weights = copy_bcoo(log_weights)  # clone the weights

            # multiply the weights with the child layer likelihood
            cloned_log_weights.data += child_layer_log_likelihood[cloned_log_weights.indices[:, 1]]
            cloned_log_weights.data = jnp.exp(cloned_log_weights.data)  # exponent weights

            # sum the weights for each node
            ll = cloned_log_weights.sum(1).todense()

            # sum the child layer result
            result += ll

        return jnp.where(result > 0, jnp.log(result) - self.log_normalization_constants, -jnp.inf)

    def __deepcopy__(self):
        child_layers = [child_layer.__deepcopy__() for child_layer in self.child_layers]
        log_weights = [copy_bcoo(log_weight) for log_weight in self.log_weights]
        return self.__class__(child_layers, log_weights)

    @classmethod
    def create_layer_from_nodes_with_same_type_and_scope(cls, nodes: List[SumUnit],
                                                         child_layers: List[NXConverterLayer],
                                                         progress_bar: bool = True) -> \
            NXConverterLayer:

        result_hash_remap = {hash(node): index for index, node in enumerate(nodes)}
        variables = jnp.array([nodes[0].probabilistic_circuit.variables.index(variable) for variable in nodes[0].variables])

        number_of_nodes = len(nodes)

        # filter the child layers to only contain layers with the same scope as this one
        filtered_child_layers = [child_layer for child_layer in child_layers if (child_layer.layer.variables ==
                                 variables).all()]
        log_weights = []

        # for every possible child layer
        for child_layer in filtered_child_layers:

            # initialize indices and values for sparse weight matrix
            indices = []
            values = []

            # gather indices and log weights
            for index, node in enumerate(tqdm.tqdm(nodes, desc="Calculating weights for sum node")
                                         if progress_bar else nodes):
                for weight, subcircuit in node.weighted_subcircuits:
                    if hash(subcircuit) in child_layer.hash_remap:
                        indices.append((index, child_layer.hash_remap[hash(subcircuit)]))
                        values.append((math.log(weight)))

            # assemble sparse log weight matrix
            log_weights.append(BCOO((jnp.array(values), jnp.array(indices)),
                                    shape=(number_of_nodes,
                                           child_layer.layer.number_of_nodes)))

        sum_layer = cls([cl.layer for cl in filtered_child_layers], log_weights)
        return NXConverterLayer(sum_layer, nodes, result_hash_remap)


class ProductLayer(InnerLayer):
    """
    A layer that represents the product of multiple other units.
    """

    child_layers: List[Union[SumLayer, InputLayer]]
    """
    The child of a product layer is a list that contains groups sum units with the same scope or groups of input
    units with the same scope.
    """

    edges: Int[BCOO, "len(child_layers), number_of_nodes"] = eqx.field(static=True)
    """
    The edges consist of a sparse matrix containing integers.
    The first dimension describes the edges for each child layer.
    The second dimension describes the edges for each node in the child layer.
    The integers are interpreted in such a way that n-th value represents a edge (n, edges[n]).

    Nodes in the child layer can be mapped to by multiple nodes in this layer.

    The shape is (#child_layers, #nodes).
    """

    def __init__(self, child_layers: List[Layer], edges: BCOO):
        """
        Initialize the product layer.

        :param child_layers: The child layers of the product layer.
        :param edges: The edges of the product layer.
        """
        super().__init__(child_layers)
        self.edges = edges

    def validate(self):
        assert self.edges.shape == (len(self.child_layers), self.number_of_nodes), \
            (f"The shape of the edges must be {(len(self.child_layers), self.number_of_nodes)} "
             f"but was {self.edges.shape}.")

    @property
    def number_of_nodes(self) -> int:
        return self.edges.shape[1]

    @classmethod
    def nx_classes(cls) -> Tuple[Type, ...]:
        return ProductUnit,

    @cached_property
    def variables(self) -> jax.Array:
        return jnp.unique(jnp.concatenate([layer.variables for layer in self.child_layers])).sort()

    def log_likelihood_of_nodes_single(self, x: jax.Array) -> jax.Array:
        result = jnp.zeros(self.number_of_nodes)

        for edges, layer in zip(self.edges, self.child_layers):
            # calculate the log likelihood over the columns of the child layer
            ll = layer.log_likelihood_of_nodes_single(x[layer.variables])  # shape: #child_nodes

            # gather the ll at the indices of the nodes that are required for the edges
            ll = ll[edges.data]  # shape: #len(edges.values())

            # add the gathered values to the result where the edges define the indices
            result = result.at[edges.indices[:, 0]].add(ll)

        return result

    def sample_from_frequencies(self, frequencies: jax.Array, key: jax.random.PRNGKey) -> BCOO:
        raise NotImplementedError
        max_frequency = jnp.max(frequencies)

        # create a list of empty tensors for the samples of each variable
        samples = []

        for index, (edges, child_layer) in enumerate(zip(self.edges, self.child_layers)):
            squeezed_edge_indices = edges.indices[:, 0]
            # count the number of samples for each child node
            frequencies_for_child_layer = jnp.zeros((child_layer.number_of_nodes,), dtype=jnp.int32)  # shape (#child_nodes)
            frequencies_for_child_layer = (frequencies_for_child_layer.at[edges.data].add(
                frequencies[squeezed_edge_indices]))

            if jnp.all(frequencies_for_child_layer == 0):
                continue

            # the creation of the frequencies for the child layer is wrong
            print("frequencies_for_child_layer", frequencies_for_child_layer)
            # sample the child layer shape (#child_nodes, #max_frequency_of_child_layer, #variables_of_child_layer)
            samples_from_child_layer = child_layer.sample_from_frequencies(frequencies_for_child_layer, key)

            # calculate the requested number of samples for each node in this layer
            frequencies_of_this_layer = jnp.zeros((self.number_of_nodes,), dtype=jnp.int32)
            frequencies_of_this_layer = frequencies_of_this_layer.at[squeezed_edge_indices].add(frequencies)

            # assemble a sparse matrix that resembles the current sample block
            indices = create_sparse_array_indices_from_row_lengths(frequencies_of_this_layer)
            print(frequencies_of_this_layer)
            print(indices)
            print(samples_from_child_layer.data.shape)
            samples_of_node_block = BCOO((samples_from_child_layer.data, indices),
                                         shape=(self.number_of_nodes, max_frequency,
                                                len(child_layer.variables)))
            samples.append(samples_of_node_block)

        # assemble the result
        result_indices = create_sparse_array_indices_from_row_lengths(frequencies)
        print([s.shape for s in samples])
        result_values = jnp.concatenate(samples, axis=-1)
        result = BCOO((result_values, result_indices), shape=(self.number_of_nodes, max_frequency,
                                                              len(self.variables)), indices_sorted=True,
                      unique_indices=True)
        return result


    def log_likelihood_of_nodes(self, x: jax.Array) -> jax.Array:
        return jax.vmap(self.log_likelihood_of_nodes_single)(x)

    def __deepcopy__(self):
        child_layers = [child_layer.__deepcopy__() for child_layer in self.child_layers]
        edges = copy_bcoo(self.edges)
        return self.__class__(child_layers, edges)

    @classmethod
    def create_layer_from_nodes_with_same_type_and_scope(cls, nodes: List[ProbabilisticCircuitMixin],
                                                         child_layers: List[NXConverterLayer],
                                                         progress_bar: bool = True) -> \
            NXConverterLayer:

        hash_remap = {hash(node): index for index, node in enumerate(nodes)}
        number_of_nodes = len(nodes)

        edge_indices = []
        edge_values = []

        progress_bar = tqdm.tqdm(total=number_of_nodes, desc="Assembling Product Layer")
        # for every node in the nodes for this layer
        for node_index, node in enumerate(nodes):

            # for every child layer
            for child_layer_index, child_layer in enumerate(child_layers):
                cl_variables = SortedSet([node.probabilistic_circuit.variables[index] for index in child_layer.layer.variables])

                # for every subcircuit
                for subcircuit_index, subcircuit in enumerate(node.subcircuits):
                    # if the scopes are compatible
                    if cl_variables == subcircuit.variables:
                        # add the edge
                        edge_indices.append([child_layer_index, node_index])
                        edge_values.append(child_layer.hash_remap[hash(subcircuit)])
            if progress_bar:
                progress_bar.update(1)

        # assemble sparse edge tensor
        edges = (BCOO((jnp.array(edge_values), jnp.array(edge_indices)), shape=(len(child_layers), number_of_nodes)).
                 sort_indices().sum_duplicates(remove_zeros=False))
        layer = cls([cl.layer for cl in child_layers], edges)
        return NXConverterLayer(layer, nodes, hash_remap)


@dataclass
class NXConverterLayer:
    """
    Class used for conversion from a probabilistic circuit in networkx to a layered circuit in jax.
    """
    layer: Layer
    nodes: List[ProbabilisticCircuitMixin]
    hash_remap: Dict[int, int]
