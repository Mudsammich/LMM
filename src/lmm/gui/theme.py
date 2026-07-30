"""The vaporwave theme: one palette, one stylesheet, applied app-wide.

Everything visual lives here so the aesthetic can be tuned (or swapped
out) without hunting through every tab file.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

# -- palette -----------------------------------------------------

BG_DARK = "#170b2e"      # main window background - deep night purple
BG_PANEL = "#20123f"     # tab pane / card background
BG_FIELD = "#2b1650"     # inputs, table cells
BG_FIELD_ALT = "#331a5e"  # alternating rows / hover fields

NEON_PINK = "#ff6ec7"
NEON_PINK_DIM = "#c94fa0"
NEON_CYAN = "#2ee6d6"
NEON_CYAN_DIM = "#1fa89c"
NEON_PURPLE = "#b967ff"
SUNSET_ORANGE = "#ff9e6d"
SUNSET_GOLD = "#ffd371"

TEXT_MAIN = "#f4eeff"
TEXT_MUTED = "#a996c9"
TEXT_DISABLED = "#6b5a8c"

BORDER = NEON_CYAN
BORDER_DIM = "#4a2f7a"

FONT_FAMILY = '"Ubuntu", "Noto Sans", "DejaVu Sans", "Segoe UI", sans-serif'
MONO_FONT_FAMILY = '"Ubuntu Mono", "DejaVu Sans Mono", "Liberation Mono", monospace'


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setPalette(_build_palette())
    app.setFont(QFont(FONT_FAMILY.split(",")[0].strip('"'), 10))
    app.setStyleSheet(STYLESHEET)


def _build_palette() -> QPalette:
    """A matching QPalette so native dialogs (file pickers, message boxes)
    don't flash white before the stylesheet takes over."""
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG_DARK))
    pal.setColor(QPalette.WindowText, QColor(TEXT_MAIN))
    pal.setColor(QPalette.Base, QColor(BG_FIELD))
    pal.setColor(QPalette.AlternateBase, QColor(BG_FIELD_ALT))
    pal.setColor(QPalette.Text, QColor(TEXT_MAIN))
    pal.setColor(QPalette.Button, QColor(BG_PANEL))
    pal.setColor(QPalette.ButtonText, QColor(TEXT_MAIN))
    pal.setColor(QPalette.Highlight, QColor(NEON_PINK))
    pal.setColor(QPalette.HighlightedText, QColor(BG_DARK))
    pal.setColor(QPalette.ToolTipBase, QColor(BG_PANEL))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT_MAIN))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
    pal.setColor(QPalette.Disabled, QPalette.Text, QColor(TEXT_DISABLED))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(TEXT_DISABLED))
    return pal


