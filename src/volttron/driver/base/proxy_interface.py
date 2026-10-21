# -*- coding: utf-8 -*- {{{
# ===----------------------------------------------------------------------===
#
#                 Installable Component of Eclipse VOLTTRON
#
# ===----------------------------------------------------------------------===
#
# Copyright 2025 Battelle Memorial Institute
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
#
# ===----------------------------------------------------------------------===
# }}}
"""Base class for interfaces that speak their protocol through a Protocol Proxy process.

A proxy-backed interface does no protocol work itself. It declares the remote and its points to a proxy process
(``REGISTER_METHOD``), asks the proxy to read and write points by their full topics (``READ_METHOD``,
``WRITE_METHOD``), and publishes the values the proxy pushes back on its own initiative (``PUSH_METHOD``: a BACnet
change-of-value, a DNP3 unsolicited response, a 2030.5 control). This class owns everything those four exchanges have
in common: the shared :class:`GeventProtocolProxyManager` per protocol, the registration handshake, the reply
envelope (``{'result': ..., 'error': ...}`` from the proxy's serializer, ``{'status': 'error', ...}`` from the IPC
layer), the mapping of a reply onto per-topic results and errors, the three failure modes (unsendable request, gevent
timeout, unexpected exception) and the push callback into :meth:`DriverAgent.publish_push`.

Requests carry the instance's remote id in the header (protocol-proxy version 2), which is how the proxy knows which
registered remote a read or write concerns; the identity fields appear only in the registration payload.

Pushes are routed to the instance they concern. Each instance has a ``remote_id`` that it registers its push handler
under and sends to the proxy with the registration; the proxy tags its pushes for that remote with the same id
(protocol-proxy header version 2) and the manager delivers them to this instance's :meth:`receive_push`, which may
therefore use ``point_map`` and the rest of the instance's state (:meth:`handle_pushed`). The instance also offers
itself as the method's fallback handler for pushes without a remote id (an older proxy); only the first instance's
offer is kept, and :meth:`handle_pushed` publishes only this instance's own topics, so an untagged push for another
instance's points is dropped with a warning. Requests to the proxy carry the remote id too.

A protocol interface subclasses this, sets the class attributes, and overrides the few hooks whose defaults do not
fit: what identifies the remote (:meth:`identity_fields`), what a register contributes to the point table
(:meth:`point_fields`), how requests are batched (:meth:`split_reads`, :meth:`split_writes`), how a reply entry becomes
a value (:meth:`read_result`) and how a value is coerced before it is sent (:meth:`coerce`).

This is a mixin, listed first: ``class Dnp3(ProxyBackedInterface, BasicRevert, BaseInterface)``. In that order it
supplies the ``_set_point`` and ``_get_multiple_points`` that :class:`BasicRevert` declares abstract and defers to
BasicRevert's tracking ``set_point`` and ``get_multiple_points``; without BasicRevert
(``class BACnet(ProxyBackedInterface, BaseInterface)``) its own ``set_point`` and ``get_multiple_points`` apply and the
interface implements ``revert_point`` and ``revert_all`` itself. The interface's ``__init__`` calls
``BaseInterface.__init__`` (and ``BasicRevert.__init__``) and then :meth:`init_proxy`.

The manager watches the proxy processes it launches. When this instance's proxy exits or fails to register, the
manager tells the instance (:meth:`_proxy_peer_lost`), which forgets the peer and, after a growing delay
(``RECOVERY_DELAYS``), runs :meth:`finalize_setup` again: the first instance to do so relaunches the proxy, every
instance registers its remote again, and a server-role proxy pushes its table back. Requests made before that fail
as unsendable, as they would for any proxy that is down.

The protocol proxy library is VOLTTRON-independent; this module is the driver framework's way of using it, which is
why it lives here and ``protocol-proxy`` is an optional dependency of the base driver.
"""
from __future__ import annotations

import json
import logging

from typing import Any, Iterable
from uuid import UUID, uuid4

from gevent import Timeout, sleep
from gevent.event import AsyncResult

from protocol_proxy.ipc import ProtocolProxyMessage, ProtocolProxyPeer, callback
from protocol_proxy.manager.gevent import GeventProtocolProxyManager

from .interfaces import BaseRegister, DriverInterfaceError

_log = logging.getLogger(__name__)

NOT_CONFIGURED = 'Point not configured on device.'
READ_ONLY = 'Trying to write to a point configured read only.'


class PointError(DriverInterfaceError):
    """A per-point failure found while interpreting a proxy reply (an offline point, an unusable value)."""


