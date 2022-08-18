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
