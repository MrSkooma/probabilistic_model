import unittest

from random_events.interval import *
from random_events.product_algebra import *

from probabilistic_model.distributions.distributions import DiracDeltaDistribution
from probabilistic_model.distributions.uniform import UniformDistribution
from probabilistic_model.utils import SubclassJSONSerializer


class UniformDistributionTestCase(unittest.TestCase):
    x: Continuous = Continuous("x")
    distribution: UniformDistribution = UniformDistribution(x, SimpleInterval(0, 2, Bound.CLOSED, Bound.OPEN))

    def test_domain(self):
        self.assertEqual(self.distribution.univariate_support, self.distribution.interval.as_composite_set())

    def test_likelihood(self):
        pdf = self.distribution.likelihood(np.array([-1, 1, 2]).reshape(-1, 1))
        self.assertEqual(pdf[0], 0)
        self.assertEqual(pdf[1], 0.5)
        self.assertEqual(pdf[2], 0)

    def test_probability_of_domain(self):
        self.assertEqual(self.distribution.probability(self.distribution.support()), 1)

    def test_cdf(self):
        cdf = self.distribution.cdf(np.array([-1, 1, 2]))
        self.assertEqual(cdf[0], 0)
        self.assertEqual(cdf[1], 0.5)
        self.assertEqual(cdf[2], 1)

    def test_probability(self):
        event = SimpleEvent({self.x: closed(0, 1) | closed(1.5, 2)}).as_composite_set()
        self.assertEqual(self.distribution.probability(event), 0.75)

    def test_mode(self):
        modes, likelihood = self.distribution.mode()
        self.assertEqual(modes, self.distribution.support())
        self.assertEqual(likelihood, 0.5)

    def test_sample(self):
        samples = self.distribution.sample(100)
        self.assertEqual(len(samples), 100)
        likelihoods = self.distribution.likelihood(samples)
        self.assertTrue(all(likelihoods == 0.5))

    def test_conditional_no_intersection(self):
        event = SimpleEvent({self.x: closed(3, 4)}).as_composite_set()
        conditional, probability = self.distribution.conditional(event)
        self.assertIsNone(conditional)
        self.assertEqual(probability, 0)

    def test_conditional_singleton_intersection(self):
        event = SimpleEvent({self.distribution.variable: singleton(1)}).as_composite_set()
        conditional, probability = self.distribution.conditional(event)
        self.assertEqual(conditional, DiracDeltaDistribution(self.x, 1, 0.5))
        self.assertEqual(probability, 0.5)

    def test_conditional_simple_intersection(self):
        event = SimpleEvent({self.distribution.variable: closed(1, 2)}).as_composite_set()
        conditional, probability = self.distribution.conditional(event)
        conditional_by_hand = UniformDistribution(self.x, SimpleInterval(1, 2, Bound.CLOSED, Bound.OPEN))
        self.assertEqual(conditional, conditional_by_hand)
        self.assertEqual(probability, 0.5)

    def test_moment(self):
        expectation = self.distribution.moment(VariableMap({self.distribution.variable: 1}),
                                               VariableMap({self.distribution.variable: 0}))
        self.assertEqual(expectation[self.distribution.variable], 1)
        variance = self.distribution.moment(VariableMap({self.distribution.variable: 2}), expectation)
        self.assertEqual(variance[self.distribution.variable], 1 / 3)

    def test_plot(self):
        fig = go.Figure(data=self.distribution.plot())
        self.assertIsNotNone(fig)
        # fig.show()

    def test_partly_joint_different_Distributions(self):
        variable = self.distribution.variable
        distribution_1 = UniformDistribution(variable, portion.closed(7, 24))
        distribution_2 = UniformDistribution(variable, portion.closed(-4, 15))
        self.assertEqual(distribution_1.area_validation_metric(distribution_2), (22 / 19) / 2)

    def test_avm_partly_joint(self):
        variable = self.distribution.variable
        distribution_1 = UniformDistribution(variable, portion.closed(7, 24))
        distribution_2 = UniformDistribution(variable, portion.closed(-4, 15))
        self.assertEqual(distribution_1.area_validation_metric(distribution_2), (22 / 19) / 2)

    def test_avm_no_overlapping(self):
        variable = self.distribution.variable
        distribution_1 = UniformDistribution(variable, portion.closed(0, 1))
        distribution_2 = UniformDistribution(variable, portion.closed(2, 3))
        self.assertEqual(distribution_1.area_validation_metric(distribution_2), 1)

    def test_avm_overlapping(self):
        variable = self.distribution.variable
        distribution_1 = UniformDistribution(variable, portion.closed(0, 1))
        distribution_2 = UniformDistribution(variable, portion.closed(0, 1))
        self.assertEqual(distribution_1.area_validation_metric(distribution_2), 0)


    def test_variable_setting(self):
        distribution = UniformDistribution(Continuous("x"), closed(0, 1).simple_sets[0])
        self.assertEqual(distribution.variable, Continuous("x"))
        distribution.variable = Continuous("y")
        self.assertEqual(distribution.variable, Continuous("y"))
