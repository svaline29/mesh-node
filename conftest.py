import os
import sys

# Ensure the repo root (containing routing.py, observer.py, etc.) is importable
# regardless of where pytest is invoked from.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
