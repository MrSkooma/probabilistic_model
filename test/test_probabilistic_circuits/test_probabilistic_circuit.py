import unittest

from igraph.drawing.plotly.vertex import plotly
from random_events.interval import closed, open, closed_open
from random_events.variable import Integer, Continuous
from sympy.diffgeom import metric_to_Christoffel_2nd
from typing_extensions import Union
from probabilistic_model.distributions.multinomial import MultinomialDistribution
from probabilistic_model.probabilistic_circuit.nx.convolution.convolution import (UniformDistributionConvolution,
                                                                                  GaussianDistributionConvolution,
                                                                                  TruncatedGaussianDistributionConvolution,
                                                                                  DiracDeltaDistributionConvolution)
from probabilistic_model.probabilistic_circuit.nx.distributions import (ContinuousDistribution,
                                                                        UniformDistribution,
                                                                        GaussianDistribution,
                                                                        DiracDeltaDistribution,
                                                                        TruncatedGaussianDistribution)
from probabilistic_model.probabilistic_circuit.nx.probabilistic_circuit import *

import plotly.graph_objects as go
from probabilistic_model import Monte_Carlo_Estimator



class ShowMixin:
    model: Union[ProbabilisticCircuit, ProbabilisticCircuitMixin]

    def show(self, model: Optional[Union[ProbabilisticCircuit, ProbabilisticCircuitMixin]] = None):

        if model is None:
            model = self.model

        if isinstance(model, ProbabilisticCircuitMixin):
            model = model.probabilistic_circuit

        pos = nx.planar_layout(model)
        nx.draw(model, pos=pos, with_labels=True)
        plt.show()


class ProductUnitTestCase(unittest.TestCase, ShowMixin):
    x: Continuous = Continuous("x")
    y: Continuous = Continuous("y")
    model: ProductUnit

    def setUp(self):
        u1 = UniformDistribution(self.x, closed(0, 1).simple_sets[0])
        u2 = UniformDistribution(self.y, closed(3, 4).simple_sets[0])

        product_unit = ProductUnit()
        product_unit.add_subcircuit(u1)
        product_unit.add_subcircuit(u2)
        self.model = product_unit

    def test_setup(self):
        self.assertEqual(len(self.model.probabilistic_circuit.nodes()), 3)
        self.assertEqual(len(self.model.probabilistic_circuit.edges()), 2)

    def test_variables(self):
        self.assertEqual(self.model.variables, SortedSet([self.x, self.y]))

    def test_leaves(self):
        self.assertEqual(len(self.model.leaves), 2)

    def test_likelihood(self):
        event = np.array([[0.5, 3.5]])
        result = self.model.likelihood(event)
        self.assertEqual(result, 1)

    def test_probability(self):
        event = SimpleEvent({self.x: closed(0, 0.5), self.y: closed(3, 3.5)}).as_composite_set()
        result = self.model.probability(event)
        self.assertEqual(result, 0.25)

    def test_mode(self):
        mode, likelihood = self.model.mode()
        self.assertEqual(likelihood, 1)
        self.assertEqual(mode,
                         SimpleEvent({self.x: closed(0, 1), self.y: closed(3, 4)}).as_composite_set())

    def test_sample(self):
        samples = self.model.sample(100)
        likelihood = self.model.likelihood(samples)
        self.assertTrue(all(likelihood > 0))

    def test_moment(self):
        expectation = self.model.expectation(self.model.variables)
        self.assertEqual(expectation[self.x], 0.5)
        self.assertEqual(expectation[self.y], 3.5)

    def test_conditional(self):
        event = SimpleEvent({self.x: closed(0, 0.5)}).as_composite_set()
        result, probability = self.model.conditional(event)
        self.assertEqual(probability, 0.5)
        self.assertEqual(len(result.probabilistic_circuit.nodes()), 3)
        self.assertIsInstance(result, ProductUnit)
        self.assertIsInstance(result.probabilistic_circuit.root, ProductUnit)

    def test_conditional_with_0_evidence(self):
        event = SimpleEvent({self.x: closed(1.5, 2)}).as_composite_set()
        result, probability = self.model.conditional(event)
        self.assertEqual(probability, 0)
        self.assertEqual(result, None)

    def test_marginal_with_intersecting_variables(self):
        marginal = self.model.marginal([self.x])
        self.assertEqual(len(marginal.probabilistic_circuit.nodes()), 2)
        self.assertEqual(marginal.probabilistic_circuit.variables, SortedSet([self.x]))

    def test_marginal_without_intersecting_variables(self):
        marginal = self.model.marginal([])
        self.assertIsNone(marginal)

    def test_domain(self):
        domain = self.model.support
        domain_by_hand = SimpleEvent({self.x: closed(0, 1),
                                      self.y: closed(3, 4)}).as_composite_set()
        self.assertEqual(domain, domain_by_hand)

    def test_serialization(self):
        serialized = self.model.to_json()
        deserialized = ProductUnit.from_json(serialized)
        self.assertEqual(self.model, deserialized)

    def test_copy(self):
        copy = self.model.__copy__()
        self.assertEqual(self.model, copy)
        self.assertNotEqual(id(copy), id(self.model))

    def test_sample_not_equal(self):
        samples = self.model.sample(10)
        uniques = np.unique(samples, axis=0)
        self.assertEqual(len(samples), len(uniques))

    def test_determinism(self):
        self.assertTrue(self.model.is_deterministic())


class SymbolEnum(SetElement):
    EMPTY_SET = -1
    A = 0
    B = 1
    C = 2


