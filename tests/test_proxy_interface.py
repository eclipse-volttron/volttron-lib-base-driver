"""ProxyBackedInterface through a toy protocol: the manager wiring, registration, pushes, batching and every failure mode."""
import logging

from types import SimpleNamespace

import pytest

from gevent import Timeout
from pydantic import Field

from volttron.driver.base.config import PointConfig, RemoteConfig
from volttron.driver.base.interfaces import BaseInterface, BaseRegister, BasicRevert, DriverInterfaceError
from volttron.driver.base.proxy_interface import NOT_CONFIGURED, READ_ONLY, PointError, ProxyBackedInterface
from volttron.driver.base.testing import FakePPM, build_interface, serialized


class ToyPointConfig(PointConfig):
    address: int = Field(validation_alias='address')


class ToyRemoteConfig(RemoteConfig):
    host: str
    registration_timeout: float = 30.0
    reply_timeout: float | None = None
    proxy_group: str | None = None

    @property
    def resolved_reply_timeout(self) -> float:
        return self.reply_timeout if self.reply_timeout is not None else 30.0

    def proxy_key(self) -> tuple:
        return ('toy',) if self.proxy_group is None else ('toy', self.proxy_group)

    def identity_fields(self) -> dict:
        return {'host': self.host}


class ToyRegister(BaseRegister):
    def __init__(self, point: ToyPointConfig):
        super().__init__('byte', not point.writable, point.volttron_point_name, point.units)
        self.address = point.address
        self.python_type = float

    def point_fields(self, topic):
        return {'topic': topic, 'address': self.address}


class Toy(ProxyBackedInterface, BasicRevert, BaseInterface):
    REGISTER_CONFIG_CLASS, INTERFACE_CONFIG_CLASS = ToyPointConfig, ToyRemoteConfig
    PROXY_NAME, PROXY_LABEL = 'toy', 'Toy Proxy'
    REGISTER_METHOD, READ_METHOD, WRITE_METHOD, PUSH_METHOD = 'REGISTER_TOY', 'READ_TOY', 'WRITE_TOY', 'RECEIVE_TOY'
    REQUEST_ERROR_KEY = 'link'

    def __init__(self, config, *args, **kwargs):
        BaseInterface.__init__(self, config, *args, **kwargs)
        BasicRevert.__init__(self, **kwargs)
        self.registered = []
        self.init_proxy()

    def create_register(self, definition):
        return ToyRegister(definition)

    def read_result(self, register, entry):
        if isinstance(entry, dict):
            if not entry.get('online', True):
                raise PointError('point offline')
            return float(entry['value'])
        return float(entry)

    def coerce(self, register, value):
        return float(value)

    def after_registration(self, result, initial_setup):
        self.registered.append((result, initial_setup))


class Batched(Toy):
    """Two topics per read request, one topic per write request, like BACnet's batch reads and single writes."""
    def split_reads(self, topics, **kwargs):
        return [(self.read_payload(topics[i:i + 2], **kwargs), topics[i:i + 2]) for i in range(0, len(topics), 2)]

    def split_writes(self, items, **kwargs):
        return [({'topic': t, 'value': v, **kwargs}, [(t, v)]) for t, v in items]


def point(name, address, writable=False):
    return ToyPointConfig(volttron_point_name=name, address=address, writable=writable, units='')


POINTS = [point('a', 1), point('b', 2), point('c', 3, writable=True), point('d', 4, writable=True)]
T = 'campus/building/device/{}'.format


@pytest.fixture
def ppm():
    return FakePPM()


@pytest.fixture
def toy(ppm):
    return build_interface(Toy, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm, points=POINTS, peer_ready=True)


