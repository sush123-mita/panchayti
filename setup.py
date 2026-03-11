"""
setup.py — Package definition for LocalDiscord.

Installation:
    pip install -e .          # editable dev install
    pip install .             # production install

After install, run with:
    localdiscord
"""

from setuptools import setup, find_packages

setup(
    name            = "localdiscord",
    version         = "1.0.6",
    description     = "Peer-to-peer LAN chat application with end-to-end encryption",
    author          = "Your Name",
    python_requires = ">=3.10",
    packages        = find_packages(exclude=["tests*"]),
    include_package_data = True,
    package_data    = {"": ["config/*.json", "assets/**/*"]},
    install_requires = [
        "PyQt6>=6.4.0",
        "PyQt6-Multimedia>=6.4.0",
        "cryptography>=41.0.0",
        "zeroconf>=0.131.0",
        "psutil>=5.9.0",
    ],
    extras_require  = {
        "dev": ["pytest>=7.0.0"],
    },
    entry_points    = {
        "console_scripts": [
            "localdiscord = src.main:main",
        ],
    },
    classifiers     = [
        "Programming Language :: Python :: 3",
        "Operating System :: OS Independent",
        "Topic :: Communications :: Chat",
    ],
)
