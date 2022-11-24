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

from volttron.driver.base.interfaces import BaseInterface


class MockInterface(BaseInterface):

    def __init__(self, **kwargs):
        super(MockInterface, self).__init__(**kwargs)

    def _scrape_all(self):
        pass

    def _set_point(self, point_name, value):
        pass

    def get_point(self, point_name):
        pass

    def configure(self, config_dict, registry_config_str):
        pass

    def scrape_all(self):
        pass

    def set_point(self, point_name, value, **kwargs):
        pass

    def revert_all(self, **kwargs):
        pass

    def revert_point(self, point_name, **kwargs):
        pass
