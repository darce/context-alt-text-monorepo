"""
Recognition Tests Module
"""

# Test configuration and shared fixtures can go here
import pytest
import sys
from pathlib import Path

# Add the project root to the path for imports
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# Configure pytest for the recognition module
pytest_plugins = []
