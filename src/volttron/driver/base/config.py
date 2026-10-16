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
from pydantic import AliasChoices, BaseModel, computed_field, ConfigDict, Field, field_serializer, field_validator, BeforeValidator
from typing import Annotated

class DataSource(Enum):
    """How a point gets its value, and so how the poll scheduler treats it.

    ============  =================================================================================================
    SHORT_POLL    Polled at its polling interval in the device's regular cyclic schedule (the default).
    LONG_POLL     Polled at its polling interval, but in a separate schedule so that very long intervals (totals,
                  configuration registers) do not stretch the hyperperiod of the regular schedule.
    POLL_ONCE     Read once when the device is set up or reconfigured (nameplate data), then never polled.
    STATIC        Never read from a device: the value is configuration or whatever was last written to it.
    NEVER_POLL    A device point the platform never polls; values arrive by push (change of value, unsolicited
                  responses) or by an explicit get. ``never`` is accepted as an older spelling.
    SERVER        A served point of a device in a server role: written by the platform and by the peer's pushes,
                  never polled, seeded both ways when the device registers with its proxy.
    ============  =================================================================================================

    Points that are not ``scheduled`` are left out of the cyclic poll sets; points that are not ``polled`` are never
    read by the scheduler at all, so their staleness is judged by any configured ``stale_timeout`` alone.
    """
    SHORT_POLL = "short_poll"
    LONG_POLL = "long_poll"
    POLL_ONCE = "poll_once"
    STATIC = "static"
    NEVER_POLL = "never_poll"
    SERVER = "server"

    @property
    def scheduled(self) -> bool:
        """Polled on a cyclic schedule."""
        return self in (DataSource.SHORT_POLL, DataSource.LONG_POLL)

    @property
    def polled(self) -> bool:
        """Read from the device by the scheduler at some point (cyclically or once)."""
        return self in (DataSource.SHORT_POLL, DataSource.LONG_POLL, DataSource.POLL_ONCE)

    @classmethod
    def normalize(cls, value):
        """Accept a member, its value or its name in any case, with spaces or hyphens, and older spellings."""
        if isinstance(value, cls):
            return value
        text = str(value).strip().lower().replace('-', '_').replace(' ', '_')
        return cls.LEGACY_VALUES.get(text, text)


DataSource.LEGACY_VALUES = {'never': 'never_poll'}


def empty_str_is(default):
    def func(v):
        if v == '':
            return default
        return v
    return BeforeValidator(func)


class EquipmentConfig(BaseModel):
    model_config = ConfigDict(validate_assignment=True, populate_by_name=True)
    active: Annotated[bool | None, empty_str_is(None)] = None
    # The polling group (see the platform driver's `groups`). `group` and `Group` are the names of earlier configurations.
    polling_group: Annotated[str | None, empty_str_is(None)] = Field(
        default=None, validation_alias=AliasChoices('polling_group', 'group', 'Group'))
    # TODO: If this needs to be an int, we may need to use milliseconds someplace.
    polling_interval: Annotated[int | None, empty_str_is(None)] = Field(default=None, alias='interval')
    publish_single_depth: Annotated[bool | None, empty_str_is(None)] = Field(default=None, alias='publish_depth_first_single')
    publish_single_breadth: Annotated[bool | None, empty_str_is(None)] = Field(default=None, alias='publish_breadth_first_single')
    publish_multi_depth: Annotated[bool | None, empty_str_is(None)] = Field(default=None, alias='publish_depth_first_multi')
    publish_multi_breadth: Annotated[bool | None, empty_str_is(None)] = Field(default=None, alias='publish_breadth_first_multi')
    publish_all_depth: Annotated[bool | None, empty_str_is(None)] = Field(default=None, alias='publish_depth_first_all')
    publish_all_breadth: Annotated[bool | None, empty_str_is(None)] = Field(default=None, alias='publish_breadth_first_all')
    reservation_required_for_write: Annotated[bool, empty_str_is(False)] = False  # TODO: Should this default to None for tree-based resolution?
    stale_timeout_configured: Annotated[float | None, empty_str_is(None)] = Field(default=None, alias='stale_timeout')
    stale_timeout_multiplier: Annotated[float, empty_str_is(None)] = Field(default=None)
    strict_all_publishes: Annotated[bool | None, empty_str_is(None)] = None

    @field_validator('polling_interval', mode='before')
    @classmethod
    def _normalize_polling_interval(cls, v):
        # TODO: This does not match int above, but we may need to convert to ms in calculations.
        return None if v == '' or v is None else float(v)


class PointConfig(EquipmentConfig):
    data_source: Annotated[DataSource, empty_str_is(DataSource.SHORT_POLL)] = Field(default=DataSource.SHORT_POLL, alias='Data Source')
    notes: str = Field(default='', alias='Notes')
    reference_point_name: str = Field(default='', alias='Reference Point Name')
    units: str = Field(default='', alias='Units')
    units_details: str = Field(default='', alias='Unit Details')
    volttron_point_name: str = Field(alias='Volttron Point Name')
    writable: Annotated[bool, empty_str_is(False)] = Field(default=False, alias='Writable')
    # Server roles only: whether the remote peer may write this served point. None lets the interface default it from
    # the protocol address (an output, an upward resource, a holding register). The platform's own right to set the
    # point is ``writable``, as for any other point.
    remote_writable: Annotated[bool | None, empty_str_is(None)] = Field(default=None, alias='Remote Writable')

    @field_validator('data_source', mode='before')
    @classmethod
    def _normalize_data_source(cls, v):
        return DataSource.normalize(v) if v is not None and v != '' else v

    @field_serializer('data_source')
    def _serialize_data_source(self, data_source):
        return data_source.value


class DeviceConfig(EquipmentConfig):
    all_publish_interval: Annotated[float | None, empty_str_is(None)] = None
    allow_duplicate_remotes: bool = False
    equipment_specific_fields: dict = {}
    registry_config: list[PointConfig] = []


class RemoteConfig(BaseModel):
    model_config = ConfigDict(extra='allow', populate_by_name=True, validate_assignment=True)
    debug: bool = False
    driver_type: str
    # Which side of its protocol this remote is: the default ``client`` reaches a device (master, client); a server
    # role (``server``, or a protocol's own word such as ``outstation``) serves the configured points to a remote peer.
    # Each interface's configuration narrows the accepted values and validates the role-specific fields.
    driver_role: str = 'client'
    heart_beat_point: str | None = None  # TODO: This needs to become a set (multiple devices could have multiple points).
    module: str | None = None
    plugins: list[str] = []

    @field_validator('driver_role', mode='before')
    @classmethod
    def _normalize_driver_role(cls, v):
        return v.strip().lower() if isinstance(v, str) and v.strip() else 'client' if v in (None, '') else v