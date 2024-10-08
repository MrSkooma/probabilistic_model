import os
import unittest

from typing_extensions import List

from probabilistic_model.learning.jpt.jpt import JPT
from probabilistic_model.learning.jpt.variables import infer_variables_from_dataframe
from sklearn.datasets import load_breast_cancer
import pandas as pd
from random_events.variable import Variable

from probabilistic_model.probabilistic_circuit.exporter.draw_io_expoter import DrawIoExporter



class MyTestCase(unittest.TestCase):

    dataset: pd.DataFrame
    variables: List[Variable]
    model: JPT

    @classmethod
    def setUpClass(cls):
        data = load_breast_cancer(as_frame=True)

        df = data.data
        target = data.target
        target[target == 1] = "malignant"
        target[target == 0] = "friendly"
        df["malignant"] = target
        cls.dataset = df

        variables = infer_variables_from_dataframe(df, min_likelihood_improvement=1)

        model = JPT(variables, min_samples_leaf=0.9)
        model.fit(df)
        cls.model = model

    def test_export_to_drawio(self):
        diagram = DrawIoExporter(self.model.probabilistic_circuit).export()
        diagram.dump_file("test.drawio")

    # def test_networkx_plot(self):
    #     diagram = self.model.probabilistic_circuit.plot()


if __name__ == '__main__':
    unittest.main()