class ProxyBackedInterface:
    """Mixin for an interface whose protocol runs in a Protocol Proxy process. See the module docstring."""

    #: Name of the shared manager (and of the proxy package under ``protocol_proxy.protocol``).
    PROXY_NAME: str | None = None
    #: How the proxy is named in log and error messages, e.g. ``'DNP3 Proxy'``. Defaults from PROXY_NAME.
    PROXY_LABEL: str | None = None
    #: Method names (at most 32 characters). ``REGISTER_METHOD`` None: no registration message is sent.
    REGISTER_METHOD: str | None = None
    READ_METHOD: str | None = None
    WRITE_METHOD: str | None = None
    #: Method the proxy uses to push values it obtained on its own; None: the proxy never pushes.
    PUSH_METHOD: str | None = None
    #: Key under which the proxy reports a whole-request failure in its ``error`` mapping.
    REQUEST_ERROR_KEY: str = 'request'
    #: Seconds to wait before re-running finalize_setup after the 1st, 2nd, ... consecutive loss of the proxy.
    RECOVERY_DELAYS: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0, 30.0)

    # Set by init_proxy(); declared here so the attributes exist on any instance.
    ppm: GeventProtocolProxyManager | None = None
    proxy_peer: ProtocolProxyPeer | None = None
    remote_id: UUID | None = None

    @property
    def proxy_label(self) -> str:
        return self.PROXY_LABEL or f'{self.PROXY_NAME} proxy'

    def init_proxy(self):
        """Attach to the protocol's shared manager and start it. The interface calls this at the end of ``__init__``."""
        self.proxy_peer = None
        self.remote_id = uuid4()
        self._recovery_attempts = 0
        self.ppm = GeventProtocolProxyManager.get_manager(self.PROXY_NAME)
        self.ppm.on_peer_lost(self._proxy_peer_lost)
        if self.PUSH_METHOD:
            # The manager is shared by every instance of the interface. Pushes tagged with this instance's remote id
            # come here; untagged ones (an older proxy) go to whichever instance registered the fallback first.
            self.ppm.register_callback(self.receive_push, self.PUSH_METHOD, provides_response=False,
                                       remote_id=self.remote_id)
            self.ppm.register_callback(self.receive_push, self.PUSH_METHOD, provides_response=False)
        self.ppm.start()
        self.driver_agent.core.spawn(self.ppm.select_loop)

    # ---- hooks a protocol may override ---------------------------------------------------------------------------
    def proxy_key(self) -> tuple:
        """Selects the proxy process; remotes with the same key share one."""
        return self.config.proxy_key()

    def proxy_launch_options(self) -> dict:
        """Keyword arguments for launching the proxy process (none by default)."""
        return {}

    def identity_fields(self) -> dict:
        """The fields that identify this remote to the proxy at registration (connection details) and in log messages.
        Later requests identify the remote by the header's remote id, not by payload fields."""
        return self.config.identity_fields()

    def reply_timeout(self) -> float:
        """How long to wait for the proxy's reply to one request."""
        timeout = getattr(self.config, 'resolved_reply_timeout', None)
        return timeout if timeout is not None else self.config.reply_timeout

    def point_fields(self, topic: str, register: BaseRegister) -> dict:
        """A register's entry in the registration point table."""
        return register.point_fields(topic)

    def registration_payload(self) -> dict:
        return {**self.identity_fields(),
                'points': [self.point_fields(topic, register) for topic, register in self.point_map.items()]}

    def tree_values(self) -> dict[str, Any]:
        """The equipment tree's current value of each of this remote's points that has one (``last_value`` of points
        that were ever updated). A server role sends these with its registration so a proxy that lost its served values
        (a restart) takes them back from the platform's memory; the proxy applies them only to points it holds no value
        for, then pushes its whole table."""
        tree = getattr(self.driver_agent, 'equipment_model', None)
        if tree is None or not callable(getattr(tree, 'get_node', None)):
            return {}
        values = {}
        for topic in self.point_map:
            node = tree.get_node(topic)
            if node is not None and getattr(node, 'last_updated', None) is not None:
                values[topic] = node.last_value
        return values

    def after_registration(self, result: dict, initial_setup: bool):
        """Called once the remote is registered (or, without a REGISTER_METHOD, once the proxy is up)."""
        _log.info(f'{self.proxy_label}: {self.identity_fields()} registered'
                  + (f' as {result}' if result else '') + '.')

    def read_payload(self, topics: list[str], **kwargs) -> dict:
        return {'topics': list(topics)}

    def split_reads(self, topics: list[str], **kwargs) -> list[tuple[dict, list[str]]]:
        """``(payload, topics)`` per request; one request for everything by default."""
        return [(self.read_payload(topics, **kwargs), list(topics))]

    def read_key(self, topic: str, register: BaseRegister) -> str:
        """The key under which a reply reports this point (the topic by default)."""
        return topic

    def read_result(self, register: BaseRegister, entry: Any) -> Any:
        """The value of a reply entry; raise :class:`PointError` for a per-point failure."""
        return entry

    def read_error(self, topic: str, register: BaseRegister, request_errors: Any) -> str:
        if isinstance(request_errors, dict):
            for key in (topic, self.read_key(topic, register), self.REQUEST_ERROR_KEY):
                if key in request_errors:
                    return str(request_errors[key])
        return f'No value returned by the {self.proxy_label}.'

    def interpret_read(self, topics: list[str], result: Any, request_errors: Any) -> tuple[dict, dict]:
        """Map one read reply onto ``(results, errors)`` for the topics of its request."""
        results, errors = {}, {}
        for topic in topics:
            register = self.point_map[topic]
            key = self.read_key(topic, register)
            if isinstance(result, dict) and key in result:
                try:
                    results[topic] = self.read_result(register, result[key])
                except PointError as e:
                    errors[topic] = str(e)
                except (TypeError, ValueError) as e:
                    errors[topic] = f'Unusable value from the {self.proxy_label}: {e}'
            else:
                errors[topic] = self.read_error(topic, register, request_errors)
        return results, errors

    def coerce(self, register: BaseRegister, value: Any) -> Any:
        """Convert a value to write into what the proxy expects; raise TypeError/ValueError when it cannot be."""
        return value

    def write_payload(self, items: list[tuple[str, Any]], **kwargs) -> dict:
        return {'values': dict(items)}

    def split_writes(self, items: list[tuple[str, Any]], **kwargs) -> list[tuple[dict, list[tuple[str, Any]]]]:
        """``(payload, items)`` per request; one request for everything by default."""
        return [(self.write_payload(items, **kwargs), list(items))]

    def write_result(self, register: BaseRegister, entry: Any, value: Any) -> Any:
        """What to report for an acknowledged write: the requested value by default."""
        return value

    def write_error(self, topic: str, register: BaseRegister, request_errors: Any) -> str:
        if isinstance(request_errors, dict):
            for key in (topic, self.read_key(topic, register), self.REQUEST_ERROR_KEY):
                if key in request_errors:
                    return str(request_errors[key])
        return f'Write not acknowledged by the {self.proxy_label}.'

    def interpret_write(self, items: list[tuple[str, Any]], result: Any, request_errors: Any) -> tuple[dict, dict]:
        """Map one write reply onto ``(results, errors)`` for the items of its request."""
        results, errors = {}, {}
        for topic, value in items:
            register = self.point_map[topic]
            key = self.read_key(topic, register)
            if isinstance(result, dict) and key in result:
                results[topic] = self.write_result(register, result[key], value)
            else:
                errors[topic] = self.write_error(topic, register, request_errors)
        return results, errors

    # ---- lifecycle -----------------------------------------------------------------------------------------------
    def finalize_setup(self, initial_setup: bool = False):
        self.proxy_peer = self.ppm.get_proxy(self.proxy_key(), **self.proxy_launch_options())
        self.ppm.wait_peer_registered(self.proxy_peer, self.config.registration_timeout, self.register_remote,
                                      initial_setup)

    def register_remote(self, initial_setup: bool = False):
        """Declare (or redeclare) the remote and its point table to the proxy, then run post-registration setup."""
        result: Any = {}
        if self.REGISTER_METHOD:
            # The payload always carries remote_id: the proxy tags pushes for this remote with it.
            payload = {**self.registration_payload(), 'remote_id': self.remote_id.hex}
            result, errors = self.request(self.REGISTER_METHOD, payload, [self.REQUEST_ERROR_KEY])
            if errors:
                _log.warning(f'Failed to register {self.identity_fields()} with the {self.proxy_label}: {errors}')
                return
        self._recovery_attempts = 0
        self.after_registration(result if isinstance(result, dict) else {}, initial_setup)

    def _proxy_peer_lost(self, peer: ProtocolProxyPeer, reason: str):
        """The manager reports that a proxy is gone. If it was ours, forget it and set up again after a delay."""
        if peer is None or peer is not self.proxy_peer:
            return
        self.proxy_peer = None
        delay = self.RECOVERY_DELAYS[min(self._recovery_attempts, len(self.RECOVERY_DELAYS) - 1)]
        self._recovery_attempts += 1
        _log.warning(f'{self.proxy_label} for {self.identity_fields()} lost ({reason}).'
                     f' Setting up again in {delay:g} s (attempt {self._recovery_attempts}).')
        self.driver_agent.core.spawn(self._recover_proxy, delay)

    def _recover_proxy(self, delay: float):
        sleep(delay)
        if self.proxy_peer is None:         # unless already set up again by someone else in the meantime
            self.finalize_setup(initial_setup=False)

    @callback
    def receive_push(self, _, raw_message: bytes):
        """Publish the values the proxy pushes, keyed by full point topic."""
        try:
            message = json.loads(raw_message.decode('utf8'))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            _log.warning(f'Undecodable {self.PUSH_METHOD} message from the {self.proxy_label}: {e}')
            return
        if not isinstance(message, dict):
            _log.warning(f'Unexpected {self.PUSH_METHOD} message from the {self.proxy_label}: {message!r}')
            return
        if error := message.get('error'):
            _log.warning(f'Error received with pushed values from the {self.proxy_label}: {error}')
        if result := message.get('result'):
            self.handle_pushed(result)

    def handle_pushed(self, values: dict[str, Any]):
        """What to do with pushed ``{topic: value}`` pairs: publish the ones that are this remote's points.

        A proxy is trusted to speak its protocol, not to name points it does not serve, so topics outside
        ``point_map`` are logged and dropped (the driver agent applies the same rule again). A protocol may override
        this to scale, coerce or filter before publishing.
        """
        mine = {topic: value for topic, value in values.items() if topic in self.point_map}
        if foreign := sorted(set(values) - set(mine)):
            _log.warning(f'{self.proxy_label}: ignoring pushed values for topics this remote does not serve: '
                         f'{foreign[:5]}{" ..." if len(foreign) > 5 else ""}')
        if mine:
            self.driver_agent.publish_push(mine)

    # ---- transport -----------------------------------------------------------------------------------------------
    def _send(self, method_name: str, payload: dict, response_expected: bool = True):
        """Send to the proxy. Every request is stamped with this instance's remote id, so a proxy may identify the
        remote from the header as well as from the payload."""
        return self.ppm.send(self.proxy_peer, ProtocolProxyMessage(method_name=method_name,
                                                                   payload=json.dumps(payload).encode('utf8'),
                                                                   response_expected=response_expected,
                                                                   remote_id=self.remote_id))

    def parse_proxy_response(self, response: Any, error_keys: Iterable[str]) -> tuple[Any, dict]:
        """Wait for and unpack a proxy reply: ``(result, errors)``.

        ``send`` returns an AsyncResult when a response is expected, or False when the request could not be sent.
        The proxy replies ``{'result': ..., 'error': ...}`` from its serializer, or ``{'status': 'error', 'error':
        ..., 'method': ...}`` when the endpoint raised or timed out. Whole-request failures are reported against every
        key in ``error_keys``. A gevent Timeout waiting on the AsyncResult is left to propagate to the caller.
        """
        error_keys = list(error_keys)

        def failed(message: str) -> tuple[dict, dict]:
            return {}, {key: message for key in error_keys}

        if not isinstance(response, AsyncResult):
            return failed(f'Unable to send request to {self.proxy_label} (send returned {response!r}).')
        raw = response.get(timeout=self.reply_timeout())
        if not raw:
            return failed(f'Empty response from {self.proxy_label}.')
        try:
            payload = json.loads(raw.decode('utf8') if isinstance(raw, (bytes, bytearray)) else raw)
        except (AttributeError, UnicodeDecodeError, json.JSONDecodeError, TypeError) as e:
            return failed(f'Undecodable response from {self.proxy_label}: {e}')
        if not isinstance(payload, dict):
            return failed(f'Unexpected response from {self.proxy_label}: {payload!r}')
        if payload.get('status') == 'error':
            return failed(f"{self.proxy_label} {payload.get('method', 'request')} failed: {payload.get('error')}")
        errors = payload.get('error')
        return payload.get('result', {}), errors if errors is not None else {}

    def request(self, method_name: str, payload: dict, error_keys: Iterable[str]) -> tuple[Any, Any]:
        """Send a request and unpack its reply, reporting a timeout or an unexpected failure against ``error_keys``."""
        error_keys = list(error_keys)
        try:
            return self.parse_proxy_response(self._send(method_name, payload), error_keys)
        except Timeout as e:
            _log.warning(f'Request {method_name} to the {self.proxy_label} timed out for {self.identity_fields()}: {e}')
            return {}, {key: f'Timeout waiting for {self.proxy_label}: {e}' for key in error_keys}
        except Exception as e:
            _log.warning(f'Unexpected error in {method_name} to the {self.proxy_label} for {self.identity_fields()}: {e}')
            return {}, {key: f'Unexpected error: {e}' for key in error_keys}

    # ---- reads and writes ----------------------------------------------------------------------------------------
    def _require_peer(self):
        if self.proxy_peer is None:
            raise DriverInterfaceError(f'{self.proxy_label} interface not initialized. No proxy peer available.')

    def proxy_read(self, topics: Iterable[str], **kwargs) -> tuple[dict, dict]:
        """Read ``topics`` through the proxy: ``(results, errors)`` keyed by topic."""
        self._require_peer()
        results, errors = {}, {}
        known = []
        for topic in topics:
            if topic in self.point_map:
                known.append(topic)
            else:
                errors[topic] = NOT_CONFIGURED
        if not known:
            return results, errors
        for payload, batch in self.split_reads(known, **kwargs):
            result, request_errors = self.request(self.READ_METHOD, payload, batch)
            batch_results, batch_errors = self.interpret_read(batch, result, request_errors)
            results.update(batch_results)
            errors.update(batch_errors)
        return results, errors

    def proxy_write(self, items: Iterable[tuple[str, Any]], **kwargs) -> tuple[dict, dict]:
        """Write ``(topic, value)`` items through the proxy: ``(results, errors)`` keyed by topic."""
        self._require_peer()
        results, errors = {}, {}
        accepted: list[tuple[str, Any]] = []
        for topic, value in items:
            register = self.point_map.get(topic)
            if register is None:
                errors[topic] = NOT_CONFIGURED
            elif register.read_only:
                errors[topic] = READ_ONLY
            else:
                try:
                    accepted.append((topic, self.coerce(register, value)))
                except PointError as e:
                    errors[topic] = str(e)
                except (TypeError, ValueError) as e:
                    errors[topic] = f'Unable to convert {value!r} for {topic}: {e}'
        if not accepted:
            return results, errors
        for payload, batch in self.split_writes(accepted, **kwargs):
            result, request_errors = self.request(self.WRITE_METHOD, payload, [topic for topic, _ in batch])
            batch_results, batch_errors = self.interpret_write(batch, result, request_errors)
            results.update(batch_results)
            errors.update(batch_errors)
        return results, errors

    # ---- BaseInterface entry points ------------------------------------------------------------------------------
    def get_point(self, topic: str, **kwargs):
        results, errors = self.proxy_read([topic], **kwargs)
        if topic in results:
            return results[topic]
        message = f'Error reading point: {topic} --- {errors.get(topic, errors)}'
        _log.warning(message)
        raise RuntimeError(message)

    def _get_multiple_points(self, topics: Iterable[str], **kwargs) -> tuple[dict, dict]:
        return self.proxy_read(list(topics), **kwargs)

    def get_multiple_points(self, topics: Iterable[str], **kwargs) -> tuple[dict, dict]:
        # A revert mixin after this class in the bases (BasicRevert) wraps the read to record clean values; use it.
        inherited = super(ProxyBackedInterface, self).get_multiple_points
        if not getattr(inherited, '__isabstractmethod__', False):
            return inherited(topics, **kwargs)
        return self._get_multiple_points(topics, **kwargs)

    def _set_point(self, topic: str, value: Any, **kwargs):
        results, errors = self.proxy_write([(topic, value)], **kwargs)
        if topic in errors:
            message = f'Error writing point: {topic} --- {errors[topic]}'
            _log.warning(message)
            raise RuntimeError(message)
        return results[topic]

    def set_point(self, topic: str, value: Any, **kwargs):
        inherited = super(ProxyBackedInterface, self).set_point
        if not getattr(inherited, '__isabstractmethod__', False):
            return inherited(topic, value, **kwargs) if kwargs else inherited(topic, value)
        return self._set_point(topic, value, **kwargs)

    def set_multiple_points(self, topics_values, **kwargs):
        results, errors = self.proxy_write(list(topics_values), **kwargs)
        tracker = getattr(self, '_tracker', None)
        if tracker is not None:
            for topic in results:
                tracker.mark_dirty_point(topic)
        if errors:
            _log.warning(f'Errors encountered setting points: {errors}')
        return results, errors
