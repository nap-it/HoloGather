"""Strict hl2ss imports from bundled vendor path.

This project requires hl2ss to be present under:
`libs/hololens_sensor_streaming/viewer`.

Upstream hl2ss files import each other as top-level modules (for example,
`import hl2ss`, `import hl2ss_dp`, `import hl2ss_mx`). To keep this stable,
we prepend the viewer directory to `sys.path` before importing any hl2ss
modules.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Ensure the vendor viewer directory is on module search path so top-level
# sibling imports inside hl2ss modules resolve correctly.
_ROOT_DIR = Path(__file__).resolve().parents[2]
_VIEWER_DIR = _ROOT_DIR / "libs" / "hololens_sensor_streaming" / "viewer"
_viewer_dir_str = str(_VIEWER_DIR)
if _viewer_dir_str not in sys.path:
    sys.path.insert(0, _viewer_dir_str)

# Import base siblings that other modules require as top-level names.
import hl2ss as hl2ss  # type: ignore
import hl2ss_dp as hl2ss_dp  # type: ignore
import hl2ss_mx as hl2ss_mx  # type: ignore

# Register aliases early so downstream imports resolve correctly.
sys.modules.setdefault("hl2ss", hl2ss)
sys.modules.setdefault("hl2ss_dp", hl2ss_dp)
sys.modules.setdefault("hl2ss_mx", hl2ss_mx)

# Import dependent modules after aliases are in place.
import hl2ss_lnm as hl2ss_lnm  # type: ignore
import hl2ss_mp as hl2ss_mp  # type: ignore

# Register additional aliases for consistency.
sys.modules.setdefault("hl2ss_lnm", hl2ss_lnm)
sys.modules.setdefault("hl2ss_mp", hl2ss_mp)

__all__ = ["hl2ss", "hl2ss_dp", "hl2ss_mx", "hl2ss_lnm", "hl2ss_mp"]