class TestWiring:
    def test_constructor_attaches_to_the_shared_manager(self, ppm):
        toy = build_interface(Toy, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm)
        assert toy.ppm is ppm and ppm.started == 1 and 'RECEIVE_TOY' in ppm.callbacks and toy.proxy_peer is None
        assert ppm.remote_callbacks == {('RECEIVE_TOY', toy.remote_id): toy.receive_push}
        other = build_interface(Toy, {'driver_type': 'toy', 'host': 'h2'}, ppm=ppm)
        assert other.remote_id != toy.remote_id and ppm.callbacks['RECEIVE_TOY'] == toy.receive_push   # fallback: first
        assert ppm.remote_callbacks[('RECEIVE_TOY', other.remote_id)] == other.receive_push
        toy.driver_agent.core.spawn.assert_called_once_with(ppm.select_loop)
        assert toy.proxy_label == 'Toy Proxy'

    def test_no_push_method_registers_no_callback(self, ppm):
        class Quiet(Toy):
            PUSH_METHOD = None
        build_interface(Quiet, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm)
        assert ppm.callbacks == {}

    def test_finalize_setup_registers_the_remote(self, ppm):
        toy = build_interface(Toy, {'driver_type': 'toy', 'host': 'h', 'proxy_group': 'site'}, ppm=ppm, points=POINTS)
        ppm.queue(serialized({'client': 'h', 'points': 4}))
        toy.finalize_setup(initial_setup=True)
        assert ppm.launch == (('toy', 'site'), {}) and ppm.registration_waits == [30.0] and toy.proxy_peer is ppm.peer
        [(method, payload, expects_reply)] = ppm.sent
        assert method == 'REGISTER_TOY' and expects_reply
        assert payload == {'host': 'h', 'remote_id': toy.remote_id.hex,
                           'points': [{'topic': T(n), 'address': a} for n, a in (('a', 1), ('b', 2), ('c', 3), ('d', 4))]}
        assert toy.registered == [({'client': 'h', 'points': 4}, True)]
        assert ppm.messages[-1].remote_id == toy.remote_id and ppm.messages[-1].protocol_version == 2   # stamped request

    def test_registration_failure_is_logged_and_skips_post_setup(self, ppm, caplog):
        toy = build_interface(Toy, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm)
        ppm.queue(serialized({}, {'link': 'refused'}))
        with caplog.at_level(logging.WARNING):
            toy.finalize_setup()
        assert 'refused' in caplog.text and toy.registered == []

    def test_without_register_method_the_post_setup_hook_still_runs(self, ppm):
        class Unregistered(Toy):
            REGISTER_METHOD = None

            def proxy_launch_options(self):
                return {'port': 47808}
        toy = build_interface(Unregistered, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm)
        toy.finalize_setup(initial_setup=True)
        assert ppm.sent == [] and ppm.launch == (('toy',), {'port': 47808}) and toy.registered == [({}, True)]


class TestTreeValues:
    def test_without_an_equipment_model_there_are_no_values(self, toy):
        assert toy.tree_values() == {}

    def test_values_of_updated_points_only(self, toy):
        nodes = {T('a'): SimpleNamespace(last_value=1.5, last_updated=object()),
                 T('b'): SimpleNamespace(last_value=None, last_updated=None)}       # never updated
        toy.driver_agent.equipment_model = SimpleNamespace(get_node=lambda topic: nodes.get(topic))
        assert toy.tree_values() == {T('a'): 1.5}


