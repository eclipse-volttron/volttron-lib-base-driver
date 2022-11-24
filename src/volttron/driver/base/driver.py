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

import datetime
import importlib
import inspect
import logging
import random
import traceback
from typing import cast

import gevent
from volttron.client.messaging import headers as headers_mod
from volttron.client.messaging.topics import (
    DEVICES_PATH,
    DEVICES_VALUE,
    DRIVER_TOPIC_ALL,
    DRIVER_TOPIC_BASE,
)
from volttron.client.vip.agent import BasicAgent, Core
from volttron.client.vip.agent.errors import Again, VIPError
from volttron.utils import (
    format_timestamp,
    get_aware_utc_now,
    get_class,
    get_module,
    get_subclasses,
    setup_logging,
)

from volttron.driver.base.driver_locks import publish_lock
from volttron.driver.base.interfaces import BaseInterface

setup_logging()
_log = logging.getLogger(__name__)


class DriverAgent(BasicAgent):

    def __init__(self,
                 parent,
                 config,
                 time_slot,
                 driver_scrape_interval,
                 device_path,
                 group,
                 group_offset_interval,
                 default_publish_depth_first_all=True,
                 default_publish_breadth_first_all=True,
                 default_publish_depth_first=True,
                 default_publish_breadth_first=True,
                 **kwargs):
        super(DriverAgent, self).__init__(**kwargs)
        self.heart_beat_value = 0
        self.device_name = ''
        #Use the parent's vip connection
        self.parent = parent
        self.vip = parent.vip
        self.config = config
        self.device_path = device_path

        self.update_publish_types(default_publish_depth_first_all,
                                  default_publish_breadth_first_all, default_publish_depth_first,
                                  default_publish_breadth_first)

        try:
            interval = int(config.get("interval", 60))
            if interval < 1.0:
                raise ValueError
        except ValueError:
            _log.warning("Invalid device scrape interval {}. Defaulting to 60 seconds.".format(
                config.get("interval")))
            interval = 60

        self.interval = interval
        self.periodic_read_event = None

        self.update_scrape_schedule(time_slot, driver_scrape_interval, group,
                                    group_offset_interval)

    def update_publish_types(self, publish_depth_first_all, publish_breadth_first_all,
                             publish_depth_first, publish_breadth_first):
        """Setup which publish types happen for a scrape.
           Values passed in are overridden by settings in the specific device configuration."""
        self.publish_depth_first_all = bool(
            self.config.get("publish_depth_first_all", publish_depth_first_all))
        self.publish_breadth_first_all = bool(
            self.config.get("publish_breadth_first_all", publish_breadth_first_all))
        self.publish_depth_first = bool(self.config.get("publish_depth_first",
                                                        publish_depth_first))
        self.publish_breadth_first = bool(
            self.config.get("publish_breadth_first", publish_breadth_first))

    def update_scrape_schedule(self, time_slot, driver_scrape_interval, group,
                               group_offset_interval):
        self.time_slot_offset = (time_slot * driver_scrape_interval) + (group *
                                                                        group_offset_interval)
        self.time_slot = time_slot
        self.group = group

        _log.debug("{} group: {}, time_slot: {}, offset: {}".format(self.device_path, group,
                                                                    time_slot,
                                                                    self.time_slot_offset))

        if self.time_slot_offset >= self.interval:
            _log.warning(
                "Scrape offset exceeds interval. Required adjustment will cause scrapes to double up with other devices."
            )
            while self.time_slot_offset >= self.interval:
                self.time_slot_offset -= self.interval

        #check weather or not we have run our starting method.
        if not self.periodic_read_event:
            return

        self.periodic_read_event.cancel()

        next_periodic_read = self.find_starting_datetime(get_aware_utc_now())

        self.periodic_read_event = self.core.schedule(next_periodic_read, self.periodic_read,
                                                      next_periodic_read)

    def find_starting_datetime(self, now):
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seconds_from_midnight = (now - midnight).total_seconds()
        interval = self.interval

        offset = seconds_from_midnight % interval

        if not offset:
            return now

        previous_in_seconds = seconds_from_midnight - offset
        next_in_seconds = previous_in_seconds + interval

        from_midnight = datetime.timedelta(seconds=next_in_seconds)
        return midnight + from_midnight + datetime.timedelta(seconds=self.time_slot_offset)

    def get_interface(self, driver_type: str, driver_config: dict,
                      registry_config: list) -> BaseInterface:
        """Returns an instance of the interface

        :param driver_type: The name of the driver
        :type driver_type: str
        :param driver_config: The configuration of the driver
        :type driver_config: dict
        :param registry_config: A list of registry points reprsented as dictionaries
        :type registry_config: list

        :return: Returns an instance of a Driver that is a subclass of BaseInterface
        :rtype: BaseInterface

        :raises ValueError: Raises ValueError if no subclasses are found.
        """
        module = self.get_driver_module(driver_config, driver_type)
        base_interface_class = get_class('volttron.driver.base.interfaces', 'BaseInterface')
        subclasses = get_subclasses(module, base_interface_class)

        klass = subclasses[0]
        _log.debug(f"Instantiating driver: {klass}")
        interface = klass(vip=self.vip, core=self.core, device_path=self.device_path)

        _log.debug(f"Configuring driver with this configuration: {driver_config}")
        interface.configure(driver_config, registry_config)

        return cast(BaseInterface, interface)

    def get_driver_module(self, driver_config, driver_type):
        if driver_config.get("driver_module") is not None:
            return get_module(driver_config.get("driver_module"))
        return get_module(f"volttron.driver.interfaces.{driver_type}.{driver_type}")

    @Core.receiver('onstart')
    def starting(self, sender, **kwargs):
        self.setup_device()

        # interval = self.config.get("interval", 60)
        # self.core.periodic(interval, self.periodic_read, wait=None)

        next_periodic_read = self.find_starting_datetime(get_aware_utc_now())

        self.periodic_read_event = self.core.schedule(next_periodic_read, self.periodic_read,
                                                      next_periodic_read)

        self.all_path_depth, self.all_path_breadth = self.get_paths_for_point(DRIVER_TOPIC_ALL)

    def setup_device(self):

        config = self.config
        driver_config = config["driver_config"]
        driver_type = config["driver_type"]
        registry_config = config.get("registry_config")

        self.heart_beat_point = config.get("heart_beat_point")

        try:
            self.interface = self.get_interface(driver_type, driver_config, registry_config)
        except ValueError as e:
            _log.error(f"Failed to setup device: {e}")
            raise e

        self.meta_data = {}

        for point in self.interface.get_register_names():
            register = self.interface.get_register_by_name(point)
            if register.register_type == 'bit':
                ts_type = 'boolean'
            else:
                if register.python_type is int:
                    ts_type = 'integer'
                elif register.python_type is float:
                    ts_type = 'float'
                elif register.python_type is str:
                    ts_type = 'string'

            self.meta_data[point] = {
                'units': register.get_units(),
                'type': ts_type,
                'tz': config.get('timezone', '')
            }

        self.base_topic = DEVICES_VALUE(campus='',
                                        building='',
                                        unit='',
                                        path=self.device_path,
                                        point=None)

        self.device_name = DEVICES_PATH(base='',
                                        node='',
                                        campus='',
                                        building='',
                                        unit='',
                                        path=self.device_path,
                                        point='')

        # self.parent.device_startup_callback(self.device_name, self)

    def periodic_read(self, now):
        #we not use self.core.schedule to prevent drift.
        next_scrape_time = now + datetime.timedelta(seconds=self.interval)
        # Sanity check now.
        # This is specifically for when this is running in a VM that gets
        # suspended and then resumed.
        # If we don't make this check a resumed VM will publish one event
        # per minute of
        # time the VM was suspended for.
        test_now = get_aware_utc_now()
        if test_now - next_scrape_time > datetime.timedelta(seconds=self.interval):
            next_scrape_time = self.find_starting_datetime(test_now)

        _log.debug("{} next scrape scheduled: {}".format(self.device_path, next_scrape_time))

        self.periodic_read_event = self.core.schedule(next_scrape_time, self.periodic_read,
                                                      next_scrape_time)

        _log.debug("scraping device: " + self.device_name)

        self.parent.scrape_starting(self.device_name)

        try:
            results = self.interface.scrape_all()
            register_names = self.interface.get_register_names_view()
            for point in (register_names - results.keys()):
                depth_first_topic = self.base_topic(point=point)
                _log.error("Failed to scrape point: " + depth_first_topic)
        except (Exception, gevent.Timeout) as ex:
            tb = traceback.format_exc()
            _log.error('Failed to scrape ' + self.device_name + ':\n' + tb)
            return

        # XXX: Does a warning need to be printed?
        if not results:
            return

        utcnow = get_aware_utc_now()
        utcnow_string = format_timestamp(utcnow)
        sync_timestamp = format_timestamp(now - datetime.timedelta(seconds=self.time_slot_offset))

        headers = {
            headers_mod.DATE: utcnow_string,
            headers_mod.TIMESTAMP: utcnow_string,
            headers_mod.SYNC_TIMESTAMP: sync_timestamp
        }

        if self.publish_depth_first or self.publish_breadth_first:
            for point, value in results.items():
                depth_first_topic, breadth_first_topic = self.get_paths_for_point(point)
                message = [value, self.meta_data[point]]

                if self.publish_depth_first:
                    self._publish_wrapper(depth_first_topic, headers=headers, message=message)

                if self.publish_breadth_first:
                    self._publish_wrapper(breadth_first_topic, headers=headers, message=message)

        message = [results, self.meta_data]
        if self.publish_depth_first_all:
            self._publish_wrapper(self.all_path_depth, headers=headers, message=message)

        if self.publish_breadth_first_all:
            self._publish_wrapper(self.all_path_breadth, headers=headers, message=message)

        self.parent.scrape_ending(self.device_name)

    def _publish_wrapper(self, topic, headers, message):
        while True:
            try:
                with publish_lock():
                    _log.debug("publishing: " + topic)
                    self.vip.pubsub.publish('pubsub', topic, headers=headers,
                                            message=message).get(timeout=10.0)

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

    def heart_beat(self):
        if self.heart_beat_point is None:
            return

        self.heart_beat_value = int(not bool(self.heart_beat_value))

        _log.debug("sending heartbeat: " + self.device_name + ' ' + str(self.heart_beat_value))

        self.set_point(self.heart_beat_point, self.heart_beat_value)

    def get_paths_for_point(self, point):
        depth_first = self.base_topic(point=point)

        parts = depth_first.split('/')
        breadth_first_parts = parts[1:]
        breadth_first_parts.reverse()
        breadth_first_parts = [DRIVER_TOPIC_BASE] + breadth_first_parts
        breadth_first = '/'.join(breadth_first_parts)

        return depth_first, breadth_first

    def get_point(self, point_name, **kwargs):
        return self.interface.get_point(point_name, **kwargs)

    def set_point(self, point_name, value, **kwargs):
        return self.interface.set_point(point_name, value, **kwargs)

    def scrape_all(self):
        return self.interface.scrape_all()

    def get_multiple_points(self, point_names, **kwargs):
        return self.interface.get_multiple_points(self.device_name, point_names, **kwargs)

    def set_multiple_points(self, point_names_values, **kwargs):
        return self.interface.set_multiple_points(self.device_name, point_names_values, **kwargs)

    def revert_point(self, point_name, **kwargs):
        self.interface.revert_point(point_name, **kwargs)

    def revert_all(self, **kwargs):
        self.interface.revert_all(**kwargs)

    def publish_cov_value(self, point_name, point_values):
        """
        Called in the platform driver agent to publish a cov from a point
        :param point_name: point which sent COV notifications
        :param point_values: COV point values
        """
        utcnow = get_aware_utc_now()
        utcnow_string = format_timestamp(utcnow)
        headers = {
            headers_mod.DATE: utcnow_string,
            headers_mod.TIMESTAMP: utcnow_string,
        }
        for point, value in point_values.items():
            results = {point_name: value}
            meta = {point_name: self.meta_data[point_name]}
            all_message = [results, meta]
            individual_point_message = [value, self.meta_data[point_name]]

            depth_first_topic, breadth_first_topic = self.get_paths_for_point(point_name)

            if self.publish_depth_first:
                self._publish_wrapper(depth_first_topic,
                                      headers=headers,
                                      message=individual_point_message)
            #
            if self.publish_breadth_first:
                self._publish_wrapper(breadth_first_topic,
                                      headers=headers,
                                      message=individual_point_message)

            if self.publish_depth_first_all:
                self._publish_wrapper(self.all_path_depth, headers=headers, message=all_message)

            if self.publish_breadth_first_all:
                self._publish_wrapper(self.all_path_breadth, headers=headers, message=all_message)
