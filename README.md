# volttron-lib-base-driver

[![Eclipse VOLTTRON™](https://img.shields.io/badge/Eclips%20VOLTTRON--red.svg)](https://volttron.readthedocs.io/en/latest/)
![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)
![Passing?](https://github.com/eclipse-volttron/volttron-lib-base-driver/actions/workflows/run-tests.yml/badge.svg)
[![pypi version](https://img.shields.io/pypi/v/volttron-lib-base-driver.svg)](https://pypi.org/project/volttron-lib-base-driver/)


## Requirements

* python >= 3.10
* volttron-core >= 2.0.0rc0

# Documentation
More detailed information about the VOLTTRON Driver Framework can be found [ReadTheDocs](https://eclipse-volttron.readthedocs.io/en/latest/external-docs/volttron-platform-driver/index.html#platform-driver-framework). The RST source
of the documentation for this component is located in the "docs" directory of this repository.

## Installation

Before installing, VOLTTRON should be installed and running.  Its virtual environment should be active.
Information on how to install of the VOLTTRON platform can be found
[here](https://github.com/eclipse-volttron/volttron-core).

Install the library into the running VOLTTRON instance:

```shell
vctl install-lib volttron-lib-base-driver
```

To remove it later, use:

```shell
vctl remove-lib volttron-lib-base-driver
```

## Proxy-backed interfaces

Interfaces whose protocol runs in a [Protocol Proxy](https://github.com/eclipse-volttron/lib-protocol-proxy) process
(BACnet, Modbus, DNP3, IEEE 2030.5) share `volttron.driver.base.proxy_interface.ProxyBackedInterface`: the manager
wiring, the registration handshake, the reply envelope, the mapping of replies onto per-topic results and errors, the
timeout and failure handling, and the push callback into `publish_push`. A protocol interface lists it first,
`class Dnp3(ProxyBackedInterface, BasicRevert, BaseInterface)`, sets the message names as class attributes and
overrides the few hooks whose defaults do not fit (`identity_fields`, `point_fields`, `read_payload`, `read_result`,
`coerce`, `split_reads`, `split_writes`). `volttron.driver.base.testing` provides `FakePPM`, `serialized` and
`build_interface` for testing such interfaces without a proxy process. The protocol proxy is an optional dependency:
`pip install volttron-lib-base-driver[proxy]`.

The proxy manager watches the processes it launches. When an interface's proxy exits or never registers, the interface
is told, forgets the peer and runs `finalize_setup` again after a growing delay (`RECOVERY_DELAYS`: 1, 2, 5, 10, then
30 seconds between attempts): the proxy is relaunched and every remote registers with it again, without a platform
driver restart. Pushed values arriving by topic are checked twice, in `handle_pushed` (only the instance's own points)
and in `DriverAgent.publish_push` (only points of that remote), so a proxy can only affect the points it serves.

A remote configuration may name a `driver_role`. The default, `client`, reaches a device; a server role (`server`, or
the protocol's own word such as `outstation`) serves the configured points to a remote peer through the same interface
class and proxy. Each interface narrows the accepted values and validates the role-specific settings. In a server role
the registry's `Remote Writable` column says which served points the peer may write (defaulting from the protocol
address), while `Writable` keeps meaning that the platform may set the point; served rows default to the `server` data
source, so they are never polled.

## Development

Please see the following for contributing guidelines [contributing](https://github.com/eclipse-volttron/volttron-core/blob/develop/CONTRIBUTING.md).

Please see the following helpful guide about [developing modular VOLTTRON agents](https://github.com/eclipse-volttron/volttron-core/blob/develop/DEVELOPING_ON_MODULAR.md)


## Disclaimer Notice

This material was prepared as an account of work sponsored by an agency of the
United States Government.  Neither the United States Government nor the United
States Department of Energy, nor Battelle, nor any of their employees, nor any
jurisdiction or organization that has cooperated in the development of these
materials, makes any warranty, express or implied, or assumes any legal
liability or responsibility for the accuracy, completeness, or usefulness or any
information, apparatus, product, software, or process disclosed, or represents
that its use would not infringe privately owned rights.

Reference herein to any specific commercial product, process, or service by
trade name, trademark, manufacturer, or otherwise does not necessarily
constitute or imply its endorsement, recommendation, or favoring by the United
States Government or any agency thereof, or Battelle Memorial Institute. The
views and opinions of authors expressed herein do not necessarily state or
reflect those of the United States Government or any agency thereof.
