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

import gevent
import logging
import random

from volttron.client.messaging import headers as headers_mod
from volttron.client.vip.agent.errors import Again, VIPError
from volttron.utils import format_timestamp, get_aware_utc_now

from volttron.driver.base.driver_locks import publish_lock


_log = logging.getLogger(__name__)


def publication_headers():
    # TODO: Sync_Timestamp won't work, so far, because time_slot_offset assumed the device was polled once per round.
    #  Since we are polling through a hyperperiod that may include multiple rounds for a given point or equipment,
    #  this no longer makes sense. Also, what if some points are polled multiple times compared to others?
    #  CAN SCHEDULED ALL_PUBLISHES REPLACE THIS MECHANISM IF THEY ARE GENERATED ALL AT ONCE?
    #  OR JUST USE THIS IS ALL-TYPE PUBLISHES ON A SCHEDULE?
    utcnow_string = format_timestamp(get_aware_utc_now())
    headers = {
        headers_mod.DATE: utcnow_string,
        headers_mod.TIMESTAMP: utcnow_string,
        # headers_mod.SYNC_TIMESTAMP: format_timestamp(current_start - timedelta(seconds=self.time_slot_offset))
    }
    return headers

def publish_wrapper(vip, topic, headers, message):
    while True:
        try:
            with publish_lock():
                _log.debug("publishing: " + topic)
                # TODO: Do we really need to block on every publish call?
                vip.pubsub.publish('pubsub', topic, headers=headers, message=message).get(timeout=10.0)
                _log.debug("finish publishing: " + topic)
        except gevent.Timeout:
            _log.warning("Did not receive confirmation of publish to " + topic)
            break
        except Again:
            _log.warning("publish delayed: " + topic + " pubsub is busy")
            gevent.sleep(random.random())
        except VIPError as ex:
            _log.warning("driver failed to publish " + topic + ": " + str(ex))
            break
        else:
            break