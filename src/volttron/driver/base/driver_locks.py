# -*- coding: utf-8 -*- {{{
# ===----------------------------------------------------------------------===
#
#                 Installable Component of Eclipse VOLTTRON
#
# ===----------------------------------------------------------------------===
#
# Copyright 2022 Battelle Memorial Institute
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
import logging
import resource

from contextlib import contextmanager
from gevent.lock import BoundedSemaphore, DummySemaphore


_log = logging.getLogger(__name__)

_socket_lock = None

def get_system_socket_limit():
    # Increase open files resource limit to max or 8192 if unlimited
    system_socket_limit = None
    try:
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    except OSError:
        _log.exception('error getting open file limits')
    else:
        if soft != hard and soft != resource.RLIM_INFINITY:
            try:
                system_socket_limit = 8192 if hard == resource.RLIM_INFINITY else hard
                resource.setrlimit(resource.RLIMIT_NOFILE, (system_socket_limit, hard))
            except OSError:
                _log.exception('error setting open file limits')
            else:
                _log.debug('open file resource limit increased from %d to %d', soft,
                           system_socket_limit)
        if soft == hard:
            system_socket_limit = soft
    return system_socket_limit

def setup_socket_lock(max_open_sockets=None):
    if max_open_sockets is not None:
        max_connections = int(max_open_sockets)
        _log.info("maximum concurrently open sockets limited to " + str(max_open_sockets))
    else:
        system_socket_limit = get_system_socket_limit()
        if system_socket_limit is not None:
            max_connections = int(system_socket_limit * 0.8)
            _log.info("maximum concurrently open sockets limited to " + str(max_open_sockets)
                      + " (derived from system limits)")
        else:
            max_connections = 0
            _log.warning(
                "No limit set on the maximum number of concurrently open sockets. "
                "Consider setting max_open_sockets if you plan to work with 800+ modbus devices."
            )
    configure_socket_lock(max_connections)

def configure_socket_lock(max_connections=0):
    global _socket_lock
    if _socket_lock is not None:
        raise RuntimeError("socket_lock already configured!")
    if max_connections < 1:
        _socket_lock = DummySemaphore()
    else:
        _socket_lock = BoundedSemaphore(max_connections)


@contextmanager
def socket_lock():
    global _socket_lock
    if _socket_lock is None:
        raise RuntimeError("socket_lock not configured!")
    _socket_lock.acquire()
    try:
        yield
    finally:
        _socket_lock.release()


_publish_lock = None


def configure_publish_lock(max_connections=0):
    if max_connections < 1:
        _log.warning(
            "No limit set on the maximum number of concurrent driver publishes. "
            "Consider setting max_concurrent_publishes if you plan to work with many devices."
        )
    else:
        _log.info("maximum concurrent driver publishes limited to " + str(max_connections))
    global _publish_lock
    if _publish_lock is not None:
        raise RuntimeError("socket_lock already configured!")
    if max_connections < 1:
        _publish_lock = DummySemaphore()
    else:
        _publish_lock = BoundedSemaphore(max_connections)


@contextmanager
def publish_lock():
    global _publish_lock
    if _publish_lock is None:
        raise RuntimeError("socket_lock not configured!")
    _publish_lock.acquire()
    try:
        yield
    finally:
        _publish_lock.release()
