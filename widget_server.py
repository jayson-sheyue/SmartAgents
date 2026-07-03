#!/usr/bin/env python3
"""兼容入口：请优先使用 python local_node/widget_server.py"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "local_node" / "widget_server.py"), run_name="__main__")