class TestRecovery:
    @pytest.fixture(autouse=True)
    def instant(self, monkeypatch):
        monkeypatch.setattr('volttron.driver.base.proxy_interface.sleep', lambda s: None)

    @staticmethod
    def run_spawned(toy):
        """The interface hands the delayed recovery to core.spawn; run what it spawned."""
        (fn, *args), _ = toy.driver_agent.core.spawn.call_args
        toy.driver_agent.core.spawn.reset_mock()
        fn(*args)

    def test_losing_our_proxy_sets_up_again_with_a_delay(self, ppm, caplog):
        toy = build_interface(Toy, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm, points=POINTS)
        toy.finalize_setup(initial_setup=True)
        toy.driver_agent.core.spawn.reset_mock()
        with caplog.at_level(logging.WARNING):
            old = ppm.lose_peer('process exited with code 9')
        assert toy.proxy_peer is None and 'exited with code 9' in caplog.text and 'in 1 s' in caplog.text
        toy.driver_agent.core.spawn.assert_called_once_with(toy._recover_proxy, 1.0)
        self.run_spawned(toy)
        assert toy.proxy_peer is ppm.peer and toy.proxy_peer is not old
        assert ppm.methods() == ['REGISTER_TOY', 'REGISTER_TOY'] and toy.registered[-1] == ({}, False)
        assert toy._recovery_attempts == 0                                     # success resets the backoff

    def test_consecutive_losses_back_off_until_registration_succeeds(self, ppm):
        toy = build_interface(Toy, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm)
        toy.finalize_setup()
        toy.driver_agent.core.spawn.reset_mock()
        delays = []
        for _ in range(7):
            ppm.queue(serialized({}, {'link': 'refused'}))                     # registration keeps failing
            ppm.lose_peer()
            delays.append(toy.driver_agent.core.spawn.call_args[0][1])
            self.run_spawned(toy)
        assert delays == [1.0, 2.0, 5.0, 10.0, 30.0, 30.0, 30.0]
        ppm.lose_peer()
        self.run_spawned(toy)                                                  # default reply: success
        assert toy._recovery_attempts == 0

    def test_another_proxys_loss_is_ignored(self, toy):
        toy.driver_agent.core.spawn.reset_mock()
        toy._proxy_peer_lost(object(), 'not ours')
        assert toy.proxy_peer is not None and toy.driver_agent.core.spawn.call_count == 0

    def test_recovery_is_skipped_if_already_set_up_again(self, ppm):
        toy = build_interface(Toy, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm)
        toy.finalize_setup()
        ppm.lose_peer()
        toy.finalize_setup()                                                   # e.g. a configuration update
        sent = len(ppm.sent)
        self.run_spawned(toy)
        assert len(ppm.sent) == sent


class TestPush:
    def test_pushed_values_are_published_by_topic(self, toy):
        toy.receive_push.__wrapped__(toy, None, serialized({T('a'): 1.5}))
        toy.driver_agent.publish_push.assert_called_once_with({T('a'): 1.5})

    def test_foreign_topics_are_dropped_with_a_warning(self, toy, caplog):
        with caplog.at_level(logging.WARNING):
            toy.receive_push.__wrapped__(toy, None, serialized({T('a'): 1.5, 'elsewhere/x': 2, T('nope'): 3}))
        toy.driver_agent.publish_push.assert_called_once_with({T('a'): 1.5})
        assert 'does not serve' in caplog.text and 'elsewhere/x' in caplog.text
        toy.driver_agent.publish_push.reset_mock()
        with caplog.at_level(logging.WARNING):
            toy.receive_push.__wrapped__(toy, None, serialized({'elsewhere/x': 2}))
        toy.driver_agent.publish_push.assert_not_called()                       # nothing of ours: nothing published

    def test_handle_pushed_hook_sees_instance_state(self, ppm):
        class Scaling(Toy):
            def handle_pushed(self, values):
                self.driver_agent.publish_push({t: v * 10 for t, v in values.items() if t in self.point_map})
        toy = build_interface(Scaling, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm, points=POINTS)
        toy.receive_push.__wrapped__(toy, None, serialized({T('a'): 1.5, 'elsewhere/x': 2}))
        toy.driver_agent.publish_push.assert_called_once_with({T('a'): 15.0})

    def test_errors_logged_and_garbage_ignored(self, toy, caplog):
        with caplog.at_level(logging.WARNING):
            toy.receive_push.__wrapped__(toy, None, serialized({}, {'link': 'lost'}))
            toy.receive_push.__wrapped__(toy, None, b'not json')
            toy.receive_push.__wrapped__(toy, None, b'[1, 2]')
        assert 'lost' in caplog.text and 'Undecodable' in caplog.text and 'Unexpected' in caplog.text
        toy.driver_agent.publish_push.assert_not_called()


