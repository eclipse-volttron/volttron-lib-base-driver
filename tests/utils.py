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

import contextlib
from typing import Any

from mock import create_autospec
from volttron.client.vip.agent import Agent
from volttron.client.vip.agent.core import ScheduledEvent
from volttrontesting.utils import AgentMock

from volttron.driver.base.driver import DriverAgent
from volttron.driver.base.interfaces import BaseInterface

DriverAgent.__bases__ = (AgentMock.imitate(Agent, Agent()), )


@contextlib.contextmanager
def base_driver_agent(has_base_topic: bool = False,
                      has_periodic_read_event: bool = False,
                      has_core_schedule: bool = False,
                      meta_data: dict = None,
                      mock_publish_wrapper: bool = False,
                      interface_scrape_all: Any = None,
                      has_heart_beat_point: bool = False):
    """
    Creates a Driver Agent and mocks its dependencies to be used for unit testing.
    :param has_base_topic:
    :param has_periodic_read_event:
    :param has_core_schedule:
    :param meta_data:
    :param mock_publish_wrapper:
    :param interface_scrape_all:
    :param has_heart_beat_point:
    :return:
    """

    parent = create_autospec(MockedParent)
    # since parent is a mock and not a real instance of a class, we have to set attributes directly
    # create_autospec does not set attributes in a class' constructor
    parent.vip = ""

    config = {
        "driver_config": {},
        "driver_type":
        "fakedriver",
        "registry_config": [{
            "Point Name": "HPWH_Phy0_PowerState",
            "Writable": "TRUE",
            "Volttron Point Name": "PowerState",
            "Units": "1/0",
            "Starting Value": "0",
            "Type": "int"
        }],
        "interval":
        60,
        "publish_depth_first_all":
        False,
        "publish_breadth_first_all":
        False,
        "publish_depth_first":
        True,
        "publish_breadth_first":
        False,
        "heart_beat_point":
        "Heartbeat",
        "timezone":
        "US/Pacific",
    }
    time_slot = 2
    driver_scrape_interval = 2
    device_path = "path/to/my/device"
    group = 42
    group_offset_interval = 0

    driver_agent = DriverAgent(parent, config, time_slot, driver_scrape_interval, device_path,
                               group, group_offset_interval)

    driver_agent.interface = create_autospec(BaseInterface)

    if interface_scrape_all is not None:
        driver_agent.interface.scrape_all.return_value = interface_scrape_all

    if has_base_topic:
        driver_agent.base_topic = MockedBaseTopic()

    if has_periodic_read_event:
        driver_agent.periodic_read_event = create_autospec(ScheduledEvent)

    if has_core_schedule:
        driver_agent.core.schedule.return_value = create_autospec(ScheduledEvent)
        driver_agent.core.schedule.cancel = None

    if meta_data is not None:
        # TODO: drive_agent.meta_data is not stored in each point node instead of a dictionary in the driver agent.
        driver_agent.meta_data = meta_data

    if mock_publish_wrapper:
        driver_agent._publish_wrapper = create_autospec(MockedPublishWrapper)

    if has_heart_beat_point:
        driver_agent.heart_beat_point = 42
    else:
        driver_agent.heart_beat_point = None

    yield driver_agent


class MockedParent:

    def scrape_starting(self, device_name):
        pass

    def scrape_ending(self, device_name):
        pass


class MockedBaseTopic:

    def __call__(self, point):
        return point


class MockedPublishWrapper:

    def __call__(self, depth_first_topic, headers, message):
        pass
