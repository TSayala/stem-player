"""Dark theme styling for PySide6."""

# Colour palette (One Dark inspired)
BG_DARKEST  = "#1B1D23"
BG_DARK     = "#21252B"
BG_MID      = "#282C34"
BG_LIGHT    = "#2C313A"
BG_HOVER    = "#3E4451"
FG          = "#ABB2BF"
FG_DIM      = "#5C6370"
ACCENT      = "#61AFEF"
ACCENT_HOVER= "#528BCC"
RED         = "#E06C75"
GREEN       = "#98C379"
YELLOW      = "#E5C07B"
PURPLE      = "#C678DD"
CYAN        = "#56B6C2"
BORDER      = "#3E4451"

STYLESHEET = f"""
/* ── global ─────────────────────────────────────────────── */
QWidget {{
    background-color: {BG_MID};
    color: {FG};
    font-family: 'Segoe UI', 'Inter', sans-serif;
}}
QMainWindow {{
    background-color: {BG_DARKEST};
}}

/* ── buttons ────────────────────────────────────────────── */
QPushButton {{
    background-color: {BG_LIGHT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 6px 14px;
    color: {FG};
    min-height: 24px;
}}
QPushButton:hover {{
    background-color: {BG_HOVER};
}}
QPushButton:pressed {{
    background-color: {ACCENT};
    color: #fff;
}}
QPushButton:checked {{
    background-color: {ACCENT};
    color: #fff;
    border-color: {ACCENT_HOVER};
}}

/* ── sliders ────────────────────────────────────────────── */
QSlider::groove:horizontal {{
    background: {BG_DARK};
    height: 6px;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}}
QSlider::groove:vertical {{
    background: {BG_DARK};
    width: 6px;
    border-radius: 3px;
}}
QSlider::handle:vertical {{
    background: {ACCENT};
    width: 14px;
    height: 14px;
    margin: 0 -4px;
    border-radius: 7px;
}}

/* ── labels ─────────────────────────────────────────────── */
QLabel {{
    background: transparent;
    padding: 0;
}}

/* ── group-box ──────────────────────────────────────────── */
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 8px;
    margin-top: 12px;
    padding-top: 14px;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
}}

/* ── scroll area ────────────────────────────────────────── */
QScrollArea {{
    border: none;
    background: transparent;
}}
QScrollBar:vertical {{
    background: {BG_DARK};
    width: 8px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical {{
    background: {BG_HOVER};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}

/* ── combo box ──────────────────────────────────────────── */
QComboBox {{
    background: {BG_LIGHT};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 4px 8px;
    min-height: 24px;
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox QAbstractItemView {{
    background: {BG_DARK};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT};
    font-size: 10pt;
}}

/* ── progress bar ───────────────────────────────────────── */
QProgressBar {{
    background: {BG_DARK};
    border: none;
    border-radius: 4px;
    height: 8px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 4px;
}}

/* ── tool tip ───────────────────────────────────────────── */
QToolTip {{
    background: {BG_DARK};
    color: {FG};
    border: 1px solid {BORDER};
    padding: 4px;
    border-radius: 4px;
}}
"""