STYLESHEET = f"""
QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_MAIN};
    font-family: {FONT_FAMILY};
    selection-background-color: {NEON_PINK};
    selection-color: {BG_DARK};
}}

QMainWindow {{
    background-color: {BG_DARK};
}}

QLabel {{
    background: transparent;
}}

QLabel[role="section"] {{
    color: {NEON_CYAN};
    font-weight: 700;
    letter-spacing: 1px;
}}

QLabel[role="status"] {{
    color: {SUNSET_GOLD};
    font-weight: 600;
}}

/* -- tabs -------------------------------------------------------- */

QTabWidget::pane {{
    background-color: {BG_PANEL};
    border: 2px solid {BORDER_DIM};
    border-radius: 6px;
    top: -1px;
}}

QTabBar::tab {{
    background-color: {BG_PANEL};
    color: {TEXT_MUTED};
    border: 2px solid {BORDER_DIM};
    border-bottom: none;
    padding: 8px 18px;
    margin-right: 3px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 600;
    letter-spacing: 1px;
}}

QTabBar::tab:selected {{
    background-color: {BG_FIELD};
    color: {NEON_PINK};
    border: 2px solid {NEON_PINK};
    border-bottom: none;
}}

QTabBar::tab:hover:!selected {{
    color: {NEON_CYAN};
    border-color: {NEON_CYAN_DIM};
}}

/* -- buttons -------------------------------------------------------- */

QPushButton {{
    background-color: {BG_FIELD};
    color: {NEON_CYAN};
    border: 2px solid {NEON_CYAN_DIM};
    border-radius: 6px;
    padding: 6px 14px;
    font-weight: 600;
}}

QPushButton:hover {{
    background-color: {NEON_CYAN};
    color: {BG_DARK};
    border-color: {NEON_CYAN};
}}

QPushButton:pressed {{
    background-color: {NEON_PINK};
    border-color: {NEON_PINK};
    color: {BG_DARK};
}}

QPushButton:disabled {{
    background-color: {BG_PANEL};
    color: {TEXT_DISABLED};
    border-color: {BORDER_DIM};
}}

QPushButton[role="primary"] {{
    background-color: {BG_FIELD};
    color: {NEON_PINK};
    border: 2px solid {NEON_PINK};
}}

QPushButton[role="primary"]:hover {{
    background-color: {NEON_PINK};
    color: {BG_DARK};
}}

/* -- inputs -------------------------------------------------------- */

QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background-color: {BG_FIELD};
    color: {TEXT_MAIN};
    border: 2px solid {BORDER_DIM};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {NEON_PINK};
}}

QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
    border: 2px solid {NEON_CYAN};
}}

QComboBox::drop-down {{
    border: none;
    width: 22px;
}}

QComboBox QAbstractItemView {{
    background-color: {BG_FIELD};
    color: {TEXT_MAIN};
    border: 2px solid {NEON_CYAN};
    selection-background-color: {NEON_PINK};
    selection-color: {BG_DARK};
}}

QCheckBox::indicator {{
    width: 15px;
    height: 15px;
    border: 2px solid {NEON_CYAN_DIM};
    border-radius: 3px;
    background-color: {BG_FIELD};
}}

QCheckBox::indicator:checked {{
    background-color: {NEON_PINK};
    border-color: {NEON_PINK};
}}

/* Radio buttons: same look as checkboxes but round, for the FOMOD
   installer's "choose exactly one" option groups. */
QRadioButton::indicator {{
    width: 15px;
    height: 15px;
    border: 2px solid {NEON_CYAN_DIM};
    border-radius: 9px;
    background-color: {BG_FIELD};
}}

QRadioButton::indicator:checked {{
    background-color: {NEON_PINK};
    border-color: {NEON_PINK};
}}

/* An option a FOMOD has ruled out has to *look* unavailable, not just say
   so - the label alone is easy to miss in a long list. */
QCheckBox:disabled, QRadioButton:disabled {{
    color: {TEXT_DISABLED};
}}

QCheckBox::indicator:disabled, QRadioButton::indicator:disabled {{
    border-color: {BORDER_DIM};
    background-color: {BG_PANEL};
}}

/* -- tables / lists -------------------------------------------------------- */

QTableWidget, QListWidget {{
    background-color: {BG_PANEL};
    alternate-background-color: {BG_FIELD};
    gridline-color: {BORDER_DIM};
    border: 2px solid {BORDER_DIM};
    border-radius: 6px;
    color: {TEXT_MAIN};
}}

QTableWidget::item:selected, QListWidget::item:selected {{
    background-color: {NEON_PURPLE};
    color: {TEXT_MAIN};
}}

QHeaderView::section {{
    background-color: {BG_FIELD};
    color: {NEON_PINK};
    padding: 6px;
    border: 1px solid {BORDER_DIM};
    font-weight: 700;
    letter-spacing: 1px;
}}

/* -- progress / scroll -------------------------------------------------------- */

QProgressBar {{
    background-color: {BG_FIELD};
    border: 2px solid {BORDER_DIM};
    border-radius: 5px;
    text-align: center;
    color: {TEXT_MAIN};
}}

QProgressBar::chunk {{
    border-radius: 3px;
    background-color: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {NEON_PURPLE}, stop:0.5 {NEON_PINK}, stop:1 {SUNSET_GOLD}
    );
}}

QScrollBar:vertical {{
    background: {BG_DARK};
    width: 12px;
    margin: 0;
}}

QScrollBar::handle:vertical {{
    background: {NEON_PURPLE};
    border-radius: 5px;
    min-height: 24px;
}}

QScrollBar::handle:vertical:hover {{
    background: {NEON_PINK};
}}

QScrollBar:horizontal {{
    background: {BG_DARK};
    height: 12px;
}}

QScrollBar::handle:horizontal {{
    background: {NEON_PURPLE};
    border-radius: 5px;
    min-width: 24px;
}}

QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0;
    width: 0;
}}

/* -- misc -------------------------------------------------------- */

QMessageBox, QDialog {{
    background-color: {BG_DARK};
}}

QMenu {{
    background-color: {BG_PANEL};
    color: {TEXT_MAIN};
    border: 2px solid {NEON_CYAN_DIM};
}}

QMenu::item:selected {{
    background-color: {NEON_PINK};
    color: {BG_DARK};
}}

QToolTip {{
    background-color: {BG_PANEL};
    color: {NEON_CYAN};
    border: 1px solid {NEON_CYAN};
    padding: 4px;
}}
"""