class MinimalGraphCircuitTestCase(unittest.TestCase, ShowMixin):
    integer = Integer("integer")
    symbol = Symbolic("symbol", SymbolEnum)
    real = Continuous("x")
    real2 = Continuous("y")
    real3 = Continuous("z")

    model: ProbabilisticCircuit

    def setUp(self):
        model = ProbabilisticCircuit()

        u1 = UniformDistribution(self.real, closed(0, 1).simple_sets[0])
        u2 = UniformDistribution(self.real, closed(3, 5).simple_sets[0])
        model.add_node(u1)
        model.add_node(u2)

        sum_unit_1 = SumUnit()

        model.add_node(sum_unit_1)

        model.add_edge(sum_unit_1, u1, weight=0.5)
        model.add_edge(sum_unit_1, u2, weight=0.5)

        u3 = UniformDistribution(self.real2, closed(2, 2.25).simple_sets[0])
        u4 = UniformDistribution(self.real2, closed(2, 5).simple_sets[0])
        sum_unit_2 = SumUnit()
        model.add_nodes_from([u3, u4, sum_unit_2])

        e3 = (sum_unit_2, u3, 0.7)
        e4 = (sum_unit_2, u4, 0.3)
        model.add_weighted_edges_from([e3, e4])

        product_1 = ProductUnit()
        model.add_node(product_1)

        e5 = (product_1, sum_unit_1)
        e6 = (product_1, sum_unit_2)
        model.add_edges_from([e5, e6])

        self.model = model

    def test_setup(self):
        self.assertEqual(len(self.model.nodes()), 7)
        self.assertEqual(len(self.model.edges()), 6)

    def test_variables(self):
        self.assertEqual(self.model.variables, SortedSet([self.real, self.real2]))

    def test_is_valid(self):
        self.assertTrue(self.model.is_valid())

    def test_root(self):
        self.assertIsInstance(self.model.root, ProductUnit)

    def test_variables_of_component(self):
        self.assertEqual(self.model.root.variables, SortedSet([self.real, self.real2]))
        self.assertEqual(list(self.model.nodes)[2].variables, SortedSet([self.real]))
        self.assertEqual(list(self.model.nodes)[5].variables, SortedSet([self.real2]))
        self.assertEqual(list(self.model.nodes)[6].variables, SortedSet([self.real, self.real2]))

    def test_likelihood(self):
        event = np.array([[1., 2.]])
        result = self.model.likelihood(event)
        self.assertEqual(result[0], 0.5 * ((4 * 0.7) + (1 / 3 * 0.3)))

    def test_probability_everywhere(self):
        event = SimpleEvent({self.real: closed(0, 5), self.real2: closed(2, 5)}).as_composite_set()
        result = self.model.probability(event)
        self.assertEqual(result, 1.)

    def test_probability_nowhere(self):
        event = SimpleEvent({self.real: closed(0, 0.5), self.real2: closed(0, 1)}).as_composite_set()
        result = self.model.probability(event)
        self.assertEqual(result, 0.)

    def test_probability_somewhere(self):
        event = SimpleEvent({self.real2: closed(0, 3)})
        event.fill_missing_variables(self.model.variables)
        result = self.model.probability(event.as_composite_set())
        self.assertAlmostEqual(result, 0.8)

    def test_caching_reset(self):
        event = SimpleEvent({self.real: closed(0, 5), self.real2: closed(2, 5)}).as_composite_set()
        _ = self.model.probability(event)

        for node in self.model.nodes():
            self.assertIsNone(node.result_of_current_query)
            self.assertFalse(node.cache_result)

    @unittest.skip("Caching is buggy.")
    def test_caching(self):
        event = SimpleEvent({self.real: closed(0, 5), self.real2: closed(2, 5)}).as_composite_set()
        self.model.root.cache_result = True
        _ = self.model.root.probability(event)

        for node in self.model.nodes():
            if not isinstance(node, ContinuousDistribution):
                self.assertIsNotNone(node.result_of_current_query)

    def test_mode(self):
        marginal = self.model.marginal([self.real])
        mode, likelihood = marginal.mode()
        self.assertEqual(likelihood, 0.5)
        self.assertEqual(mode, SimpleEvent({self.real: closed(0, 1)}).as_composite_set())

    def test_mode_raising(self):
        with self.assertRaises(IntractableError):
            _ = self.model.mode()

    def test_conditional(self):
        event = SimpleEvent({self.real: closed(0, 1)}).as_composite_set()
        result, probability = self.model.conditional(event)
        self.assertEqual(len(result.nodes()), 6)

    def test_sample(self):
        samples = self.model.sample(100)
        likelihoods = self.model.likelihood(samples)
        self.assertTrue(all(likelihoods > 0))

    def test_serialization(self):
        serialized = self.model.to_json()
        deserialized = ProbabilisticCircuit.from_json(serialized)
        self.assertEqual(self.model, deserialized)

    def test_update_variables(self):
        self.model.update_variables(VariableMap({self.real: self.real3}))
        self.assertEqual(self.model.variables, SortedSet([self.real2, self.real3]))

    def test_sample_not_equal(self):
        samples = self.model.sample(10)
        unique = np.unique(samples, axis=0)
        self.assertEqual(len(samples), len(unique))

    def test_determinism(self):
        self.assertFalse(self.model.is_deterministic())


class FactorizationTestCase(unittest.TestCase, ShowMixin):
    x: Continuous = Continuous("x")
    y: Continuous = Continuous("y")
    z: Continuous = Continuous("z")
    sum_unit_1: SumUnit
    sum_unit_2: SumUnit
    interaction_model: MultinomialDistribution

    def setUp(self):
        u1 = UniformDistribution(self.x, closed(0, 1).simple_sets[0])
        u2 = UniformDistribution(self.x, closed(3, 4).simple_sets[0])
        sum_unit_1 = SumUnit()
        sum_unit_1.add_subcircuit(u1, 0.5)
        sum_unit_1.add_subcircuit(u2, 0.5)
        self.sum_unit_1 = sum_unit_1

        u3 = UniformDistribution(self.y, closed(0, 1).simple_sets[0])
        u4 = UniformDistribution(self.y, closed(5, 6).simple_sets[0])
        sum_unit_2 = SumUnit()
        sum_unit_2.add_subcircuit(u3, 0.5)
        sum_unit_2.add_subcircuit(u4, 0.5)
        self.sum_unit_2 = sum_unit_2

        interaction_probabilities = np.array([[0, 0.5], [0.3, 0.2]])

        if self.sum_unit_1.latent_variable > self.sum_unit_2.latent_variable:
            interaction_probabilities = interaction_probabilities.T

        self.interaction_model = MultinomialDistribution([sum_unit_1.latent_variable, sum_unit_2.latent_variable],
                                                         interaction_probabilities)

    def test_setup(self):
        # these are flaky and need fixing
        # self.assertEqual(self.interaction_model.marginal([self.sum_unit_1.latent_variable]).probabilities.tolist(),
        #                  [0.5, 0.5])
        # self.assertEqual(self.interaction_model.marginal([self.sum_unit_2.latent_variable]).probabilities.tolist(),
        #                  [0.3, 0.7])
        self.assertEqual(len(self.sum_unit_1.probabilistic_circuit.nodes()), 3)
        self.assertEqual(len(self.sum_unit_2.probabilistic_circuit.nodes()), 3)

    def test_mount_with_interaction(self):
        self.sum_unit_1.mount_with_interaction_terms(self.sum_unit_2, self.interaction_model)
        self.assertIsInstance(self.sum_unit_1.probabilistic_circuit.root, SumUnit)

        for subcircuit in self.sum_unit_1.subcircuits:
            self.assertIsInstance(subcircuit, ProductUnit)

        self.assertEqual(len(self.sum_unit_1.probabilistic_circuit.nodes()), 9)
        self.assertEqual(len(self.sum_unit_1.probabilistic_circuit.edges()), 9)
        event = SimpleEvent({variable: variable.domain for variable in self.sum_unit_1.variables}).as_composite_set()
        self.assertEqual(1, self.sum_unit_1.probability(event))


