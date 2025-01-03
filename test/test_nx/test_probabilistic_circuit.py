import json
import os.path
import unittest

import numpy as np
from matplotlib import pyplot as plt
from random_events.interval import closed, SimpleInterval
from random_events.set import SetElement
from random_events.variable import Continuous

from probabilistic_model.distributions.uniform import UniformDistribution
from probabilistic_model.probabilistic_circuit.nx.probabilistic_circuit import *
#from probabilistic_model.probabilistic_circuit.nx.probabilistic_circuit import ProbabilisticCircuit, SumUnit, ProductUnit, SimpleEvent, ShallowProbabilisticCircuit
from probabilistic_model.probabilistic_circuit.nx.distributions import UnivariateContinuousLeaf
import plotly.graph_objects as go
from probabilistic_model.monte_carlo_estimator import MonteCarloEstimator

class SymbolEnum(SetElement):
    EMPTY_SET = -1
    A = 0
    B = 1
    C = 2

class SmallCircuitTestCast(unittest.TestCase):
    """
    Integration test for all classes in probabilistic circuits.
    """

    x = Continuous("x")
    y = Continuous("y")

    model: ProbabilisticCircuit

    def setUp(self):
        sum1, sum2, sum3 = SumUnit(), SumUnit(), SumUnit()
        sum4, sum5 = SumUnit(), SumUnit()
        prod1, prod2 = ProductUnit(), ProductUnit()

        sum1.add_subcircuit(prod1, 0.5)
        sum1.add_subcircuit(prod2, 0.5)
        prod1.add_subcircuit(sum2)
        prod1.add_subcircuit(sum4)
        prod2.add_subcircuit(sum3)
        prod2.add_subcircuit(sum5)

        d_x1 = UnivariateContinuousLeaf(UniformDistribution(self.x, SimpleInterval(0, 1)))
        d_x2 = UnivariateContinuousLeaf(UniformDistribution(self.x, SimpleInterval(2, 3)))
        d_y1 = UnivariateContinuousLeaf(UniformDistribution(self.y, SimpleInterval(0, 1)))
        d_y2 = UnivariateContinuousLeaf(UniformDistribution(self.y, SimpleInterval(3, 4)))

        sum2.add_subcircuit(d_x1, 0.8)
        sum2.add_subcircuit(d_x2, 0.2)
        sum3.add_subcircuit(d_x1, 0.7)
        sum3.add_subcircuit(d_x2, 0.3)

        sum4.add_subcircuit(d_y1, 0.5)
        sum4.add_subcircuit(d_y2, 0.5)
        sum5.add_subcircuit(d_y1, 0.1)
        sum5.add_subcircuit(d_y2, 0.9)

        self.model = sum1.probabilistic_circuit

    def test_sampling(self):
        samples = self.model.sample(100)
        unique = np.unique(samples, axis=0)
        self.assertGreater(len(unique), 95)

    def test_conditioning(self):
        event = SimpleEvent({self.x: closed(0, 0.25) | closed(0.5, 0.75)}).as_composite_set()
        conditional, prob = self.model.conditional(event)
        self.assertAlmostEqual(prob, 0.375)
        conditional.plot_structure()
        # plt.show()

    def test_plot(self):
        self.model.plot_structure()
        # plt.show()
        fig = go.Figure(self.model.plot(600, surface=True))
        # fig.show()



# class PyCRAMErrorTestCase(unittest.TestCase):
#
#     path = os.path.join(os.path.expanduser("~"), "Documents", "model.json")
#     with open(path, "r") as file:
#         model: ProbabilisticCircuit = ProbabilisticCircuit.from_json(json.load(file))
#
#     def test_error(self):
#         arm, grasp, rx, ry = self.model.variables
#         self.model.marginal([rx, ry])
#         print(self.model.variables)
#
#


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
        from src.probabilistic_model.probabilistic_circuit.exporter.draw_io_expoter import DrawIoExporter
        diagram = DrawIoExporter(shallow_pc).export()
        diagram.dump_file("test.drawio")
        self.assertTrue(True)


class L1MetricTestCase(unittest.TestCase):

    x = Continuous("x")
    y = Continuous("y")
    standard_circuit = ProductUnit()

    standard_circuit.add_subcircuit(LeafUnit(distribution=UniformDistribution(x, SimpleInterval(0, 1))))
    standard_circuit.add_subcircuit(LeafUnit(distribution=UniformDistribution(y, SimpleInterval(0, 1))))
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


    def test_jpt_l1(self):
        result = self.shallow_1.l1(self.shallow_2)

        p_event_by_hand = self.event_2
        q_event_by_hand = self.event_1
        self.assertEqual(self.circuit_2.probability(p_event_by_hand.as_composite_set()), 0)
        self.assertEqual(self.circuit_1.probability(q_event_by_hand.as_composite_set()), 0)
        result_by_hand = self.circuit_1.probability(p_event_by_hand.as_composite_set()) + self.circuit_2.probability(
            q_event_by_hand.as_composite_set())
        self.assertAlmostEqual(result, result_by_hand, 4)

    def test_jpt_l1_same_input(self):
        result = self.shallow_1.l1(self.shallow_1)
        self.assertEqual(result, 0)

    def test_jpt_l1_disjunct_input(self):


        result = self.shallow_3.l1(self.shallow_4)

        self.assertEqual(result, 2)

    def test_l1_mc(self):
        mc_esti = MonteCarloEstimator(sample_size=1000, model=self.circuit_1)
        result = mc_esti.l1(self.circuit_2)
        self.assertAlmostEqual(result/2, 0.13333333333333336, delta=0.1)

if __name__ == '__main__':
    unittest.main()
