import math
import unittest

import numpy as np
import torch
from numpy.testing import assert_almost_equal
from random_events.interval import SimpleInterval, closed
from random_events.product_algebra import SimpleEvent
from random_events.variable import Continuous
from torch.testing import assert_close

from probabilistic_model.learning.torch.uniform_layer import UniformLayer
from probabilistic_model.learning.torch.pc import SumLayer, ProductLayer
from probabilistic_model.probabilistic_circuit.distributions import UniformDistribution
from probabilistic_model.probabilistic_circuit.probabilistic_circuit import SumUnit, ProductUnit


class SumTestCase(unittest.TestCase):
    x = Continuous("x")
    p1_x = UniformLayer(x, torch.Tensor([[0, 1]]))
    p2_x = UniformLayer(x, torch.Tensor([[1, 3], [1, 1.5]]))
    s1 = SumLayer([p1_x, p2_x], log_weights=[torch.tensor([[math.log(2)], [1]]), torch.tensor([[0, 0], [1, 1]])])

    p1_x_by_hand = UniformDistribution(x, SimpleInterval(0, 1))
    p2_x_by_hand = UniformDistribution(x, SimpleInterval(1, 3))
    p3_x_by_hand = UniformDistribution(x, SimpleInterval(1, 1.5))
    s1_by_hand = SumUnit()
    s1_by_hand.add_subcircuit(p1_x_by_hand, 1 / 2)
    s1_by_hand.add_subcircuit(p2_x_by_hand, 1 / 4)
    s1_by_hand.add_subcircuit(p3_x_by_hand, 1 / 4)

    s2_by_hand = SumUnit()
    s2_by_hand.probabilistic_circuit = s1_by_hand.probabilistic_circuit
    s2_by_hand.add_subcircuit(p1_x_by_hand, 1 / 3)
    s2_by_hand.add_subcircuit(p2_x_by_hand, 1 / 3)
    s2_by_hand.add_subcircuit(p3_x_by_hand, 1 / 3)

    def test_stack(self):
        self.assertEqual(self.s1.concatenated_weights.shape, (2, 3))

    def test_normalizing_constant(self):
        assert_close(self.s1.log_normalization_constants,
                     torch.tensor([torch.log(torch.tensor(4.)), torch.log(torch.exp(torch.tensor(1)) * 3)]))

    def test_log_likelihood(self):
        input = torch.tensor([0.5, 1.5, 2.5]).reshape(-1, 1)

        p_by_hand_1 = self.s1_by_hand.log_likelihood(input)
        p_by_hand_2 = self.s2_by_hand.log_likelihood(input)

        self.assertEqual(input.shape, (3, 1))

        ll = self.s1.log_likelihood(input)
        self.assertEqual(ll.shape, (3, 2))
        assert_almost_equal(p_by_hand_1.tolist(), ll[:, 0].tolist())
        assert_almost_equal(p_by_hand_2.tolist(), ll[:, 1].tolist())

    def test_probability(self):
        event = SimpleEvent({self.x: closed(0.5, 2.5) | closed(3, 5)})
        prob = self.s1.probability_of_simple_event(event)
        self.assertEqual(prob.shape, (2, 1))
        p_by_hand_1 = self.s1_by_hand.probability_of_simple_event(event)
        p_by_hand_2 = self.s2_by_hand.probability_of_simple_event(event)
        assert_almost_equal([p_by_hand_1, p_by_hand_2], prob[:, 0].tolist())



class ProductTestCase(unittest.TestCase):
    x = Continuous("x")
    y = Continuous("y")
    p1_x_by_hand = UniformDistribution(x, SimpleInterval(0, 1))
    p1_y_by_hand = UniformDistribution(y, SimpleInterval(0.5, 1))
    p2_y_by_hand = UniformDistribution(y, SimpleInterval(5, 6))

    product_1 = ProductUnit()
    product_1.add_subcircuit(p1_x_by_hand)
    product_1.add_subcircuit(p1_y_by_hand)

    product_2 = ProductUnit()
    product_2.probabilistic_circuit = product_1.probabilistic_circuit
    product_2.add_subcircuit(p1_x_by_hand)
    product_2.add_subcircuit(p2_y_by_hand)

    p1_x = UniformLayer(x, torch.Tensor([[0, 1]]))
    p1_y = UniformLayer(y, torch.Tensor([[0.5, 1], [5, 6]]))

    product = ProductLayer(child_layers=[p1_x, p1_y], edges=[torch.tensor([0, 0]), torch.tensor([0, 1])])

    def test_log_likelihood(self):
        data = [[0.5, 0.75], [0.9, 0.7], [0.5, 5.5]]
        ll_p1_by_hand = self.product_1.log_likelihood(np.array(data))
        ll_p2_by_hand = self.product_2.log_likelihood(np.array(data))
        ll = self.product.log_likelihood(torch.tensor(data))
        self.assertEqual(ll.shape, (3, 2))
        assert_almost_equal(ll_p1_by_hand.tolist(), ll[:, 0].tolist())
        assert_almost_equal(ll_p2_by_hand.tolist(), ll[:, 1].tolist())

    def test_probability(self):
        event = SimpleEvent({self.x: closed(0.5, 2.5) | closed(3, 5),
                             self.y: closed(0.5, 2.5) | closed(3, 5)})
        prob = self.product.probability_of_simple_event(event)
        self.assertEqual(prob.shape, (2, 1))
        p_by_hand_1 = self.product_1.probability_of_simple_event(event)
        p_by_hand_2 = self.product_2.probability_of_simple_event(event)
        assert_almost_equal([p_by_hand_1, p_by_hand_2], prob[:, 0].tolist())


if __name__ == '__main__':
    unittest.main()
