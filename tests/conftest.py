import subprocess
import sys
import time

import pytest

on_windows = pytest.mark.skipif(
    sys.platform != "win32", reason="Windows backend test"
)

_TK_APP = """
import tkinter as tk
root = tk.Tk()
root.title("GhostdriverTestWindow")
tk.Button(root, text="Expand All").pack()
tk.Button(root, text="Collapse All").pack()
tk.Entry(root).pack()
container = tk.Frame(root)
container.pack()
tk.Button(container, text="Nested Action").pack()
root.geometry("300x200")
root.mainloop()
"""


@pytest.fixture
def tk_target():
    """Launch a Tk window in a subprocess and yield its pid.

    Cross-process is the case that matters: reading text and enumerating
    windows behave differently for windows we do not own.
    """
    proc = subprocess.Popen([sys.executable, "-c", _TK_APP])
    try:
        deadline = time.time() + 10
        from ghostdriver.backends.windows.enumerate import top_level_windows
        while time.time() < deadline:
            if top_level_windows(proc.pid):
                break
            time.sleep(0.1)
        else:
            raise RuntimeError("Tk target did not create a window in time")
        time.sleep(0.3)  # let child widgets finish realizing
        yield proc.pid
    finally:
        proc.terminate()
        proc.wait(timeout=5)
