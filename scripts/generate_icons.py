#!/usr/bin/env python3
"""Rasterizes src/lmm/assets/icon.svg into the fixed-size PNGs the
hicolor icon theme needs. Re-run this after editing the source SVG.

    python scripts/generate_icons.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

SIZES = (16, 24, 32, 48, 64, 128, 256)
REPO_ROOT = Path(__file__).resolve().parent.parent
SVG_PATH = REPO_ROOT / "src" / "lmm" / "assets" / "icon.svg"
ICONS_DIR = REPO_ROOT / "packaging" / "icons" / "hicolor"


def main() -> int:
    app = QApplication.instance() or QApplication([])
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        print(f"error: {SVG_PATH} is not a valid SVG", file=sys.stderr)
        return 1

    for size in SIZES:
        out_dir = ICONS_DIR / f"{size}x{size}" / "apps"
        out_dir.mkdir(parents=True, exist_ok=True)
        image = QImage(QSize(size, size), QImage.Format_ARGB32_Premultiplied)
        image.fill(0)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        renderer.render(painter)
        painter.end()
        out_path = out_dir / "lmm.png"
        image.save(str(out_path))
        print(f"wrote {out_path.relative_to(REPO_ROOT)}")

    scalable_dir = ICONS_DIR / "scalable" / "apps"
    scalable_dir.mkdir(parents=True, exist_ok=True)
    scalable_path = scalable_dir / "lmm.svg"
    scalable_path.write_text(SVG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"wrote {scalable_path.relative_to(REPO_ROOT)}")

    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
