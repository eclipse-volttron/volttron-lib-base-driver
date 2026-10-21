"""publish_push: pushed values reach only the points of this remote, and one bad topic never spoils the batch."""
import logging

from types import SimpleNamespace
from unittest import mock

from volttron.driver.base.driver import DriverAgent

BESS = 'devices/PNNL/SEB/BESS'


def _point(topic, active=True):
    return SimpleNamespace(identifier=topic, is_point=True, meta_data={'units': 'V'}, last_value=None, active=active)


def _world():
    """A remote with two points, a device node, a point owned by another remote and nothing else."""
    me, other = SimpleNamespace(unique_id='me', vip=object()), SimpleNamespace(unique_id='other')
    nodes = {f'{BESS}/SOC': _point(f'{BESS}/SOC'), f'{BESS}/Power': _point(f'{BESS}/Power'),
             BESS: SimpleNamespace(identifier=BESS, is_point=False, meta_data={}),
             'devices/X/P': _point('devices/X/P')}
    owners = {f'{BESS}/SOC': me, f'{BESS}/Power': me, 'devices/X/P': other}
    model = mock.Mock()
    model.get_node.side_effect = lambda t: nodes.get(t)
    model.get_remote.side_effect = lambda t: owners[t]
    model.get_point_topics.side_effect = lambda t: (t, 'breadth/' + t)
    model.get_device_topics.side_effect = lambda t: (BESS, 'breadth/' + BESS)
    model.is_active.return_value = True
    model.is_published_single_depth.return_value = True
    model.is_published_single_breadth.return_value = False
    model.is_published_multi_depth.return_value = True
    model.is_published_multi_breadth.return_value = False
    me.equipment_model = model
    return me, nodes, model


def test_only_this_remotes_points_are_published(caplog):
    me, nodes, model = _world()
    pushed = {f'{BESS}/SOC': 55.0, 'devices/nowhere/Q': 1, BESS: 2, 'devices/X/P': 3, f'{BESS}/Power': -12.5}
    with mock.patch('volttron.driver.base.driver.publish_wrapper') as publish, caplog.at_level(logging.WARNING):
        DriverAgent.publish_push(me, pushed)
    single = [c.args[1] for c in publish.call_args_list if not c.args[1].endswith('/multi')]
    assert single == [f'{BESS}/SOC', f'{BESS}/Power']
    multi = [c for c in publish.call_args_list if c.args[1].endswith('/multi')]
    assert len(multi) == 1 and multi[0].args[3][0] == {'SOC': 55.0, 'Power': -12.5}
    assert nodes[f'{BESS}/SOC'].last_value == 55.0 and nodes['devices/X/P'].last_value is None
    warnings = [r.message for r in caplog.records if r.levelno == logging.WARNING]
    assert any("'devices/nowhere/Q', which is not a point" in w for w in warnings)
    assert any(f"'{BESS}', which is not a point" in w for w in warnings)
    assert any("'devices/X/P', a point of another remote" in w for w in warnings)
    assert len(warnings) == 3


def test_a_failing_topic_does_not_abort_the_batch(caplog):
    me, nodes, model = _world()
    model.is_published_single_depth.side_effect = lambda t: (_ for _ in ()).throw(RuntimeError('boom')) if t.endswith('SOC') else True
    with mock.patch('volttron.driver.base.driver.publish_wrapper') as publish, caplog.at_level(logging.WARNING):
        DriverAgent.publish_push(me, {f'{BESS}/SOC': 1, f'{BESS}/Power': 2})
    assert [c.args[1] for c in publish.call_args_list] == [f'{BESS}/Power', f'{BESS}/multi']
    assert 'unable to publish a pushed value' in caplog.text and 'boom' in caplog.text


def test_inactive_point_is_published_but_not_stored():
    me, nodes, model = _world()
    model.is_active.return_value = False
    with mock.patch('volttron.driver.base.driver.publish_wrapper') as publish:
        DriverAgent.publish_push(me, {f'{BESS}/SOC': 9})
    assert nodes[f'{BESS}/SOC'].last_value is None and publish.call_count == 2


def test_stored_values_are_recorded_when_the_model_offers_it(caplog):
    me, nodes, model = _world()
    inactive = nodes[f'{BESS}/Power']
    model.is_active.side_effect = lambda t: not t.endswith('Power')
    with mock.patch('volttron.driver.base.driver.publish_wrapper'):
        DriverAgent.publish_push(me, {f'{BESS}/SOC': 1, f'{BESS}/Power': 2})
    model.record_pushed_value.assert_called_once_with(nodes[f'{BESS}/SOC'])      # stored points only, not inactive ones
    del model.record_pushed_value
    with mock.patch('volttron.driver.base.driver.publish_wrapper'):
        DriverAgent.publish_push(me, {f'{BESS}/SOC': 3})                           # a model without the hook is fine
    assert nodes[f'{BESS}/SOC'].last_value == 3
