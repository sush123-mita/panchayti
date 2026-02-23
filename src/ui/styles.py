"""
styles.py — Discord-inspired dark theme (Qt Style Sheet).

Colours:
  #202225  darkest  — background of sidebars' lowest areas
  #2f3136  dark     — sidebar panels
  #36393f  medium   — main chat background
  #40444b  lighter  — input fields
  #dcddde  text     — primary text
  #8e9297  muted    — secondary / placeholder text
  #5865f2  blurple  — accent (self-messages, buttons, selections)
  #3ba55c  green    — online indicator
"""

DARK_THEME = """
/* ================================================================== */
/*  Base                                                               */
/* ================================================================== */
QMainWindow, QDialog {
    background-color: #36393f;
    color: #dcddde;
}

QWidget {
    background-color: #36393f;
    color: #dcddde;
    font-family: 'Segoe UI', 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px;
}

/* ================================================================== */
/*  Sidebar                                                            */
/* ================================================================== */
QWidget#sidebar {
    background-color: #2f3136;
}

QLabel#server_name {
    background-color: #2f3136;
    color: #ffffff;
    font-size: 15px;
    font-weight: bold;
    padding: 0 12px;
    border-bottom: 1px solid #202225;
}

QLabel#section_label {
    background-color: #2f3136;
    color: #8e9297;
    font-size: 11px;
    font-weight: bold;
    padding: 16px 8px 4px 16px;
    letter-spacing: 0.8px;
}

/* ================================================================== */
/*  List widgets (channels + users)                                    */
/* ================================================================== */
QListWidget {
    background-color: #2f3136;
    border: none;
    outline: none;
    padding: 4px 0;
}

QListWidget::item {
    color: #8e9297;
    padding: 6px 8px 6px 12px;
    border-radius: 4px;
    margin: 1px 4px;
}

/* Items that use setItemWidget() (peer rows) need no padding —
   the widget itself supplies its own margins.               */
QListWidget::item[hasWidget="true"] {
    padding: 0;
}

QListWidget::item:hover {
    background-color: #393c43;
    color: #dcddde;
}

QListWidget::item:selected {
    background-color: #393c43;
    color: #ffffff;
}

/* ================================================================== */
/*  Chat area                                                          */
/* ================================================================== */
QWidget#chat_panel {
    background-color: #36393f;
}

QLabel#channel_header {
    background-color: #36393f;
    color: #ffffff;
    font-size: 15px;
    font-weight: bold;
    padding: 0 16px;
    border-bottom: 1px solid #202225;
}

QTextEdit#chat_display {
    background-color: #36393f;
    border: none;
    color: #dcddde;
    font-size: 14px;
    padding: 8px 0;
    selection-background-color: #5865f2;
}

/* ================================================================== */
/*  Message input                                                      */
/* ================================================================== */
QWidget#input_row {
    background-color: #36393f;
    padding: 0 16px 20px 16px;
}

QLineEdit#message_input {
    background-color: #40444b;
    border: none;
    border-radius: 8px;
    color: #dcddde;
    font-size: 14px;
    padding: 11px 16px;
    selection-background-color: #5865f2;
}

QLineEdit#message_input:focus {
    background-color: #484c52;
}

/* ================================================================== */
/*  User info bar (bottom of sidebar)                                  */
/* ================================================================== */
QWidget#user_bar {
    background-color: #292b2f;
}

QLabel#own_username {
    color: #ffffff;
    font-weight: bold;
    font-size: 13px;
}

QLabel#own_tag {
    color: #8e9297;
    font-size: 12px;
}

/* ================================================================== */
/*  Buttons                                                            */
/* ================================================================== */
QPushButton {
    background-color: #5865f2;
    color: #ffffff;
    border: none;
    border-radius: 4px;
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
    background-color: #ed4245;
}

QPushButton#danger_btn:hover {
    background-color: #c03537;
}

/* ================================================================== */
/*  Scrollbars                                                         */
/* ================================================================== */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #202225;
    border-radius: 4px;
    min-height: 30px;
}

QScrollBar::handle:vertical:hover {
    background: #2f3136;
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
    background-color: #36393f;
    color: #dcddde;
}

QInputDialog QLabel, QMessageBox QLabel {
    color: #dcddde;
    font-size: 14px;
}

QInputDialog QLineEdit {
    background-color: #40444b;
    border: 1px solid #202225;
    border-radius: 4px;
    color: #dcddde;
    padding: 6px 10px;
}

QDialogButtonBox QPushButton {
    min-width: 80px;
}

/* ================================================================== */
/*  Tooltip                                                            */
/* ================================================================== */
QToolTip {
    background-color: #18191c;
    color: #dcddde;
    border: 1px solid #040405;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: 12px;
}
"""
