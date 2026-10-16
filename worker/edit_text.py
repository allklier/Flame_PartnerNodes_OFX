"""The prompt editor (decision 13), run by the plugin's Edit button while Flame waits.

  <runtime python> -I -B edit_text.py <file> <title>

Exit 0: the file holds the edited text. 1: cancelled. 2: no editor (zenity on Linux, the Command
Line Tools' swiftc on macOS). The window itself is in cpo/oslayer.py.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cpo import oslayer  # noqa: E402

if __name__ == "__main__":
    sys.exit(oslayer.edit_text(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "Edit"))
