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

from datetime import timedelta
from enum import Enum
from pydantic import BaseModel, computed_field, ConfigDict, Field, field_serializer, field_validator

# TODO: Wire up the data_source field to poll scheduling (everything is currently short-poll because this isn't used).
# TODO: Should NEVER actually be an option? Could it just be None?
class DataSource(Enum):
    SHORT_POLL = "short_poll"
    LONG_POLL = "long_poll"
    NEVER = "never"
    POLL_ONCE = "poll_once"
    STATIC = "static"


class EquipmentConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True, populate_by_name=True)
    active: bool | None = None
    group: str | None = None
    # TODO: If this needs to be an int, we may need to use milliseconds someplace.
    polling_interval: int | None = Field(default=None, alias='interval')
    publish_single_depth: bool | None = Field(default=None, alias='publish_depth_first_single')
    publish_single_breadth: bool | None = Field(default=None, alias='publish_breadth_first_single')
    publish_multi_depth: bool | None = Field(default=None, alias='publish_depth_first_multi')
    publish_multi_breadth: bool | None = Field(default=None, alias='publish_breadth_first_multi')
    publish_all_depth: bool | None = Field(default=None, alias='publish_depth_first_all')
    publish_all_breadth: bool | None = Field(default=None, alias='publish_breadth_first_all')
    reservation_required_for_write: bool = False

    @field_validator('polling_interval', mode='before')
    @classmethod
    def _normalize_polling_interval(cls, v):
        # TODO: This does not match int above, but we may need to convert to ms in calculations.
        return None if v == '' or v is None else float(v)

class PointConfig(EquipmentConfig):
    data_source: DataSource = Field(default=DataSource.SHORT_POLL, alias='Data Source')
    notes: str = Field(default='', alias='Notes')
    reference_point_name: str = Field(default='', alias='Reference Point Name')
    stale_timeout_configured: float | None = Field(default=None, alias='stale_timeout')
    stale_timeout_multiplier: float = Field(default=3)
    units: str = Field(default='', alias='Units')
    units_details: str = Field(default='', alias='Unit Details')
    volttron_point_name: str = Field(alias='Volttron Point Name')
    writable: bool = Field(default=False, alias='Writable')

    @field_validator('data_source', mode='before')
    @classmethod
    def _normalize_data_source(cls, v):
        # TODO: This never converts to DataSource.
        # TODO: Data Source enum needs something to tell Data Point how to serialize it, otherwise enable/disable will fail.
        return v.lower()

    @field_serializer('data_source')
    def _serialize_data_source(self, data_source):
        return data_source.value

    @computed_field
    @property
    def stale_timeout(self) -> timedelta | None:
        if self.stale_timeout_configured is None and self.polling_interval is None:
            return None
        else:
            return timedelta(seconds=(self.stale_timeout_configured
                    if self.stale_timeout_configured is not None
                    else self.polling_interval * self.stale_timeout_multiplier))

    @stale_timeout.setter
    def stale_timeout(self, value):
        self.stale_timeout_configured = value


class DeviceConfig(EquipmentConfig):
    all_publish_interval: float = 0.0
    allow_duplicate_remotes: bool = False
    equipment_specific_fields: dict = {}
    registry_config: list[PointConfig] = []


class RemoteConfig(BaseModel):
    model_config = ConfigDict(extra='allow', validate_assignment=True)
    debug: bool = False
    driver_type: str
    heart_beat_point: str | None = None  # TODO: This needs to become a set (multiple devices could have multiple points).
    module: str | None = None