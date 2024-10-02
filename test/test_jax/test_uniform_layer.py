import math
import unittest

import jax.numpy as jnp
from random_events.interval import SimpleInterval, Bound

from probabilistic_model.probabilistic_circuit.jax import simple_interval_to_open_array
from probabilistic_model.probabilistic_circuit.jax.uniform_layer import UniformLayer


class UniformLayerTestCaste(unittest.TestCase):
    p_x = UniformLayer(0, jnp.array([[0, 1], [1, 3]]))

    def test_log_likelihood(self):
        data = jnp.array([0.5, 1.5, 4]).reshape(-1, 1)
        ll = self.p_x.log_likelihood_of_nodes(data)
        self.assertEqual(ll.shape, (3, 2))
        result = [[0., -float("inf")], [-float("inf"), -math.log(2)], [-float("inf"), -float("inf")]]
        self.assertTrue(jnp.allclose(ll, jnp.array(result)))

    def test_from_interval(self):
        ioo = SimpleInterval(0, 1)
        ioc = SimpleInterval(0, 1, right=Bound.CLOSED)
        ico = SimpleInterval(0, 1, left=Bound.CLOSED)
        icc = SimpleInterval(0, 1, left=Bound.CLOSED, right=Bound.CLOSED)

        intervals = jnp.vstack([simple_interval_to_open_array(i) for i in [ioo, ioc, ico, icc]])
        p_x = UniformLayer(0, intervals)

        data = jnp.array([[0], [1]])
        ll = jnp.exp(p_x.log_likelihood_of_nodes(data))
        result = jnp.array([[0, 0, 1, 1], [0, 1, 0, 1]])
        self.assertTrue(jnp.allclose(ll, result))