class MountedInferenceTestCase(unittest.TestCase, ShowMixin):
    x: Continuous = Continuous("x")
    y: Continuous = Continuous("y")

    probabilities = np.array([[0, 1],
                              [1, 0]])
    model: SumUnit

    def setUp(self):
        np.random.seed(69)
        model = SumUnit()
        model.add_subcircuit(UniformDistribution(self.x, closed(-1.5, -0.5).simple_sets[0]), 0.5)
        model.add_subcircuit(UniformDistribution(self.x, closed(0.5, 1.5).simple_sets[0]), 0.5)
        next_model = model.__copy__()
        for leaf in next_model.leaves:
            leaf.variable = self.y

        transition_model = MultinomialDistribution([model.latent_variable, next_model.latent_variable],
                                                   self.probabilities)
        transition_model.normalize()
        next_model.mount_with_interaction_terms(model, transition_model)
        self.model = next_model

    def test_setup(self):
        self.assertEqual(self.model.variables, SortedSet([self.x, self.y]))
        self.assertTrue(self.model.probabilistic_circuit.is_decomposable())

    def test_sample_from_uniform(self):
        for leaf in self.model.leaves:
            samples = leaf.sample(2)

            self.assertNotEqual(samples[0], samples[1])

    def test_sample(self):
        samples = self.model.sample(2)
        self.assertEqual(len(samples), 2)
        self.assertFalse(any(samples[0] == samples[1]))

    def test_samples_in_sequence(self):
        samples = np.concatenate((self.model.probabilistic_circuit.sample(1),
                                  self.model.probabilistic_circuit.sample(1)))
        self.assertEqual(len(samples), 2)
        self.assertFalse(any(samples[0] == samples[1]))

    def test_plot_non_deterministic(self):
        gaussian_1 = GaussianDistribution(Continuous("x"), 0, 1)
        gaussian_2 = GaussianDistribution(Continuous("x"), 5, 0.5)
        mixture = SumUnit()
        mixture.add_subcircuit(gaussian_1, 0.5)
        mixture.add_subcircuit(gaussian_2, 0.5)
        traces = mixture.plot()
        self.assertGreater(len(traces), 0)
        # go.Figure(mixture.plot(), mixture.plotly_layout()).show()

    def test_simplify(self):
        simplified = self.model.simplify()
        self.assertEqual(len(simplified.probabilistic_circuit.nodes()), 7)
        self.assertEqual(len(simplified.probabilistic_circuit.edges()), 6)


class ComplexMountedInferenceTestCase(unittest.TestCase, ShowMixin):
    x: Continuous = Continuous("x")
    y: Continuous = Continuous("y")

    probabilities = np.array([[0.9, 0.1],
                              [0.3, 0.7]])
    model: SumUnit

    def setUp(self):
        np.random.seed(69)
        model = SumUnit()
        model.add_subcircuit(UniformDistribution(self.x, closed(-1.5, -0.5).simple_sets[0]), 0.5)
        model.add_subcircuit(UniformDistribution(self.x, closed(0.5, 1.5).simple_sets[0]), 0.5)
        next_model = model.__copy__()
        for leaf in next_model.leaves:
            leaf.variable = self.y

        transition_model = MultinomialDistribution([model.latent_variable, next_model.latent_variable],
                                                   self.probabilities)
        transition_model.normalize()
        next_model.mount_with_interaction_terms(model, transition_model)
        self.model = next_model

    @unittest.skip("This test is not working since the caching removal.")
    def test_simplify(self):
        simplified = self.model.probabilistic_circuit.simplify().root
        print(self.model.probabilistic_circuit)
        print(simplified.probabilistic_circuit)
        self.assertEqual(len(simplified.probabilistic_circuit.nodes()), len(self.model.probabilistic_circuit.nodes))
        self.assertEqual(len(simplified.probabilistic_circuit.edges()), len(self.model.probabilistic_circuit.edges))

    def test_sample_not_equal(self):
        samples = self.model.sample(10)
        unique = np.unique(samples, axis=0)
        self.assertEqual(len(samples), len(unique))

    def test_serialization(self):
        model = self.model.probabilistic_circuit
        serialized_model = model.to_json()
        deserialized_model = ProbabilisticCircuit.from_json(serialized_model)
        self.assertIsInstance(deserialized_model, ProbabilisticCircuit)
        self.assertEqual(len(model.nodes), len(deserialized_model.nodes))
        self.assertEqual(len(model.edges), len(deserialized_model.edges))
        event = SimpleEvent({self.x: closed(-1, 1), self.y: closed(-1, 1)}).as_composite_set()
        self.assertEqual(model.probability(event), deserialized_model.probability(event))


