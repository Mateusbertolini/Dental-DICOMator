import importlib.util
import sys
import types
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType("dental_dicomator")
package.__path__ = [str(ROOT)]
sys.modules["dental_dicomator"] = package

constants = types.ModuleType("dental_dicomator.constants")
constants.MIN_HU_VALUE = -1024
constants.MAX_HU_VALUE = 4095
sys.modules["dental_dicomator.constants"] = constants

spec = importlib.util.spec_from_file_location(
    "dental_dicomator.dental", ROOT / "dental.py"
)
dental = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = dental
spec.loader.exec_module(dental)


def test_cortical_and_cancellous_values_without_background():
    depth = np.array([0.0, 0.5, 1.5, 2.0, 2.25, 3.0, 8.0])
    values = dental.layered_bone_values_from_depth(
        depth, 2.0, 0.5, 800.0, 350.0
    )
    assert values[0] == 800
    assert values[-1] == 350
    assert np.all(values >= 350)
    assert np.all(values <= 800)
    assert not np.any(values == -1000)


def test_zero_depth_is_uniform_cancellous():
    values = dental.layered_bone_values_from_depth(
        np.array([0.1, 1.0, 5.0]), 0.0, 0.0, 800.0, 350.0
    )
    np.testing.assert_array_equal(values, np.array([350, 350, 350], dtype=np.int16))


def test_textured_path_preserves_filled_value_count():
    depth = np.linspace(0.0, 10.0, 101)
    values = dental.textured_bone_values(
        depth, np.zeros(101), np.zeros(101), np.arange(101),
        2.0, 0.5, 800.0, 350.0, 0.4, 0.0,
    )
    assert values.shape == depth.shape
    assert np.count_nonzero(values > -1000) == depth.size
