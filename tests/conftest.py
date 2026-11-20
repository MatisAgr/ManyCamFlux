import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import ManyCamFlux  # noqa: E402,F401  preloads msvcp140 before any test imports PyQt5 (see ManyCamFlux.py)
