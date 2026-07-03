#!/usr/bin/env python3
"""
兼容入口（shim）：从项目根目录运行 python server.py 时，实际执行 local_node/server.py。

【为什么需要？】
  文档和旧习惯可能写「python server.py」；真实实现已移到 local_node/ 目录。
  本文件不做任何业务逻辑，只用 runpy 转调，避免你改命令习惯。
"""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).parent / "local_node" / "server.py"), run_name="__main__")
