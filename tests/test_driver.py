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
import sys
from copy import copy
from datetime import date, datetime, time
from pathlib import Path

import mock
import pytest
import pytz
from utils import base_driver_agent
from volttron.client.vip.agent.core import ScheduledEvent

from volttron.driver.base.driver import DriverAgent
from volttron.driver.base.interfaces import BaseInterface

DriverAgent._log = logging.getLogger("test_logger")


def test_update_publish_types_should_only_set_depth_first_to_true():
    publish_depth_first_all = True
    publish_breadth_first_all = True
    publish_depth_first = True
    publish_breadth_first = True

    with base_driver_agent() as driver_agent:
        driver_agent.update_publish_types(publish_depth_first_all, publish_breadth_first_all,
                                          publish_depth_first, publish_breadth_first)

        assert not driver_agent.publish_all_depth
        assert not driver_agent.publish_all_breadth
        assert driver_agent.publish_depth_first
        assert not driver_agent.publish_breadth_first


@pytest.mark.parametrize("time_slot, driver_scrape_interval, group, group_offset_interval, "
                         "expected_time_slot_offset, expected_group", [(60, 2, 0, 3, 0, 0),
                                                                       (1, 4, 2, 3, 10, 2)])
def test_update_scrape_schedule_should_set_periodic_event(time_slot, driver_scrape_interval, group,
                                                          group_offset_interval,
                                                          expected_time_slot_offset,
                                                          expected_group):
    with base_driver_agent(has_periodic_read_event=True, has_core_schedule=True) as driver_agent:
        driver_agent.update_scrape_schedule(time_slot, driver_scrape_interval, group,
                                            group_offset_interval)

        assert driver_agent.group == expected_group
        assert driver_agent.time_slot_offset == expected_time_slot_offset
        assert isinstance(driver_agent.periodic_read_event, ScheduledEvent)


def test_update_scrape_schedule_should_return_none_when_no_periodic_read_event():
    time_slot = 1
    driver_scrape_interval = 4
    group = 2
    group_offset = 3
    expected_time_slot_offset = 10

    with base_driver_agent() as driver_agent:
        result = driver_agent.update_scrape_schedule(time_slot, driver_scrape_interval, group,
                                                     group_offset)

        assert result is None
        assert driver_agent.time_slot_offset == expected_time_slot_offset


@pytest.mark.parametrize("seconds, expected_datetime",
                         [(0, datetime.combine(date(2020, 6, 1), time(5, 30))),
                          (1, datetime.combine(date(2020, 6, 1), time(5, 31, 4))),
                          (59, datetime.combine(date(2020, 6, 1), time(5, 31, 4)))])
def test_find_starting_datetime_should_return_new_datetime(seconds, expected_datetime):
    # Note: the expected datetime depends on the interval attribute of driver_agent
    now = datetime.combine(date(2020, 6, 1), time(5, 30, seconds))

    with base_driver_agent() as driver_agent:
        actual_start_datetime = driver_agent.find_starting_datetime(now)

        assert actual_start_datetime == expected_datetime


def test_get_interface_should_return_mock_interface_on_custom_path_to_driver():
    sys_path_with = copy(sys.path)
    sys_path_with.insert(0, str(Path(__file__).resolve().parent))

    with mock.patch("sys.path", sys_path_with):
        with base_driver_agent() as driver_agent:
            driver_type = "mockinterface"
            config_dict = {"driver_module": "modules_for_testing.mock_interface"}
            config_string = [{
                "Point Name": "HPWH_Phy0_PowerState",
                "Writable": "TRUE",
                "Volttron Point Name": "PowerState",
                "Units": "1/0",
                "Starting Value": "0",
                "Type": "int"
            }]
            interface = driver_agent.get_interface(driver_type, config_dict, config_string)
            assert isinstance(interface, BaseInterface)
            assert type(interface).__name__ == "MockInterface"


def test_get_interface_should_raise_value_error_on_non_base_interface_module():
    sys_path_with = copy(sys.path)
    sys_path_with.insert(0, str(Path(__file__).resolve().parent))
    with pytest.raises(ValueError):
        with mock.patch("sys.path", sys_path_with):
            with base_driver_agent() as driver_agent:
                driver_type = "mockinterface"
                config_dict = {"driver_module": "modules_for_testing.non_base_interfaces"}
                driver_agent.get_interface(driver_type, config_dict, [])


