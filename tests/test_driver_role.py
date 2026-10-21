"""driver_role and remote_writable in the base configuration, and interface lookup preferring the module's own class."""
import sys
from types import ModuleType

import pytest

from volttron.driver.base.config import PointConfig, RemoteConfig
from volttron.driver.base.interfaces import BaseInterface


@pytest.mark.parametrize('given, expected', [(None, 'client'), ('', 'client'), ('Server', 'server'),
                                             (' OUTSTATION ', 'outstation'), ('client', 'client')])
def test_driver_role_defaults_to_client_and_is_normalized(given, expected):
    kwargs = {} if given is None else {'driver_role': given}
    assert RemoteConfig(driver_type='x', **kwargs).driver_role == expected


def test_remote_writable_is_optional_and_aliased():
    assert PointConfig(volttron_point_name='p').remote_writable is None
    assert PointConfig(**{'Volttron Point Name': 'p', 'Remote Writable': ''}).remote_writable is None
    assert PointConfig(**{'Volttron Point Name': 'p', 'Remote Writable': 'TRUE'}).remote_writable is True
    assert PointConfig(volttron_point_name='p', remote_writable=False).model_dump()['remote_writable'] is False


def test_interface_lookup_prefers_the_class_the_module_defines(monkeypatch):
    class Helper(BaseInterface):                    # imported into the module, alphabetically first
        pass
    module = ModuleType('volttron.driver.interfaces.zz.zz')

    class Zz(BaseInterface):
        pass
    Zz.__module__ = module.__name__
    module.Helper, module.Zz = Helper, Zz
    monkeypatch.setitem(sys.modules, module.__name__, module)
    assert BaseInterface.get_interface_subclass('zz') is Zz
    assert BaseInterface.get_interface_subclass('zz', module=module.__name__) is Zz
    del module.Zz
    assert BaseInterface.get_interface_subclass('zz') is Helper        # nothing of its own: first subclass found
