import abc
import logging

from abc import ABC
from functools import wraps
from pydantic import ConfigDict, create_model
from types import MethodType
from typing import Any, Callable, Iterable

from volttron.driver.base.interfaces import BaseInterface

_log = logging.getLogger(__name__)


class DriverPlugin(ABC):
    """
    Plugin to add functionality to an existing driver interface.
    Use as:
        di = MyDriverInterface()
        MyDriverPlugin.plug_into(di)
        di.method_from_plugin()  # The method is now available as if it were part of MyDriverInterface.

    """
    # Plugins should specify the specific class they are extending unless they are intended
    #  to work with all possible interfaces or proxies (in which case specify BaseInterface/ProtocolProxy).
    EXTENDED_CLASS = object

    # Plugins should specify a set of method names from the plugin class which will be added to the extended interface.
    PLUGIN_METHODS = set()

    # API_METHODS <-- {api_name: {'method_name': method_name, Optional['provides_response': bool], Optional['timeout': float]]}
    PROTOCOL_PROXY_METHODS: dict[str, dict[str, str | bool | float]] = dict()

    @classmethod
    @property
    def SHORT_NAME(cls) -> str:
        return cls.__name__

    @classmethod
    def plug_into(cls, obj):
        if not isinstance(obj, cls.EXTENDED_CLASS):
            raise TypeError(f'Plugin "{cls.__name__} extends {cls.EXTENDED_CLASS.__name__}'
                            f' not {obj.__class__.__name__}')
        for method_name in cls.PLUGIN_METHODS:
            method = getattr(cls, method_name)
            _log.info(f'Attaching plugin method: "{method_name}" to: {obj}')
            method = cls._add_overridden(method, getattr(obj, method_name)) if hasattr(obj, method_name) else method
            setattr(obj, method_name, MethodType(method, obj))

    @staticmethod
    def _add_overridden(func, overridden_method):
        @wraps(func)
        def wrapper(*args, **kwargs):
            kwargs['overridden'] = overridden_method
            return func(*args, **kwargs)
        return wrapper

    @classmethod
    def _extend_config(cls, super_config_class,
                       new_fields: dict[str, Any | tuple[str, Any]] | None = None,
                       new_configs: ConfigDict | dict[str, str] | None =None,
                       new_computed_fields: dict[str, Callable] | None = None,
                       new_validators: dict[str, Callable] | None = None):
        # TODO: Pydantic 2.13 and up are likely to change the API for __validators__ and add support for computed_fields.
        combined_configs: ConfigDict = ConfigDict(**super_config_class.model_config, **(new_configs or {}))
        combined_validators = {**(new_validators or {}), **(new_computed_fields or {})}
        new_fields = new_fields or {}
        return create_model(
            f'{super_config_class.__name__}-{cls.SHORT_NAME}',
            __base__=super_config_class,
            __config__=combined_configs,
            __validators__= combined_validators,
            **new_fields
        )


class InterfacePlugin(DriverPlugin):
    # API_METHODS <-- set of method names to be added to the interface.
    API_METHODS: set[str] = set()

    EXTENDED_CLASS = BaseInterface

    @classmethod
    def plug_into(cls, interface):
        super().plug_into(interface)
        interface.interface_callable_methods |= cls.API_METHODS

        # Set up any proxy methods:
        kwargs = {}
        if hasattr(interface, 'ppm'):
            for api_name, params in cls.PROTOCOL_PROXY_METHODS.items():
                if provides_response := params.get('provides_response'):
                    kwargs['provides_response'] = provides_response
                if timeout := params.get('timeout'):
                    kwargs['timeout'] = timeout
                interface.ppm.register_callback(MethodType(getattr(cls, params['method_name']), interface),
                                                api_name, **kwargs)

        # Extend configurations:
        interface.INTERFACE_CONFIG_CLASS = cls._extend_config(cls.EXTENDED_CLASS.INTERFACE_CONFIG_CLASS,
                                                              *cls.extend_interface_configuration())
        interface.REGISTER_CONFIG_CLASS = cls._extend_config(cls.EXTENDED_CLASS.REGISTER_CONFIG_CLASS,
                                                             *cls.extend_register_config())

    @classmethod
    @abc.abstractmethod
    def extend_interface_configuration(cls):
        """Return the following to extend the interface configuration class of the extended interface.
            These are provided to the pydantic.create_model() function to extend the configuration class.
            new_fields: dict[str, Any | tuple[str, Any]] | None
                - The key becomes the configuration name.
                - The value may be the type or a two-tuple where the first value is a type
                    and the second is a default value or Field.
            new_configs: ConfigDict | dict[str, str] | None,
            new_computed_fields: dict[str, Callable] | None,
            new_validators: dict[str, Callable] | None"""
        return None, None, None, None

    @classmethod
    @abc.abstractmethod
    def extend_register_config(cls):
        """Return the following to extend the register configuration class of the extended interface.
            These are provided to the pydantic.create_model() function to extend the configuration class.
            new_fields: dict[str, Any | tuple[str, Any]] | None
                - The key becomes the configuration name.
                - The value may be the type or a two-tuple where the first value is a type
                    and the second is a default value or Field.
            new_configs: ConfigDict | dict[str, str] | None,
            new_computed_fields: dict[str, Callable] | None,
            new_validators: dict[str, Callable] | None"""
        return None, None, None, None
