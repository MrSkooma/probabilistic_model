import math
import unittest

import jax
import jax.numpy as jnp
from random_events.interval import SimpleInterval, Bound

from probabilistic_model.probabilistic_circuit.jax import simple_interval_to_open_array
from probabilistic_model.probabilistic_circuit.jax.uniform_layer import UniformLayer
import equinox as eqx


class UniformLayerTestCaste(unittest.TestCase):
    p_x = UniformLayer(0, jnp.array([[0, 1], [1, 3]]))
    key = jax.random.PRNGKey(69)

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

    def test_sampling(self):

        samples = self.p_x.sample_from_frequencies(jnp.array([20, 10]), self.key)
        self.assertEqual(samples.shape, (2, 20, 1))
        samples = samples.data
        self.assertEqual(samples.shape, (30, 1))
        samples_n0 = samples[:20]
        samples_n1 = samples[20:30]

        l_n0 = self.p_x.log_likelihood_of_nodes(samples_n0)[:, 0]
        l_n1 = self.p_x.log_likelihood_of_nodes(samples_n1)[:, 1]

        self.assertTrue(all(l_n0 > -jnp.inf))
        self.assertTrue(all(l_n1 > -jnp.inf))