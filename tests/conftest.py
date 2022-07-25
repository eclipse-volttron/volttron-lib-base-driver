"""Tests suite for `platform_driver_agent`."""
from pathlib import Path

import pytest

from volttron.driver.base.interfaces import BaseInterface

TESTS_DIR = Path(__file__).parent
TMP_DIR = TESTS_DIR / "tmp"
FIXTURES_DIR = TESTS_DIR / "fixtures"
"""Configuration for the pytest test suite."""


@pytest.fixture()
def generic_test_interface():

    class GenericTestInterface(BaseInterface):

        def __init__(self, **kwargs):
            super(GenericTestInterface, self).__init__(**kwargs)

        def configure(self, config_dict, registry_config_str):
            return

        def get_point(self, point_name, get_priority_array=False):
            return

        def set_point(self, point_name, value, priority=None):
            return

        def scrape_all(self):
            return

        def revert_all(self, priority=None):
            return

        def revert_point(self, point_name, priority=None):
            return

    yield GenericTestInterface()