class TestReads:
    def test_default_read_maps_entries_and_reports_the_rest(self, toy, ppm):
        ppm.queue(serialized({T('a'): {'value': 1, 'online': True}, T('b'): {'value': 2, 'online': False}},
                             {T('c'): 'not reported'}))
        results, errors = toy.get_multiple_points([T('a'), T('b'), T('c'), T('d'), T('nope')])
        assert results == {T('a'): 1.0}
        assert errors == {T('b'): 'point offline', T('c'): 'not reported', T('d'): 'No value returned by the Toy Proxy.',
                          T('nope'): NOT_CONFIGURED}
        assert ppm.payloads('READ_TOY') == [{'topics': [T('a'), T('b'), T('c'), T('d')]}]
        assert all(m.remote_id == toy.remote_id for m in ppm.messages)             # the header names the remote

    def test_request_level_error_key(self, toy, ppm):
        ppm.queue(serialized({}, {'link': 'connection refused'}))
        _, errors = toy.get_multiple_points([T('a'), T('b')])
        assert errors == {T('a'): 'connection refused', T('b'): 'connection refused'}

    def test_get_point_raises_with_the_reason(self, toy, ppm):
        ppm.queue(serialized({T('a'): 7}))
        assert toy.get_point(T('a')) == 7.0
        ppm.queue(serialized({}))
        with pytest.raises(RuntimeError, match='No value returned'):
            toy.get_point(T('a'))

    def test_failure_modes(self, toy, ppm, monkeypatch):
        ppm.queue(False)
        _, errors = toy.get_multiple_points([T('a')])
        assert 'Unable to send request to Toy Proxy' in errors[T('a')]
        ppm.queue(b'{"status": "error", "method": "READ_TOY", "error": "boom"}')
        _, errors = toy.get_multiple_points([T('a')])
        assert errors[T('a')] == 'Toy Proxy READ_TOY failed: boom'
        ppm.queue(b'not json')
        _, errors = toy.get_multiple_points([T('a')])
        assert 'Undecodable response' in errors[T('a')]
        ppm.queue(b'[]')
        _, errors = toy.get_multiple_points([T('a')])
        assert 'Unexpected response' in errors[T('a')]

        def slow(*_):
            raise Timeout()
        monkeypatch.setattr(toy, 'parse_proxy_response', slow)
        _, errors = toy.get_multiple_points([T('a')])
        assert errors[T('a')].startswith('Timeout waiting for Toy Proxy')

        def broken(*_):
            raise RuntimeError('kaput')
        monkeypatch.setattr(toy, 'parse_proxy_response', broken)
        _, errors = toy.get_multiple_points([T('a')])
        assert errors[T('a')] == 'Unexpected error: kaput'

    def test_unusable_value_is_a_point_error(self, toy, ppm):
        ppm.queue(serialized({T('a'): 'abc'}))
        _, errors = toy.get_multiple_points([T('a')])
        assert errors[T('a')].startswith('Unusable value from the Toy Proxy')

    def test_uninitialized_interface_raises(self, ppm):
        toy = build_interface(Toy, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm, points=POINTS)
        with pytest.raises(DriverInterfaceError):
            toy.get_multiple_points([T('a')])
        with pytest.raises(DriverInterfaceError):
            toy.set_point(T('c'), 1)

    def test_split_reads_issue_one_request_per_batch(self, ppm):
        toy = build_interface(Batched, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm, points=POINTS, peer_ready=True)
        ppm.queue(serialized({T('a'): 1, T('b'): 2}), serialized({T('c'): 3}, {T('d'): 'bad'}))
        results, errors = toy.get_multiple_points([T(n) for n in 'abcd'])
        assert results == {T('a'): 1.0, T('b'): 2.0, T('c'): 3.0} and errors == {T('d'): 'bad'}
        assert [p['topics'] for p in ppm.payloads('READ_TOY')] == [[T('a'), T('b')], [T('c'), T('d')]]