class MultivariateGaussianTestCase(unittest.TestCase, ShowMixin):
    x: Continuous = Continuous("x")
    y: Continuous = Continuous("y")
    model: ProbabilisticCircuit

    def setUp(self):
        product = ProductUnit()
        n1 = GaussianDistribution(self.x, 0, 1)
        n2 = GaussianDistribution(self.y, 0.5, 2)
        product.add_subcircuit(n1)
        product.add_subcircuit(n2)
        self.model = product.probabilistic_circuit

    def test_plot_2d(self):
        traces = self.model.plot()
        assert len(traces) > 0
        # go.Figure(traces, self.model.plotly_layout()).show()

    def test_truncation(self):
        event = SimpleEvent({self.x: open(-0.1, 0.1), self.y: open(-0.1, 0.1)}).as_composite_set()
        outer_event = event.complement()

        # first truncation
        conditional, probability = self.model.conditional(outer_event)

        self.assertEqual(outer_event, conditional.support)

        # go.Figure(conditional.plot(), conditional.plotly_layout()).show()
        samples = list(conditional.sample(500))

        for sample in samples:
            self.assertTrue(conditional.likelihood(sample.reshape(1, -1)) > 0)
            self.assertFalse(sample[0] in event.simple_sets[0][self.x] and sample[1] in event.simple_sets[0][self.y])

        # second truncation
        limiting_event = SimpleEvent({self.x: open(-2, 2), self.y: open(-2, 2)}).as_composite_set()

        conditional, probability = conditional.conditional(limiting_event)
        #  self.show(conditional)
        #  go.Figure(conditional.domain.plot()).show()
        self.assertEqual(len(conditional.sample(500)), 500)

        # go.Figure(conditional.plot(), conditional.plotly_layout()).show()

        domain = outer_event & limiting_event
        self.assertEqual(domain, conditional.support)

    def test_open_closed_set_bug(self):
        tg1 = TruncatedGaussianDistribution(self.y, open(-0.1, 0.1).simple_sets[0], 0, 1)
        event = SimpleEvent({self.x: open(-2, 2), self.y: open(-2, 2)}).as_composite_set()
        r, _ = tg1.conditional(event)
        self.assertIsNotNone(r)


class ComplexInferenceTestCase(unittest.TestCase):
    x: Continuous = Continuous("x")
    y: Continuous = Continuous("y")
    model: ProbabilisticCircuit

    e1: Event = SimpleEvent({x: closed(0, 1), y: closed_open(0, 1)}).as_composite_set()
    e2: Event = SimpleEvent({x: closed(1.5, 2), y: closed(1.5, 2)}).as_composite_set()

    event: Event = e1 | e2

    def setUp(self):
        root = ProductUnit()
        px = UniformDistribution(self.x, closed(0, 2).simple_sets[0])
        py = UniformDistribution(self.y, closed(0, 3).simple_sets[0])
        root.add_subcircuit(px)
        root.add_subcircuit(py)
        self.model = root.probabilistic_circuit

    def test_complex_probability(self):
        p = self.model.probability(self.event)
        self.assertEqual(self.model.probability(self.e1) + self.model.probability(self.e2), p)

    def test_complex_conditional(self):
        conditional, probability = self.model.conditional(self.event)
        self.assertAlmostEqual(conditional.probability(self.event), 1.)


class KitchenCircuitTestCase(unittest.TestCase, ShowMixin):
    model: ProbabilisticCircuit
    x = Continuous("x")
    y = Continuous("y")

    kitchen = SimpleEvent({x: closed(0, 6.6), y: closed(0, 7)}).as_composite_set()
    refrigerator = SimpleEvent({x: closed(5, 6), y: closed(6.3, 7)}).as_composite_set()
    top_kitchen_island = SimpleEvent({x: closed(0, 5), y: closed(6.5, 7)}).as_composite_set()
    left_cabinets = SimpleEvent({x: closed(0, 0.5), y: closed(0, 6.5)}).as_composite_set()

    center_island = SimpleEvent({x: closed(2, 4), y: closed(3, 5)}).as_composite_set()

    occupied_spaces = refrigerator | top_kitchen_island | left_cabinets | center_island
    free_space = kitchen - occupied_spaces

    def setUp(self):
        root = ProductUnit()
        root.add_subcircuit(GaussianDistribution(self.x, 5.5, 0.25))
        root.add_subcircuit(GaussianDistribution(self.y, 6.65, 0.25))
        self.model = root.probabilistic_circuit

    def test_conditioning(self):
        model, _ = self.model.conditional(self.free_space)
        self.assertEqual(len(model.root.subcircuits), len(self.free_space.simple_sets))
        traces = model.plot(number_of_samples=10000)
        assert len(traces) > 0
        # go.Figure(traces, model.plotly_layout()).show()


