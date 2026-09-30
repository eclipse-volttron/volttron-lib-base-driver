"""publish_poll and the device-scoped point set of DriverAgent. Runs without a platform."""
import logging

from types import SimpleNamespace
from unittest import mock

from volttron.driver.base.driver import DriverAgent

BESS = 'devices/PNNL/SEB/BESS'
METER = f'{BESS}/METER'


def _stub_remote():
    model = mock.Mock()
    model.get_node.side_effect = lambda topic: SimpleNamespace(meta_data={'units': 'V', 'topic': topic})
    return SimpleNamespace(vip=object(), equipment_model=model)


def _poll_set(**multi_depth):
    return SimpleNamespace(single_depth=set(), single_breadth=set(), multi_depth=multi_depth, multi_breadth={})


def test_multi_publish_skipped_when_no_values_for_that_device(caplog):
    """A poll set spanning a device and a device nested beneath it: only the device with values is published."""
    poll_set = _poll_set(**{BESS: {f'{BESS}/SOC', f'{BESS}/Power'}, METER: {f'{METER}/Volts AN', f'{METER}/Watts'}})
    results = {f'{BESS}/SOC': 55.0, f'{BESS}/Power': -12.5}    # The meter's points all failed.
    with mock.patch('volttron.driver.base.driver.publish_wrapper') as publish, caplog.at_level(logging.WARNING):
        DriverAgent.publish_poll(_stub_remote(), results, poll_set)
    assert publish.call_count == 1
    (_, topic), kwargs = publish.call_args
    assert topic == f'{BESS}/multi'
    assert kwargs['message'][0] == {'SOC': 55.0, 'Power': -12.5}
    assert set(kwargs['message'][1]) == {'SOC', 'Power'}
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings == [f'No values were returned for any of the 2 polled points of {METER}.'
                        f' Skipping the {METER}/multi publish.']


def test_partial_results_still_publish():
    poll_set = _poll_set(**{METER: {f'{METER}/Volts AN', f'{METER}/Watts'}})
    with mock.patch('volttron.driver.base.driver.publish_wrapper') as publish:
        DriverAgent.publish_poll(_stub_remote(), {f'{METER}/Watts': 1.0}, poll_set)
    assert publish.call_count == 1 and publish.call_args.kwargs['message'][0] == {'Watts': 1.0}


def test_breadth_multi_publish_skipped_when_empty(caplog):
    poll_set = _poll_set()
    poll_set.multi_breadth = {'devices/METER/BESS/SEB/PNNL': {f'{METER}/Watts'}}
    with mock.patch('volttron.driver.base.driver.publish_wrapper') as publish, caplog.at_level(logging.WARNING):
        DriverAgent.publish_poll(_stub_remote(), {}, poll_set)
    assert publish.call_count == 0 and 'Skipping the devices/METER/BESS/SEB/PNNL/multi publish' in caplog.text


def test_point_set_and_registration_use_only_the_devices_own_points():
    bess_points = [mock.Mock(identifier=f'{BESS}/SOC', config='soc-config')]
    model = mock.Mock()
    model.device_points.return_value = bess_points
    model.points.return_value = bess_points + [mock.Mock(identifier=f'{METER}/Watts', config='watts-config')]
    device_node = mock.Mock(identifier=BESS)
    remote = SimpleNamespace(equipment_model=model, equipment=set(), add_registers=mock.Mock())
    DriverAgent.add_equipment(remote, device_node)
    remote.add_registers.assert_called_once_with(['soc-config'], BESS)
    assert DriverAgent.point_set.fget(remote) == set(bess_points)
    model.points.assert_not_called()
