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
"""Test helpers for proxy-backed interfaces: a stand-in for the proxy manager, and a builder that wires it in.

These run without a platform, a proxy process or a device. A test queues the replies the proxy would give, calls the
interface, and inspects the messages it sent::

    ppm = FakePPM()
    interface = build_interface(Dnp3, {'driver_type': 'dnp3', 'outstation_ip': '10.0.0.5'}, ppm=ppm)
    ppm.queue(serialized({'campus/b/der/AI_2': {'value': 2401, 'online': True}}))
    results, errors = interface.get_multiple_points(['campus/b/der/AI_2'])
    assert ppm.payloads('READ_POINTS') == [...]
"""
from __future__ import annotations

import json

from typing import Any
from unittest import mock

from gevent.event import AsyncResult


def serialized(result, error=None) -> bytes:
    """A reply as the proxy's serializer would produce it."""
    return json.dumps({'result': result, 'error': error if error is not None else {}}).encode('utf8')


class FakePPM:
    """Stands in for GeventProtocolProxyManager: records every message, replays queued replies, runs the hooks that
    ``wait_peer_registered`` would run once the proxy is up."""

    def __init__(self, default_reply: bytes | None = None):
        self.sent: list[tuple[str, dict, bool]] = []
        self.messages: list = []                            # the ProtocolProxyMessage objects as sent
        self.replies: list = []
        self.callbacks: dict[str, Any] = {}
        self.remote_callbacks: dict[tuple, Any] = {}
        self.peer = object()
        self.started = 0
        self.launch: tuple | None = None
        self.registration_waits: list[float] = []
        self.peer_lost_callbacks: list = []
        self.default_reply = serialized({}) if default_reply is None else default_reply

    def on_peer_lost(self, callback):
        self.peer_lost_callbacks.append(callback)

    def lose_peer(self, reason: str = 'process exited with code 1'):
        """Simulate the current proxy process dying: a fresh peer replaces it and the listeners are told."""
        lost, self.peer = self.peer, object()
        for callback in list(self.peer_lost_callbacks):
            callback(lost, reason)
        return lost

    def queue(self, *replies):
        """Replies in the order the interface will consume them: ``bytes`` become an AsyncResult; anything else
        (``False``) is returned as the result of ``send`` itself, to simulate an unsendable request."""
        self.replies.extend(replies)

    def register_callback(self, fn, name, provides_response=False, timeout=30.0, remote_id=None):
        if remote_id is not None:
            self.remote_callbacks[(name, remote_id)] = fn
        else:
            self.callbacks.setdefault(name, fn)             # first registration wins, as in the real manager

    def unregister_callback(self, name, remote_id=None):
        return (self.remote_callbacks.pop((name, remote_id), None) if remote_id is not None
                else self.callbacks.pop(name, None)) is not None

    def start(self):
        self.started += 1

    def select_loop(self):
        pass

    def get_proxy(self, key, **kwargs):
        self.launch = (key, kwargs)
        return self.peer

    def wait_peer_registered(self, peer, timeout, func=None, *args, **kwargs):
        self.registration_waits.append(timeout)
        if func:
            func(*args, **kwargs)

    def send(self, peer, message):
        self.sent.append((message.method_name, json.loads(message.payload.decode('utf8')), message.response_expected))
        self.messages.append(message)
        reply = self.replies.pop(0) if self.replies else self.default_reply
        if isinstance(reply, (bytes, bytearray)):
            result = AsyncResult()
            result.set(reply)
            return result
        return reply

    def payloads(self, method_name=None) -> list[dict]:
        return [p for m, p, _ in self.sent if method_name is None or m == method_name]

    def methods(self) -> list[str]:
        return [m for m, _, _ in self.sent]

    # Convenience views over the recorded launch and registration.
    @property
    def proxy_key(self):
        return self.launch[0] if self.launch else None

    @property
    def proxy_kwargs(self):
        return self.launch[1] if self.launch else None

    @property
    def registration_wait(self):
        return self.registration_waits[-1] if self.registration_waits else None


def build_interface(interface_class, remote: dict, *, driver_agent=None, ppm: FakePPM | None = None, points=(),
                    base_topic: str = 'campus/building/device', peer_ready: bool = False):
    """Construct a real interface whose proxy manager is a FakePPM, and insert ``points`` (PointConfig instances).

    ``peer_ready`` sets ``proxy_peer`` as if ``finalize_setup`` had run, for tests that go straight to reads and writes.
    """
    from volttron.driver.base.config import RemoteConfig
    ppm = ppm if ppm is not None else FakePPM()
    driver_agent = driver_agent if driver_agent is not None else mock.Mock(equipment_model=None)
    interface_class.default_config = {}
    with mock.patch('volttron.driver.base.proxy_interface.GeventProtocolProxyManager') as manager_class:
        manager_class.get_manager.return_value = ppm
        interface = interface_class(RemoteConfig(**remote), driver_agent=driver_agent)
    for point in points:
        interface.insert_register(interface.create_register(point), base_topic)
    if peer_ready:
        interface.proxy_peer = ppm.peer
    return interface