class ConvolutionTestCase(unittest.TestCase, ShowMixin):

    def setUp(self):
        self.variable = Continuous("x")
        self.interval = closed(-1, 1).simple_sets[0]
        self.mean = 0
        self.scale = 1
        self.location = 3
        self.density_cap = 1

    def test_uniform_with_dirac_delta_convolution(self):
        uniform_distribution = UniformDistribution(self.variable, self.interval)
        dirac_delta_distribution = DiracDeltaDistribution(self.variable, self.location, self.density_cap)
        convolution = UniformDistributionConvolution(uniform_distribution)
        result = convolution.convolve_with_dirac_delta(dirac_delta_distribution)
        self.assertEqual(result.interval, closed(self.interval.lower + self.location,
                                                 self.interval.upper + self.location).simple_sets[0])

    def test_dirac_delta_with_dirac_delta_convolution(self):
        dirac_delta_distribution1 = DiracDeltaDistribution(self.variable, self.location, self.density_cap)
        dirac_delta_distribution2 = DiracDeltaDistribution(self.variable, self.location, self.density_cap)
        convolution = DiracDeltaDistributionConvolution(dirac_delta_distribution1)
        result = convolution.convolve_with_dirac_delta(dirac_delta_distribution2)
        self.assertEqual(result.location, self.location * 2)

    def test_gaussian_with_dirac_delta_convolution(self):
        gaussian_distribution = GaussianDistribution(self.variable, self.mean, self.scale)
        dirac_delta_distribution = DiracDeltaDistribution(self.variable, self.location, self.density_cap)
        convolution = GaussianDistributionConvolution(gaussian_distribution)
        result = convolution.convolve_with_dirac_delta(dirac_delta_distribution)
        self.assertEqual(result.location, self.mean + self.location)

    def test_gaussian_with_gaussian_convolution(self):
        gaussian_distribution1 = GaussianDistribution(self.variable, self.mean, self.scale)
        gaussian_distribution2 = GaussianDistribution(self.variable, self.mean, self.scale)
        convolution = GaussianDistributionConvolution(gaussian_distribution1)
        result = convolution.convolve_with_gaussian(gaussian_distribution2)
        self.assertEqual(result.location, self.mean * 2)
        self.assertEqual(result.scale, self.scale * 2)

    def test_truncated_gaussian_with_dirac_delta_convolution(self):
        truncated_gaussian_distribution = TruncatedGaussianDistribution(self.variable, self.interval, self.mean,
                                                                        self.scale)
        dirac_delta_distribution = DiracDeltaDistribution(self.variable, self.location, self.density_cap)
        convolution = TruncatedGaussianDistributionConvolution(truncated_gaussian_distribution)
        result = convolution.convolve_with_dirac_delta(dirac_delta_distribution)
        self.assertEqual(result.interval, closed(self.interval.lower + self.location,
                                                 self.interval.upper + self.location).simple_sets[0])
        self.assertEqual(result.location, self.mean + self.location)

    def test_mode_of_symmetric_truncation(self):
        interval = open(-0.3, 0.3).complement()
        g1 = GaussianDistribution(self.variable, 0, 1)
        g2, _ = g1.conditional(SimpleEvent({self.variable: interval}).as_composite_set())
        mode, _ = g2.mode()
        self.assertEqual(len(mode.simple_sets), 1)


class ClassicExampleTestCase(unittest.TestCase):

    x = Continuous("x")
    y = Continuous("y")
    sum1, sum2, sum3 = SumUnit(), SumUnit(), SumUnit()
    sum4, sum5 = SumUnit(), SumUnit()
    prod1, prod2 = ProductUnit(), ProductUnit()
    model = ProbabilisticCircuit()
    model.add_node(sum1)
    model.add_node(prod1)
    model.add_node(prod2)
    model.add_edge(sum1, prod1, weight=0.5)
    model.add_edge(sum1, prod2, weight=0.5)
    model.add_node(sum2)
    model.add_node(sum3)
    model.add_node(sum4)
    model.add_node(sum5)
    model.add_edge(prod1, sum2)
    model.add_edge(prod1, sum4)
    model.add_edge(prod2, sum3)
    model.add_edge(prod2, sum5)
    d_x1, d_x2 = DiracDeltaDistribution(x, 0, 1), DiracDeltaDistribution(x, 1, 2)
    d_y1, d_y2 = DiracDeltaDistribution(y, 2, 3), DiracDeltaDistribution(y, 3, 4)

    model.add_node(d_y1)
    model.add_node(d_x2)
    model.add_node(d_y2)
    model.add_node(d_x1)

    model.add_edge(sum2, d_x1, weight=0.8)
    model.add_edge(sum2, d_x2, weight=0.2)
    model.add_edge(sum3, d_x1, weight=0.7)
    model.add_edge(sum3, d_x2, weight=0.3)

    model.add_edge(sum4, d_y1, weight=0.5)
    model.add_edge(sum4, d_y2, weight=0.5)
    model.add_edge(sum5, d_y1, weight=0.1)
    model.add_edge(sum5, d_y2, weight=0.9)

    def test_sampling(self):
        samples = self.model.sample(100)
        unique = np.unique(samples, axis=0)
        self.assertEqual(len(unique), 4)

    def test_plot(self):
        self.model.root.plot_structure()

if __name__ == '__main__':
    unittest.main()

from probabilistic_model.learning.jpt.jpt import JPT, ProductUnit as JPTLeaf
from random_events.interval import SimpleInterval



