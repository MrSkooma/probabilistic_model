import unittest

import portion
from matplotlib import pyplot as plt
from random_events.events import Event
from random_events.variables import Integer, Symbolic, Continuous

from probabilistic_model.graph_circuits.probabilistic_circuit import *

from probabilistic_model.graph_circuits.distributions.distributions import UniformDistribution


class UniformDistributionTestCase(unittest.TestCase):

    variable = Continuous("x")
    model: UniformDistribution

    def setUp(self):
        circuit = ProbabilisticCircuit()
        self.model = UniformDistribution(self.variable, portion.closed(0, 1))
        circuit.add_node(self.model)

    def show(self):
        nx.draw(self.model.probabilistic_circuit, with_labels=True)
        plt.show()

    def test_conditional_from_simple_event(self):
        event = Event({self.variable: portion.closed(0.5, 2)})
        conditional, probability = self.model.conditional(event)
        self.assertEqual(len(list(self.model.probabilistic_circuit.nodes)), 1)
        conditional_from_circuit = list(self.model.probabilistic_circuit.nodes)[0]
        self.assertEqual(conditional, conditional_from_circuit)
        self.assertEqual(probability, 0.5)
        self.assertEqual(conditional.interval, portion.closed(0.5, 1))

    def test_conditional_from_singleton_event(self):
        event = Event({self.variable: portion.singleton(0.3)})
        conditional, probability = self.model.conditional(event)
        self.assertEqual(len(list(self.model.probabilistic_circuit.nodes)), 1)
        conditional_from_circuit = list(self.model.probabilistic_circuit.nodes)[0]
        self.assertEqual(conditional, conditional_from_circuit)
        self.assertEqual(probability, 1.)
        self.assertEqual(conditional.location, 0.3)

    def test_conditional_from_complex_event(self):
        interval = portion.closed(0., 0.2) | portion.closed(0.5, 1.) | portion.singleton(0.3)
        event = Event({self.variable: interval})
        self.model.conditional(event)
        self.assertEqual(len(list(self.model.probabilistic_circuit.nodes)), 4)
        self.assertIsInstance(self.model.probabilistic_circuit.root, DeterministicSumUnit)

    def test_conditional_with_none(self):
        event = Event({self.variable: 2})
        conditional, probability = self.model.conditional(event)
        self.assertEqual(len(list(self.model.probabilistic_circuit.nodes)), 0)
        self.assertEqual(conditional, None)



if __name__ == '__main__':
    unittest.main()
