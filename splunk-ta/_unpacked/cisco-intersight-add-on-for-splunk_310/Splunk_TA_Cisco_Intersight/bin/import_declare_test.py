"""Declare the path of the libraries for the Addon Package.

The goal is to make sure that the Python interpreter loads the libraries from
the correct location. This is important because the Addon Package contains
custom libraries that are not part of the standard Python distribution.

The approach is to remove all paths that do not contain the name of the Addon
Package from the sys.path list. This is done to prevent the Python interpreter
from loading the wrong libraries.

The new paths are inserted at the beginning of the sys.path list to ensure that
the custom libraries are loaded first.

The paths are constructed by joining the directory of the current file with the
name of the Addon Package and the subdirectories "lib" or "bin".
"""

import os
import sys
import re
from os.path import dirname

ta_name = 'Splunk_TA_Cisco_Intersight'
pattern = re.compile(r'[\\/]etc[\\/]apps[\\/][^\\/]+[\\/]bin[\\/]?$')
new_paths = [path for path in sys.path if not pattern.search(path) or ta_name in path]
new_paths.insert(0, os.path.join(dirname(dirname(__file__)), "lib"))
new_paths.insert(0, os.path.sep.join([os.path.dirname(__file__), ta_name]))
sys.path = new_paths

# This is the path of the current script
bindir = os.path.dirname(os.path.realpath(os.path.dirname(__file__)))

# This is the path of the libraries
libdir = os.path.join(bindir, "lib")

# This is the name of the platform
platform = sys.platform

# This is the version of Python
python_version = "".join(str(x) for x in sys.version_info[:2])