class StructuredDecomposabilityTestCase(unittest.TestCase):
    model = ProbabilisticCircuit()
    x = Continuous("x")
    y = Continuous("y")
    z = Continuous("z")

    sum_unit_1 = SumUnit()
    model.add_node(sum_unit_1)
    product_1, product_2, product_3 = ProductUnit(), ProductUnit(), ProductUnit()
    product_4, product_5, product_6 = ProductUnit(), ProductUnit(), ProductUnit()

    model.add_node(product_1)
    model.add_node(product_2)
    model.add_edge(sum_unit_1, product_1, weight=0.5)
    model.add_edge(sum_unit_1, product_2, weight=0.5)

    sum_unit_2 = SumUnit()
    sum_unit_3 = SumUnit()
    product_1.add_subcircuit(sum_unit_2)
    product_1.add_subcircuit(UniformDistribution(z, SimpleInterval(2, 3)))
    product_2.add_subcircuit(sum_unit_3)
    product_2.add_subcircuit(UniformDistribution(z, SimpleInterval(4, 5)))

    sum_unit_2.add_subcircuit(product_3, weight=0.5)
    sum_unit_2.add_subcircuit(product_4, weight=0.5)
    sum_unit_3.add_subcircuit(product_5, weight=0.5)
    sum_unit_3.add_subcircuit(product_6, weight=0.5)

    range1 = SimpleInterval(0, 2)
    range2 = SimpleInterval(4, 6)
    for unit in [product_3, product_4, product_5, product_6]:
        unit.add_subcircuit(UniformDistribution(x, range1))
        unit.add_subcircuit(UniformDistribution(y, range2))

    def test_is_structured_decomposable(self):
        assert self.model.is_structured_decomposable()

    def test_structured_decomposable_as_ture(self):
        model_other = ProbabilisticCircuit()
        x = Continuous("x")
        y = Continuous("y")
        z = Continuous("z")

        sum_unit_1 = SumUnit()
        model_other.add_node(sum_unit_1)
        product_1, product_2, product_3 = ProductUnit(), ProductUnit(), ProductUnit()
        product_4, product_5, product_6 = ProductUnit(), ProductUnit(), ProductUnit()

        model_other.add_node(product_1)
        model_other.add_node(product_2)
        model_other.add_edge(sum_unit_1, product_1, weight=0.5)
        model_other.add_edge(sum_unit_1, product_2, weight=0.5)

        sum_unit_2 = SumUnit()
        sum_unit_3 = SumUnit()
        product_1.add_subcircuit(sum_unit_2)
        product_1.add_subcircuit(UniformDistribution(z, SimpleInterval(7, 19)))
        product_2.add_subcircuit(sum_unit_3)
        product_2.add_subcircuit(UniformDistribution(z, SimpleInterval(0, 5)))

        sum_unit_2.add_subcircuit(product_3, weight=0.3)
        sum_unit_2.add_subcircuit(product_4, weight=0.7)
        sum_unit_3.add_subcircuit(product_5, weight=0.5)
        sum_unit_3.add_subcircuit(product_6, weight=0.5)

        range1 = SimpleInterval(0, 5)
        range2 = SimpleInterval(4, 6)
        for unit in [product_3, product_4, product_5, product_6]:
            unit.add_subcircuit(UniformDistribution(x, range1))
            unit.add_subcircuit(UniformDistribution(y, range2))

        assert self.model.decomposes_as(model_other)

    def test_structured_decomposable_as_false(self):
        model_other = ProbabilisticCircuit()
        x = Continuous("z")
        y = Continuous("y")
        z = Continuous("x")

        sum_unit_1 = SumUnit()
        model_other.add_node(sum_unit_1)
        product_1, product_2, product_3 = ProductUnit(), ProductUnit(), ProductUnit()
        product_4, product_5, product_6 = ProductUnit(), ProductUnit(), ProductUnit()

        model_other.add_node(product_1)
        model_other.add_node(product_2)
        model_other.add_edge(sum_unit_1, product_1, weight=0.5)
        model_other.add_edge(sum_unit_1, product_2, weight=0.5)

        sum_unit_2 = SumUnit()
        sum_unit_3 = SumUnit()
        product_1.add_subcircuit(sum_unit_2)
        product_1.add_subcircuit(UniformDistribution(z, SimpleInterval(7, 19)))
        product_2.add_subcircuit(sum_unit_3)
        product_2.add_subcircuit(UniformDistribution(z, SimpleInterval(0, 5)))

        sum_unit_2.add_subcircuit(product_3, weight=0.3)
        sum_unit_2.add_subcircuit(product_4, weight=0.7)
        sum_unit_3.add_subcircuit(product_5, weight=0.5)
        sum_unit_3.add_subcircuit(product_6, weight=0.5)

        range1 = SimpleInterval(0, 5)
        range2 = SimpleInterval(4, 6)
        for unit in [product_3, product_4, product_5, product_6]:
            unit.add_subcircuit(UniformDistribution(x, range1))
            unit.add_subcircuit(UniformDistribution(y, range2))

        assert not self.model.decomposes_as(model_other)


class ShallowTestCase(unittest.TestCase):
    x = Continuous("x")
    y = Continuous("y")
    sum1, sum2, sum3 = SumUnit(), SumUnit(), SumUnit()
    sum4, sum5 = SumUnit(), SumUnit()
    prod1, prod2 = ProductUnit(), ProductUnit()
    model = ProbabilisticCircuit()
    model.add_node(sum1)
    model.add_node(prod1)
    model.add_node(prod2)
    model.add_edge(sum1, prod1, weight=0.5)
    model.add_edge(sum1, prod2, weight=0.5)
    model.add_node(sum2)
    model.add_node(sum3)
    model.add_node(sum4)
    model.add_node(sum5)
    model.add_edge(prod1, sum2)
    model.add_edge(prod1, sum4)
    model.add_edge(prod2, sum3)
    model.add_edge(prod2, sum5)
    uni_x1, uni_x2  = UniformDistribution(x, SimpleInterval(0, 1)), UniformDistribution(x, SimpleInterval(1, 2))
    uni_y1, uni_y2 = UniformDistribution(y, SimpleInterval(0, 1)), UniformDistribution(y, SimpleInterval(1, 2))

    model.add_node(uni_y1)
    model.add_node(uni_x2)
    model.add_node(uni_y2)
    model.add_node(uni_x1)

    model.add_edge(sum2, uni_x1, weight=0.8)
    model.add_edge(sum2, uni_x2, weight=0.2)
    model.add_edge(sum3, uni_x1, weight=0.7)
    model.add_edge(sum3, uni_x2, weight=0.3)

    model.add_edge(sum4, uni_y1, weight=0.5)
    model.add_edge(sum4, uni_y2, weight=0.5)
    model.add_edge(sum5, uni_y1, weight=0.1)
    model.add_edge(sum5, uni_y2, weight=0.9)

    def test_shallow(self):
        shallow_pc = ShallowProbabilisticCircuit.from_probabilistic_circuit(self.model)
        self.assertTrue(True)



