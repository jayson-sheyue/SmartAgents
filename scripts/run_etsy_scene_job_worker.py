#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Background worker process for Etsy scene-swap async jobs."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from domains.etsy.etsy_tools import run_scene_job_worker


def main() -> int:
    if len(sys.argv) < 2:
        return 2
    job_id = (sys.argv[1] or "").strip()
    if not job_id:
        return 2
    return run_scene_job_worker(job_id)


if __name__ == "__main__":
    raise SystemExit(main())
