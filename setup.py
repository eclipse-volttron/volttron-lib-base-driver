# Always prefer setuptools over distutils
import sys

from setuptools import setup, find_packages



# Find the agent package that contains the main module
packages = find_packages("./src")
agent_package = ""

# Find the version number from the main module
sys.path.append('src')

# _temp = __import__(f'{agent_module}', globals(), locals(), ["__version__"], 0)
# __version__ = _temp.__version__

setup(
    name=f"volttron-lib-base-driver",
    version=0.1, #__version__, TODO: Is there a way to find the version of this library? Read pyproject.yml? Do we need to?
    install_requires=[],
    packages=packages,
    package_dir={'': 'src'},
    classifiers=[
        "Development Status :: 3 - Alpha",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Home Automation",
        "Topic :: Software Development :: Embedded Systems",
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
    ],
)