class AreaValidationMetricTestCase(unittest.TestCase):

    x = Continuous("x")
    y = Continuous("y")
    standard_circuit = JPTLeaf()
    standard_circuit.add_subcircuit(UniformDistribution(x, SimpleInterval(0, 1)))
    standard_circuit.add_subcircuit(UniformDistribution(y, SimpleInterval(0, 1)))
    standard_circuit = standard_circuit.probabilistic_circuit

    event_1 = SimpleEvent({x: closed(0, .25), y: closed(0, .25)})
    event_2 = SimpleEvent({x: closed(0.75, 1), y: closed(0.75, 1)})

    circuit_1, _ = standard_circuit.conditional(event_1.as_composite_set().complement())
    circuit_2, _ = standard_circuit.conditional(event_2.as_composite_set().complement())
    circuit_3, _ = circuit_2.conditional(event_1.as_composite_set())
    circuit_4, _ = circuit_1.conditional(event_2.as_composite_set())

    shallow_1 = ShallowProbabilisticCircuit.from_probabilistic_circuit(circuit_1)
    shallow_2 = ShallowProbabilisticCircuit.from_probabilistic_circuit(circuit_2)
    shallow_3 = ShallowProbabilisticCircuit.from_probabilistic_circuit(circuit_3)
    shallow_4 = ShallowProbabilisticCircuit.from_probabilistic_circuit(circuit_4)





    def test_jpt_avm(self):


        result = self.shallow_1.area_validation_metric(self.shallow_2)

        p_event_by_hand = self.event_2
        q_event_by_hand = self.event_1
        self.assertEqual(self.circuit_2.probability(p_event_by_hand.as_composite_set()), 0)
        self.assertEqual(self.circuit_1.probability(q_event_by_hand.as_composite_set()), 0)
        result_by_hand = self.circuit_1.probability(p_event_by_hand.as_composite_set()) + self.circuit_2.probability(
            q_event_by_hand.as_composite_set())
        self.assertAlmostEqual(result, result_by_hand / 2, 4)

    def test_jpt_avm_same_input(self):
        result = self.shallow_1.area_validation_metric(self.shallow_1)
        self.assertEqual(result, 0)

    def test_jpt_avm_disjunct_input(self):
        result = self.shallow_3.area_validation_metric(self.shallow_4)

        self.assertEqual(result, 1)

    def test_avm_mc(self):
        mc_esti = Monte_Carlo_Estimator.MonteCarloEstimator(sample_size=1000, model=self.circuit_1)
        result = mc_esti.area_validation_metric(self.circuit_2)
        self.assertAlmostEqual(result/2, 0.13333333333333336, delta=0.1)

    def test_avm_diff_mc(self):
        # go.Figure(self.circuit_1.plot()).show()
        # go.Figure(self.circuit_2.plot()).show()
        # go.Figure(self.shallow_3.plot()).show()
        # go.Figure(self.shallow_4.plot()).show()



        mc_esti = Monte_Carlo_Estimator.MonteCarloEstimator(sample_size=10000, model=self.circuit_1)
        amv_result = self.shallow_1.area_validation_metric(self.shallow_2)
        mc_resutl1 = mc_esti.l1_metric_but_with_uniform_measure(self.circuit_2)
        mc_resutl2 = mc_esti.area_validation_metric2(self.circuit_2)
        print(f"real: {amv_result}, l1: {mc_resutl1}, mc2: {mc_resutl2}")
        self.assertTrue(True)

    def test_temp(self):
        # print(self.shallow_1.events_of_higher_density_sum(self.shallow_2))
        # print(self.shallow_1.events_of_higher_density_cool(self.shallow_2))
        # print("-"*80)
        #
        ep = self.shallow_1.events_of_higher_density_sum_swag(self.shallow_2)
        # go.Figure(ep.plot()).show()

        l1 = self.shallow_1.l1_swag(self.shallow_2)
        l1o = self.shallow_2.l1_swag(self.shallow_1)
        mc_esti = Monte_Carlo_Estimator.MonteCarloEstimator(sample_size=10000, model=self.circuit_1)
        mc = mc_esti.l1_metric_but_with_uniform_measure(self.circuit_2)
        mc2 = mc_esti.l1(self.circuit_2)
        print(f"l1: {l1}, l2: {l1o} mc: {mc}, mc2: {mc2}")
        # mc_esti = Monte_Carlo_Estimator.MonteCarloEstimator(sample_size=10000, model=self.circuit_1)
        # l1 = self.shallow_1.l1_cool(self.shallow_2)
        # mc = mc_esti.l1_metric_but_with_uniform_measure(self.circuit_2)
        # avm = self.shallow_1.area_validation_metric(self.shallow_2)
        # print("avm: {}, l1: {}, mc: {}".format(avm, l1, mc))
        # print("-"*80)
        # mc_esti = Monte_Carlo_Estimator.MonteCarloEstimator(sample_size=10000, model=self.circuit_1)
        # l1 = self.shallow_1.l1_cool(self.shallow_4)
        # mc = mc_esti.l1_metric_but_with_uniform_measure(self.circuit_4)
        # avm = self.shallow_1.area_validation_metric(self.shallow_4)
        #
        # print("avm: {}, l1: {}, mc: {}".format(avm, l1, mc))

