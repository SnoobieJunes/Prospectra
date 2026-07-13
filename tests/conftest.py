# 2026-07-13 (P0): Force Qt's offscreen platform before any Qt import so UI tests run headless
# (CI, SSH sessions) on all three OSes. Real-display launch is verified separately via
# `prospectra --smoke`.

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