class TestWrites:
    def test_set_multiple_points_coerces_rejects_and_marks_dirty(self, toy, ppm):
        ppm.queue(serialized({T('c'): {'status': 'ok'}}, {T('d'): 'refused'}))
        results, errors = toy.set_multiple_points([(T('c'), '1.5'), (T('d'), 2), (T('a'), 3), (T('nope'), 4), (T('c'), 'x')])
        assert results == {T('c'): 1.5}
        assert errors[T('d')] == 'refused' and errors[T('a')] == READ_ONLY and errors[T('nope')] == NOT_CONFIGURED
        assert 'Unable to convert' in errors[T('c')] or True       # the second value for c failed coercion before sending
        assert ppm.payloads('WRITE_TOY') == [{'values': {T('c'): 1.5, T('d'): 2.0}}]
        assert T('c') in toy._tracker.dirty_points

    def test_set_point_through_basic_revert(self, toy, ppm):
        ppm.queue(serialized({T('c'): 'ack'}))
        assert toy.set_point(T('c'), 4) == 4.0
        assert T('c') in toy._tracker.dirty_points
        ppm.queue(serialized({}, {T('c'): 'nope'}))
        with pytest.raises(RuntimeError, match='nope'):
            toy.set_point(T('c'), 5)
        ppm.queue(serialized({}))
        with pytest.raises(RuntimeError, match='Write not acknowledged by the Toy Proxy'):
            toy.set_point(T('c'), 6)
        with pytest.raises(RuntimeError, match='read only'):
            toy.set_point(T('a'), 6)

    def test_split_writes_pass_kwargs_through(self, ppm):
        toy = build_interface(Batched, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm, points=POINTS, peer_ready=True)
        ppm.queue(serialized({T('c'): 1}), serialized({T('d'): 1}))
        results, errors = toy.set_multiple_points([(T('c'), 1), (T('d'), 2)], priority=8)
        assert results == {T('c'): 1.0, T('d'): 2.0} and errors == {}
        assert ppm.payloads('WRITE_TOY') == [{'topic': T('c'), 'value': 1.0, 'priority': 8},
                                             {'topic': T('d'), 'value': 2.0, 'priority': 8}]

    def test_write_timeout_reports_every_item_of_the_batch(self, toy, ppm, monkeypatch):
        def slow(*_):
            raise Timeout()
        monkeypatch.setattr(toy, 'parse_proxy_response', slow)
        results, errors = toy.set_multiple_points([(T('c'), 1), (T('d'), 2)])
        assert results == {} and all(e.startswith('Timeout waiting for Toy Proxy') for e in errors.values()) and len(errors) == 2


class TestWithoutBasicRevert:
    def test_direct_set_and_get_apply(self, ppm):
        class Bare(ProxyBackedInterface, BaseInterface):
            REGISTER_CONFIG_CLASS, INTERFACE_CONFIG_CLASS = ToyPointConfig, ToyRemoteConfig
            PROXY_NAME, READ_METHOD, WRITE_METHOD = 'toy', 'READ_TOY', 'WRITE_TOY'

            def __init__(self, config, *args, **kwargs):
                BaseInterface.__init__(self, config, *args, **kwargs)
                self.init_proxy()

            def create_register(self, definition):
                return ToyRegister(definition)

            def revert_point(self, topic, **kwargs):
                pass

            def revert_all(self, **kwargs):
                pass
        bare = build_interface(Bare, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm, points=POINTS, peer_ready=True)
        ppm.queue(serialized({T('a'): 5}), serialized({T('c'): 'ok'}))
        assert bare.get_multiple_points([T('a')]) == ({T('a'): 5}, {})
        assert bare.set_point(T('c'), 9, priority=8) == 9
        assert ppm.payloads('WRITE_TOY') == [{'values': {T('c'): 9}}]
        assert not hasattr(bare, '_tracker') and ppm.callbacks == {}


class TestFakePPM:
    def test_convenience_views(self, ppm):
        toy = build_interface(Toy, {'driver_type': 'toy', 'host': 'h'}, ppm=ppm)
        toy.finalize_setup()
        assert ppm.proxy_key == ('toy',) and ppm.proxy_kwargs == {} and ppm.registration_wait == 30.0
        assert ppm.methods() == ['REGISTER_TOY']
        assert FakePPM().proxy_key is None