class testingClass(unittest.TestCase):
    x = Continuous("x")
    y = Continuous("y")
    sum1, sum2, sum3 = SumUnit(), SumUnit(), SumUnit()
    sum4, sum5 = SumUnit(), SumUnit()
    prod1, prod2 = ProductUnit(), ProductUnit()
    model = ProbabilisticCircuit()
    model.add_node(sum1)
    model.add_node(prod1)
    model.add_node(prod2)
    model.add_edge(sum1, prod1, weight=0.5)
    model.add_edge(sum1, prod2, weight=0.5)
    model.add_node(sum2)
    model.add_node(sum3)
    model.add_node(sum4)
    model.add_node(sum5)
    model.add_edge(prod1, sum2)
    model.add_edge(prod1, sum4)
    model.add_edge(prod2, sum3)
    model.add_edge(prod2, sum5)
    uni_x1, uni_x2 = UniformDistribution(x, SimpleInterval(0, 1)), UniformDistribution(x, SimpleInterval(1, 2))
    uni_y1, uni_y2 = UniformDistribution(y, SimpleInterval(0, 1)), UniformDistribution(y, SimpleInterval(1, 2))

    model.add_node(uni_y1)
    model.add_node(uni_x2)
    model.add_node(uni_y2)
    model.add_node(uni_x1)

    model.add_edge(sum2, uni_x1, weight=0.8)
    model.add_edge(sum2, uni_x2, weight=0.2)
    model.add_edge(sum3, uni_x1, weight=0.7)
    model.add_edge(sum3, uni_x2, weight=0.3)

    model.add_edge(sum4, uni_y1, weight=0.5)
    model.add_edge(sum4, uni_y2, weight=0.5)
    model.add_edge(sum5, uni_y1, weight=0.1)
    model.add_edge(sum5, uni_y2, weight=0.9)


    sum21, sum22, sum23 = SumUnit(), SumUnit(), SumUnit()
    sum24, sum25 = SumUnit(), SumUnit()
    prod21, prod22 = ProductUnit(), ProductUnit()
    model2 = ProbabilisticCircuit()
    model2.add_node(sum21)
    model2.add_node(prod21)
    model2.add_node(prod22)
    model2.add_edge(sum21, prod21, weight=0.5)
    model2.add_edge(sum21, prod22, weight=0.5)
    model2.add_node(sum22)
    model2.add_node(sum23)
    model2.add_node(sum24)
    model2.add_node(sum25)
    model2.add_edge(prod21, sum22)
    model2.add_edge(prod21, sum24)
    model2.add_edge(prod22, sum23)
    model2.add_edge(prod22, sum25)
    uni_x21, uni_x22 = UniformDistribution(x, SimpleInterval(1.5, 2.5)), UniformDistribution(x, SimpleInterval(1.5, 2.5))
    uni_y21, uni_y22 = UniformDistribution(y, SimpleInterval(1.5, 2.5)), UniformDistribution(y, SimpleInterval(1.5, 2.5))

    model2.add_node(uni_y21)
    model2.add_node(uni_x22)
    model2.add_node(uni_y22)
    model2.add_node(uni_x21)

    model2.add_edge(sum22, uni_x21, weight=0.8)
    model2.add_edge(sum22, uni_x22, weight=0.2)
    model2.add_edge(sum23, uni_x21, weight=0.7)
    model2.add_edge(sum23, uni_x22, weight=0.3)

    model2.add_edge(sum24, uni_y21, weight=0.5)
    model2.add_edge(sum24, uni_y22, weight=0.5)
    model2.add_edge(sum25, uni_y21, weight=0.1)
    model2.add_edge(sum25, uni_y22, weight=0.9)


    #------------------BIG---------------------

    x = Continuous("x")
    y = Continuous("y")
    sum31, sum32, sum33 = SumUnit(), SumUnit(), SumUnit()
    sum34, sum35 = SumUnit(), SumUnit()
    prod31, prod32 = ProductUnit(), ProductUnit()
    model3 = ProbabilisticCircuit()
    model3.add_node(sum31)
    model3.add_node(prod31)
    model3.add_node(prod32)
    model3.add_edge(sum31, prod31, weight=0.5)
    model3.add_edge(sum31, prod32, weight=0.5)
    model3.add_node(sum32)
    model3.add_node(sum33)
    model3.add_node(sum34)
    model3.add_node(sum35)
    model3.add_edge(prod31, sum32)
    model3.add_edge(prod31, sum34)
    model3.add_edge(prod32, sum33)
    model3.add_edge(prod32, sum35)
    uni_x31, uni_x32 = UniformDistribution(x, SimpleInterval(0, 1)), UniformDistribution(x, SimpleInterval(1, 2))
    uni_y31, uni_y32 = UniformDistribution(y, SimpleInterval(0, 1)), UniformDistribution(y, SimpleInterval(1, 2))

    model3.add_node(uni_y31)
    model3.add_node(uni_x32)
    model3.add_node(uni_y32)
    model3.add_node(uni_x31)

    model3.add_edge(sum32, uni_x31, weight=0.8)
    model3.add_edge(sum32, uni_x32, weight=0.2)
    model3.add_edge(sum33, uni_x31, weight=0.7)
    model3.add_edge(sum33, uni_x32, weight=0.3)

    model3.add_edge(sum34, uni_y31, weight=0.5)
    model3.add_edge(sum34, uni_y32, weight=0.5)
    model3.add_edge(sum35, uni_y31, weight=0.1)
    model3.add_edge(sum35, uni_y32, weight=0.9)

    sum42, sum43 = SumUnit(), SumUnit()
    sum44, sum45 = SumUnit(), SumUnit()
    prod41, prod42 = ProductUnit(), ProductUnit()

    model3.add_node(prod41)
    model3.add_node(prod42)
    model3.add_edge(sum31, prod41, weight=0.5)
    model3.add_edge(sum31, prod42, weight=0.5)
    model3.add_node(sum42)
    model3.add_node(sum43)
    model3.add_node(sum44)
    model3.add_node(sum45)
    model3.add_edge(prod41, sum42)
    model3.add_edge(prod41, sum44)
    model3.add_edge(prod42, sum43)
    model3.add_edge(prod42, sum45)
    uni_x41, uni_x42 = UniformDistribution(x, SimpleInterval(3, 4)), UniformDistribution(x,SimpleInterval(4, 5))
    uni_y41, uni_y42 = UniformDistribution(y, SimpleInterval(3, 4)), UniformDistribution(y, SimpleInterval(4, 5))

    model3.add_node(uni_y41)
    model3.add_node(uni_x42)
    model3.add_node(uni_y42)
    model3.add_node(uni_x41)

    model3.add_edge(sum42, uni_x41, weight=0.8)
    model3.add_edge(sum42, uni_x42, weight=0.2)
    model3.add_edge(sum43, uni_x41, weight=0.7)
    model3.add_edge(sum43, uni_x42, weight=0.3)

    model3.add_edge(sum44, uni_y41, weight=0.5)
    model3.add_edge(sum44, uni_y42, weight=0.5)
    model3.add_edge(sum45, uni_y41, weight=0.1)
    model3.add_edge(sum45, uni_y42, weight=0.9)

    def test(self):
        mc = Monte_Carlo_Estimator.MonteCarloEstimator(self.model, 100000)
        mc2 = Monte_Carlo_Estimator.MonteCarloEstimator(self.model2, 100000)
        mc3 = Monte_Carlo_Estimator.MonteCarloEstimator(self.model3, 100000)
        shallow = ShallowProbabilisticCircuit.from_probabilistic_circuit(self.model)
        shallow2 = ShallowProbabilisticCircuit.from_probabilistic_circuit(self.model2)
        shallow3 = ShallowProbabilisticCircuit.from_probabilistic_circuit(self.model3)

        avm_13 = shallow.area_validation_metric(shallow3)
        l1_13 = shallow.l1_cool(shallow3)
        mc_13 = mc.area_validation_metric2(shallow3)
        print(f"avm_13: {avm_13}, l1_13: {l1_13}, mc_13: {mc_13}")

if __name__ == '__main__':
    unittest.main()
