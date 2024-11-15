import unittest

import jax
from jax.experimental.sparse import BCOO
from random_events.variable import Continuous
import jax.numpy as jnp
from probabilistic_model.probabilistic_circuit.jax.input_layer import DiracDeltaLayer
from probabilistic_model.probabilistic_circuit.jax.inner_layer import ProductLayer


class DiracProductTestCase(unittest.TestCase):

    p1_x = DiracDeltaLayer(0, jnp.array([0., 1.]), jnp.array([1, 1]))
    p2_x = DiracDeltaLayer(0, jnp.array([2., 3.]), jnp.array([1, 1]))
    p_y = DiracDeltaLayer(1, jnp.array([4., 5.]), jnp.array([1, 1]))
    p_z = DiracDeltaLayer(2, jnp.array([6.]), jnp.array([1]))

    indices = jnp.array([[1, 2, 3, 3, 0, 0],
                            [0, 1, 0, 1, 0, 1]]).T
    values = jnp.array([0, 0, 1, 0, 0, 0])
    edges = BCOO((values, indices), shape=(4, 2))

    product_layer = ProductLayer([p_z, p1_x, p2_x, p_y, ], edges)

    def test_variables(self):
        self.assertTrue(jnp.allclose(self.product_layer.variables, jnp.array([0, 1, 2])))

    def test_likelihood(self):
        data = jnp.array([[0., 5., 6.],
                             [2, 4, 6]])
        likelihood = self.product_layer.log_likelihood_of_nodes(data)
        self.assertTrue(likelihood[0, 0] > -jnp.inf)
        self.assertTrue(likelihood[1, 1] > -jnp.inf)
        self.assertTrue(likelihood[0, 1] == -jnp.inf)
        self.assertTrue(likelihood[1, 0] == -jnp.inf)

    def test_sample_from_frequencies(self):
        frequencies = jnp.array([5, 3])
        samples = self.product_layer.sample_from_frequencies(frequencies, jax.random.PRNGKey(69))

        samples_n0 = samples[0].todense()
        samples_n1 = samples[1].todense()

        self.assertEqual(samples_n0.shape, (5, 3))
        self.assertEqual(samples_n1.shape, (5, 3))
        self.assertEqual(len(samples[1].data), 3)
        self.assertTrue(jnp.all(samples_n0 == jnp.array([0, 5 ,6])))
        self.assertTrue(jnp.all(samples_n1[:3] == jnp.array([2, 4 ,6])))


if __name__ == '__main__':
    unittest.main()
