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

Install the library. You have two options. You can install this library using the version on PyPi:

```shell
poetry add --directory $VOLTTRON_HOME volttron-lib-base-driver
```

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
