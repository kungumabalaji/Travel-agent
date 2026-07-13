"""
Adds both backend services to sys.path so their modules import directly
(e.g. `import tool`, `import luggage_api`) without turning them into
installable packages just for testing.

Requires each service's own requirements already installed (tool.py needs
google-adk for its ToolContext type hint) — see the root README's Testing
section.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend" / "chatagent"))
sys.path.insert(0, str(ROOT / "backend" / "voiceagent"))
