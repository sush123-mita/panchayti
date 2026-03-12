"""
styles.py — Discord-inspired dark theme (Qt Style Sheet).

Colours:
  #1e1f22  darkest  — background of sidebars' lowest areas
  #2b2d31  dark     — sidebar panels
  #313338  medium   — main chat background
  #383a40  lighter  — input fields
  #f2f3f5  text     — primary text (brighter)
  #949ba4  muted    — secondary / placeholder text
  #5865f2  blurple  — accent (self-messages, buttons, selections)
  #23a559  green    — online indicator
"""

DARK_THEME = """
/* ================================================================== */
/*  Base                                                               */
/* ================================================================== */
QMainWindow, QDialog {
    background-color: #313338;
    color: #f2f3f5;
}

QWidget {
    background-color: #313338;
    color: #f2f3f5;
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
}

/* ================================================================== */
/*  Sidebar                                                            */
/* ================================================================== */
QWidget#sidebar {
    background-color: #2b2d31;
}

QLabel#server_name {
    background-color: #2b2d31;
    color: #f2f3f5;
    font-size: 16px;
    font-weight: bold;
    padding: 0 14px;
    border-bottom: 2px solid #1e1f22;
}

QLabel#section_label {
    background-color: #2b2d31;
    color: #949ba4;
    font-size: 11px;
    font-weight: bold;
    padding: 18px 8px 4px 16px;
    letter-spacing: 1px;
    text-transform: uppercase;
}

/* ================================================================== */
/*  List widgets (channels + users)                                    */
/* ================================================================== */
QListWidget {
    background-color: #2b2d31;
    border: none;
    outline: none;
    padding: 2px 0;
}

QListWidget::item {
    color: #949ba4;
    padding: 7px 8px 7px 12px;
    border-radius: 6px;
    margin: 1px 8px;
}

/* Items that use setItemWidget() (peer rows) need no padding —
   the widget itself supplies its own margins.               */
QListWidget::item[hasWidget="true"] {
    padding: 0;
}

QListWidget::item:hover {
    background-color: #35373c;
    color: #f2f3f5;
}

QListWidget::item:selected {
    background-color: #404249;
    color: #ffffff;
}

/* ================================================================== */
/*  Chat area                                                          */
/* ================================================================== */
QWidget#chat_panel {
    background-color: #313338;
}

QLabel#channel_header {
    background-color: #313338;
    color: #f2f3f5;
    font-size: 16px;
    font-weight: bold;
    padding: 0 16px;
    border-bottom: 2px solid #1e1f22;
}

QTextEdit#chat_display, QTextBrowser#chat_display {
    background-color: #313338;
    border: none;
    color: #f2f3f5;
    font-size: 14px;
    padding: 8px 4px;
    selection-background-color: #5865f2;
}

/* ================================================================== */
/*  Message input                                                      */
/* ================================================================== */
QWidget#input_row {
    background-color: #313338;
    padding: 0 16px 16px 16px;
}

QLineEdit#message_input {
    background-color: #383a40;
    border: none;
    border-radius: 10px;
    color: #f2f3f5;
    font-size: 14px;
    padding: 12px 18px;
    selection-background-color: #5865f2;
}

QLineEdit#message_input:focus {
    background-color: #404249;
}

/* ================================================================== */
/*  User info bar (bottom of sidebar)                                  */
/* ================================================================== */
QWidget#user_bar {
    background-color: #232428;
    border-top: 1px solid #1e1f22;
}

QLabel#own_username {
    color: #f2f3f5;
    font-weight: bold;
    font-size: 13px;
}

QLabel#own_tag {
    color: #949ba4;
    font-size: 12px;
}

/* ================================================================== */
/*  Buttons                                                            */
/* ================================================================== */
QPushButton {
    background-color: #5865f2;
    color: #ffffff;
    border: none;
    border-radius: 6px;
    padding: 8px 18px;
    font-weight: bold;
    font-size: 13px;
}

QPushButton:hover {
    background-color: #4752c4;
}

QPushButton:pressed {
    background-color: #3c45a5;
}

QPushButton#danger_btn {
    background-color: #da373c;
}

QPushButton#danger_btn:hover {
    background-color: #a12d2f;
}

/* ================================================================== */
/*  Scrollbars                                                         */
/* ================================================================== */
QScrollBar:vertical {
    background: transparent;
    width: 6px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #1e1f22;
    border-radius: 3px;
    min-height: 40px;
}

QScrollBar::handle:vertical:hover {
    background: #404249;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}

QScrollBar:horizontal {
    height: 0;   /* hide horizontal scrollbar in most panels */
}

/* ================================================================== */
/*  Dialogs / Input dialog                                             */
/* ================================================================== */
QInputDialog, QMessageBox {
    background-color: #313338;
    color: #f2f3f5;
}

QInputDialog QLabel, QMessageBox QLabel {
    color: #f2f3f5;
    font-size: 14px;
}

QInputDialog QLineEdit {
    background-color: #1e1f22;
    border: 1px solid #404249;
    border-radius: 6px;
    color: #f2f3f5;
    padding: 8px 12px;
}

QInputDialog QLineEdit:focus {
    border: 1px solid #5865f2;
}

QDialogButtonBox QPushButton {
    min-width: 90px;
}

/* ================================================================== */
/*  Tooltip                                                            */
/* ================================================================== */
QToolTip {
    background-color: #111214;
    color: #f2f3f5;
    border: 1px solid #1e1f22;
    padding: 6px 10px;
    border-radius: 6px;
    font-size: 12px;
}

/* ================================================================== */
/*  Context menus                                                      */
/* ================================================================== */
QMenu {
    background-color: #111214;
    color: #f2f3f5;
    border: 1px solid #1e1f22;
    border-radius: 6px;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #5865f2;
    color: #ffffff;
}

QMenu::separator {
    height: 1px;
    background-color: #2b2d31;
    margin: 4px 8px;
}
"""
