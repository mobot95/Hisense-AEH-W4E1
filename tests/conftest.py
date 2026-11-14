import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Home Assistant 2026.11 installs its probatio-backed voluptuous compatibility
# layer at package import time. Load it before test modules import voluptuous.
import homeassistant  # noqa: E402, F401
