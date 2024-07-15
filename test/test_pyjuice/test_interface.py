import unittest

import numpy as np
import torch
from random_events.variable import Continuous

from probabilistic_model.learning.nyga_distribution import NygaDistribution
from probabilistic_model.probabilistic_circuit.probabilistic_circuit import SumUnit
from probabilistic_model.probabilistic_circuit.distributions.distributions import GaussianDistribution
import plotly.graph_objects as go
from probabilistic_model.learning.converter import TensorProbabilisticCircuit


class InterfaceTestCase(unittest.TestCase):

    x: Continuous = Continuous("x")
    model: SumUnit

    def setUp(self) -> None:
        model = NygaDistribution(self.x, min_likelihood_improvement=0.001, min_samples_per_quantile=300)
        data = np.random.normal(0, 1, 1000).tolist()
        model.fit(data)

        self.model = SumUnit()

        for weight, subcircuit in model.weighted_subcircuits:
            mean = subcircuit.expectation()[self.x]
            variance = subcircuit.variance()[self.x]
            normal_child = GaussianDistribution(self.x, mean, variance**0.5)
            self.model.add_subcircuit(normal_child, weight)

    def show(self):
        fig = go.Figure(self.model.plot())
        fig.show()

    def test_something(self):
        # self.show()
        result = TensorProbabilisticCircuit.from_pc(self.model.probabilistic_circuit)
        data = self.model.sample(1000)
        torch_data = torch.tensor(data)
        device = torch.device("cuda:0")
        result.tensor_circuit.to(device)
        ll = result.tensor_circuit(torch_data)
        print(ll)


if __name__ == '__main__':
    unittest.main()