def test_setup_device_should_raise_value_error_on_non_base_interface_module():
    sys_path_with = copy(sys.path)
    sys_path_with.insert(0, str(Path(__file__).resolve().parent))
    with pytest.raises(ValueError):
        with mock.patch("sys.path", sys_path_with):
            with base_driver_agent() as driver_agent:
                driver_agent.config = {
                    "driver_config": {
                        "driver_module": "modules_for_testing.non_base_interfaces"
                    },
                    "driver_type": "mockinterface",
                    "registry_config": []
                }
                driver_agent.setup_device()


def test_periodic_read_should_succeed():
    now = pytz.UTC.localize(datetime.utcnow())

    with base_driver_agent(has_core_schedule=True,
                           meta_data={"foo": "bar"},
                           has_base_topic=True,
                           mock_publish_wrapper=True,
                           interface_scrape_all={"foo": "bar"}) as driver_agent:
        driver_agent.periodic_read(now)

        driver_agent.agent.scrape_starting.assert_called_once()
        driver_agent.agent.scrape_ending.assert_called_once()
        driver_agent._publish_wrapper.assert_called_once()
        assert isinstance(driver_agent.periodic_read_event, ScheduledEvent)


@pytest.mark.parametrize("scrape_all_response", [{}, Exception()])
def test_periodic_read_should_return_none_on_scrape_response(scrape_all_response):
    now = pytz.UTC.localize(datetime.utcnow())

    with base_driver_agent(has_core_schedule=True,
                           meta_data={"foo": "bar"},
                           mock_publish_wrapper=True,
                           interface_scrape_all=scrape_all_response) as driver_agent:
        result = driver_agent.periodic_read(now)

        assert result is None
        driver_agent.agent.scrape_starting.assert_called_once()
        driver_agent.agent.scrape_ending.assert_not_called()
        driver_agent._publish_wrapper.assert_not_called()
        assert isinstance(driver_agent.periodic_read_event, ScheduledEvent)


def test_heart_beat_should_return_none_on_no_heart_beat_point():
    with base_driver_agent() as driver_agent:
        result = driver_agent.heart_beat()

        assert result is None
        assert not driver_agent.heart_beat_value
        driver_agent.interface.set_point.assert_not_called()


def test_heart_beat_should_set_heart_beat():
    with base_driver_agent(has_heart_beat_point=True) as driver_agent:
        driver_agent.heart_beat()

        assert driver_agent.heart_beat_value
        driver_agent.interface.set_point.assert_called_once()


def test_get_paths_for_point_should_return_depth_breadth():
    expected_depth = "foobar/roma"
    expected_breadth = "devices/roma"
    point = "foobar/roma"

    with base_driver_agent(has_base_topic=True) as driver_agent:
        actual_depth, actual_breadth = driver_agent.get_paths_for_point(point)

        assert actual_depth == expected_depth
        assert actual_breadth == expected_breadth


def test_get_point_should_succeed():
    with base_driver_agent() as driver_agent:
        driver_agent.get_point("pointname")

        driver_agent.interface.get_point.assert_called_once()


def test_set_point_should_succeed():
    with base_driver_agent() as driver_agent:
        driver_agent.set_point("pointname", "value")

        driver_agent.interface.set_point.assert_called_once()


def test_scrape_all_should_succeed():
    with base_driver_agent() as driver_agent:
        driver_agent.scrape_all()

        driver_agent.interface.scrape_all.assert_called_once()


def test_get_multiple_points_should_succeed():
    with base_driver_agent() as driver_agent:
        driver_agent.get_multiple_points("pointnames")

        driver_agent.interface.get_multiple_points.assert_called_once()


def test_set_multiple_points_should_succeed():
    with base_driver_agent() as driver_agent:
        driver_agent.set_multiple_points("pointnamevalues")

        driver_agent.interface.set_multiple_points.assert_called_once()


def test_revert_point_should_succeed():
    with base_driver_agent() as driver_agent:
        driver_agent.revert_point("pointnamevalues")

        driver_agent.interface.revert_point.assert_called_once()


def test_revert_all_should_succeed():
    with base_driver_agent() as driver_agent:
        driver_agent.revert_all()

        driver_agent.interface.revert_all.assert_called_once()


def test_publish_cov_value_should_succeed_when_publish_depth_first_is_true():
    point_name = "pointname"
    point_values = {"pointname": "value"}

    with base_driver_agent(mock_publish_wrapper=True,
                           meta_data={"pointname": "values"},
                           has_base_topic=True) as driver_agent:
        driver_agent.publish_cov_value(point_name, point_values)

        driver_agent._publish_wrapper.assert_called_once()
