"""
app.py — Main application window.

Layout (mimicking Discord)
--------------------------
┌──────────────────────────────────────────────────────────┐
│  ┌──────────────────┐ ┌─────────────────────────────────┐│
│  │  Server name hdr │ │   # channel-name   header bar   ││
│  │──────────────────│ │─────────────────────────────────││
│  │ TEXT CHANNELS    │ │                                  ││
│  │  # general  ◄   │ │   chat messages (scrollable)    ││
│  │  # random       │ │                                  ││
│  │  # announcements│ │─────────────────────────────────││
│  │──────────────────│ │  [  Message #general …    ] [→] ││
│  │ ONLINE — 2       │ └─────────────────────────────────┘│
│  │  🟢 Alice        │                                     │
│  │  🟢 Bob          │                                     │
│  │──────────────────│                                     │
│  │  🟢 You (bottom) │                                     │
│  └──────────────────┘                                     │
└──────────────────────────────────────────────────────────┘

Thread safety
-------------
All network callbacks arrive on worker threads.  They post data to the
Qt main thread via Qt signals (NetworkBridge).  Never touch QWidget
objects directly from non-main threads.
"""

import html
import socket
import threading
from typing import Optional

from PyQt6.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, QSize
from PyQt6.QtGui import QFont, QTextCursor, QColor, QPalette, QIcon
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QTextEdit,
    QLineEdit, QPushButton, QFrame, QSizePolicy,
    QInputDialog, QMessageBox, QApplication,
)

from src.ui.styles import DARK_THEME


# ------------------------------------------------------------------ #
#  _PeerRow — custom widget shown for each online peer               #
# ------------------------------------------------------------------ #

class _PeerRow(QWidget):
    """
    One row in the online-users list.

    Layout:
        ●  Alice                ← green dot  +  bold username
           192.168.1.42         ← dimmed IP address below the name
    """

    def __init__(self, username: str, ip: str, parent=None):
        super().__init__(parent)
        self.setToolTip(f"{username}  —  {ip}")

        row = QHBoxLayout(self)
        row.setContentsMargins(10, 5, 8, 5)
        row.setSpacing(8)

        # ── Green online dot ──────────────────────────────────────
        dot = QLabel("●")
        dot.setFixedWidth(14)
        dot.setStyleSheet("color: #3ba55c; font-size: 13px; padding-top: 2px;")
        row.addWidget(dot, alignment=Qt.AlignmentFlag.AlignTop)

        # ── Name + IP stacked ─────────────────────────────────────
        info = QWidget()
        info.setStyleSheet("background: transparent;")
        col = QVBoxLayout(info)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)

        name_lbl = QLabel(_escape(username))
        name_lbl.setStyleSheet(
            "color: #dcddde; font-weight: bold; font-size: 13px; background: transparent;"
        )
        col.addWidget(name_lbl)

        ip_lbl = QLabel(ip)
        ip_lbl.setStyleSheet(
            "color: #72767d; font-size: 10px; background: transparent;"
        )
        col.addWidget(ip_lbl)

        row.addWidget(info, stretch=1)


# ------------------------------------------------------------------ #
#  Signal bridge — safely cross the thread boundary                    #
# ------------------------------------------------------------------ #

class _Bridge(QObject):
    """
    Worker threads call these signals; Qt delivers them on the main
    thread where all UI updates happen.
    """
    peer_connected    = pyqtSignal(object)   # Peer
    peer_disconnected = pyqtSignal(str)      # peer_id
    message_received  = pyqtSignal(object)   # Message
    network_error     = pyqtSignal(str)      # error message string


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #

def _fmt_time(iso: str) -> str:
    """Extract HH:MM from an ISO timestamp string."""
    try:
        return iso[11:16]
    except Exception:
        return ""


def _escape(text: str) -> str:
    """HTML-escape user content before inserting into the chat display."""
    return html.escape(text)


# ------------------------------------------------------------------ #
#  MainWindow                                                          #
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    """
    Top-level window.  Wires UI ↔ business-logic objects together.

    Parameters
    ----------
    network        : NetworkManager
    discovery      : DiscoveryManager
    peer_registry  : PeerRegistry
    message_broker : MessageBroker
    config         : Config
    """

    def __init__(self, network, discovery, peer_registry, message_broker, config):
        super().__init__()
        self._net     = network
        self._disc    = discovery
        self._peers   = peer_registry
        self._broker  = message_broker
        self._cfg     = config
        self._channel = config.channels[0]   # currently viewed channel

        # --- Thread-safe Qt signal bridge ---
        self._bridge = _Bridge()
        self._bridge.peer_connected.connect(self._on_peer_joined)
        self._bridge.peer_disconnected.connect(self._on_peer_left)
        self._bridge.message_received.connect(self._on_message)

        # Wire network callbacks → bridge signals
        network.on_peer_connected    = self._bridge.peer_connected.emit
        network.on_peer_disconnected = self._bridge.peer_disconnected.emit
        network.on_error             = self._bridge.network_error.emit
        # on_message_received is intentionally NOT wired here.
        # The broker listener below is the single render path for ALL messages
        # (own sent + received from peers).  Wiring on_message_received too
        # would fire the signal twice for every incoming message → doubled chat.

        # Connect error signal
        self._bridge.network_error.connect(self._on_network_error)

        # Single render path: store_message → broker listener → bridge.emit → _on_message
        message_broker.on_message(self._bridge.message_received.emit)

        self._build_ui()

    # ---------------------------------------------------------------- #
    #  UI construction                                                   #
    # ---------------------------------------------------------------- #

    def _build_ui(self):
        self.setWindowTitle(self._cfg.app_name)
        self.setMinimumSize(900, 600)
        self.resize(
            self._cfg.get("ui.window_width",  1100),
            self._cfg.get("ui.window_height", 700),
        )
        self.setStyleSheet(DARK_THEME)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        layout.addWidget(self._make_sidebar())
        layout.addWidget(self._make_chat_panel(), stretch=1)

        # Kick off with a welcome note
        self._append_system(
            f"Welcome, <b>{_escape(self._cfg.username)}</b>! "
            "Searching for peers on the local network…"
        )

    # ---- Sidebar ----------------------------------------------------- #

    def _make_sidebar(self) -> QWidget:
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(240)

        vbox = QVBoxLayout(sidebar)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Server name header
        header = QLabel(f" {self._cfg.app_name}")
        header.setObjectName("server_name")
        header.setFixedHeight(48)
        header.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        vbox.addWidget(header)

        # --- Channels section ---
        ch_lbl = QLabel("TEXT CHANNELS")
        ch_lbl.setObjectName("section_label")
        vbox.addWidget(ch_lbl)

        self._ch_list = QListWidget()
        self._ch_list.setObjectName("channel_list")
        self._ch_list.setMaximumHeight(180)
        for ch in self._cfg.channels:
            item = QListWidgetItem(f"  # {ch}")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self._ch_list.addItem(item)
        if self._ch_list.count():
            self._ch_list.setCurrentRow(0)
        self._ch_list.currentItemChanged.connect(self._switch_channel)
        vbox.addWidget(self._ch_list)

        # --- Users section ---
        self._users_lbl = QLabel("ONLINE — 0")
        self._users_lbl.setObjectName("section_label")
        vbox.addWidget(self._users_lbl)

        self._user_list = QListWidget()
        self._user_list.setObjectName("channel_list")
        vbox.addWidget(self._user_list, stretch=1)

        # Hint shown when no peers are connected yet
        self._no_peers_hint = QLabel(
            "  Searching for peers…\n"
            "  Make sure both devices\n"
            "  are on the same network."
        )
        self._no_peers_hint.setStyleSheet(
            "color: #4f545c; font-size: 11px; padding: 6px 4px;"
        )
        self._no_peers_hint.setWordWrap(True)
        vbox.addWidget(self._no_peers_hint)

        # --- Manual peer connection button ---
        add_peer_btn = QPushButton("+ Add Peer")
        add_peer_btn.setObjectName("add_peer_btn")
        add_peer_btn.setFixedHeight(32)
        add_peer_btn.setToolTip("Connect to a peer by IP address (for cross-subnet)")
        add_peer_btn.setStyleSheet(
            "QPushButton { background: #40444b; color: #8e9297; font-size: 12px; "
            "             margin: 4px 8px; border-radius: 4px; }"
            "QPushButton:hover { background: #4f545c; color: #dcddde; }"
        )
        add_peer_btn.clicked.connect(self._add_peer_dialog)
        vbox.addWidget(add_peer_btn)

        # --- Current-user bar ---
        user_bar = QWidget()
        user_bar.setObjectName("user_bar")
        user_bar.setFixedHeight(52)
        hb = QHBoxLayout(user_bar)
        hb.setContentsMargins(10, 0, 10, 0)

        name_lbl = QLabel(f"🟢  {_escape(self._cfg.username)}")
        name_lbl.setObjectName("own_username")
        hb.addWidget(name_lbl)
        hb.addStretch()

        # Settings button (placeholder for future)
        settings_btn = QPushButton("⚙")
        settings_btn.setFixedSize(28, 28)
        settings_btn.setToolTip("Settings")
        settings_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #8e9297; font-size: 16px; border: none; }"
            "QPushButton:hover { color: #dcddde; }"
        )
        settings_btn.clicked.connect(self._open_settings)
        hb.addWidget(settings_btn)

        vbox.addWidget(user_bar)
        return sidebar

    # ---- Chat panel -------------------------------------------------- #

    def _make_chat_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("chat_panel")
        vbox = QVBoxLayout(panel)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)

        # Channel header bar
        self._ch_header = QLabel(f"  # {self._channel}")
        self._ch_header.setObjectName("channel_header")
        self._ch_header.setFixedHeight(48)
        self._ch_header.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        vbox.addWidget(self._ch_header)

        # Chat message display
        self._chat = QTextEdit()
        self._chat.setObjectName("chat_display")
        self._chat.setReadOnly(True)
        vbox.addWidget(self._chat, stretch=1)

        # Message input row
        input_row = QWidget()
        input_row.setObjectName("input_row")
        hb = QHBoxLayout(input_row)
        hb.setContentsMargins(16, 8, 16, 16)
        hb.setSpacing(8)

        self._input = QLineEdit()
        self._input.setObjectName("message_input")
        self._input.setPlaceholderText(f"Message  # {self._channel}")
        self._input.returnPressed.connect(self._send)
        hb.addWidget(self._input, stretch=1)

        send_btn = QPushButton("↵ Send")
        send_btn.setFixedHeight(42)
        send_btn.setToolTip("Send message (Enter)")
        send_btn.clicked.connect(self._send)
        hb.addWidget(send_btn)

        vbox.addWidget(input_row)
        return panel

    # ---------------------------------------------------------------- #
    #  Network lifecycle                                                 #
    # ---------------------------------------------------------------- #

    def start_network(self):
        """Call after show() — starts discovery and network threads."""
        self._net.start()
        self._disc.start()

    # ---------------------------------------------------------------- #
    #  Qt slots (always on main thread)                                  #
    # ---------------------------------------------------------------- #

    @pyqtSlot(object)
    def _on_peer_joined(self, peer):
        # Avoid duplicates
        for i in range(self._user_list.count()):
            if self._user_list.item(i).data(Qt.ItemDataRole.UserRole) == peer.peer_id:
                return

        # Create a blank list item sized to hold the custom widget
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, peer.peer_id)
        # Store username in display role so _on_peer_left can read it
        item.setData(Qt.ItemDataRole.DisplayRole, peer.username)
        item.setSizeHint(QSize(0, 52))          # height for two-line row
        self._user_list.addItem(item)

        # Attach the custom name + IP widget to this item
        row_widget = _PeerRow(peer.username, peer.ip)
        self._user_list.setItemWidget(item, row_widget)

        self._update_online_count()
        # Hide the "searching…" hint once we have at least one peer
        self._no_peers_hint.setVisible(False)
        self._append_system(
            f"<b>{_escape(peer.username)}</b> connected "
            f"<span style='color:#72767d;'>({_escape(peer.ip)})</span>"
        )

    @pyqtSlot(str)
    def _on_peer_left(self, peer_id: str):
        for i in range(self._user_list.count()):
            item = self._user_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == peer_id:
                username = item.data(Qt.ItemDataRole.DisplayRole) or "Unknown"
                self._user_list.takeItem(i)
                self._append_system(f"<b>{_escape(username)}</b> disconnected.")
                break
        self._update_online_count()
        # Show the hint again if the list is now empty
        if self._user_list.count() == 0:
            self._no_peers_hint.setVisible(True)

    @pyqtSlot(str)
    def _on_network_error(self, error_msg: str):
        """Show a network error (port taken, firewall, etc.) in the chat."""
        self._append_system(f"⚠ Network error: <b>{_escape(error_msg)}</b>")
        # Also update the hint text so the user knows what happened
        self._no_peers_hint.setText(
            f"  ⚠ {error_msg}\n\n"
            "  Check that port 55001 (TCP)\n"
            "  and 55000 (UDP) are open\n"
            "  in your firewall."
        )
        self._no_peers_hint.setStyleSheet(
            "color: #ed4245; font-size: 11px; padding: 6px 4px;"
        )

    @pyqtSlot(object)
    def _on_message(self, message):
        """
        Render one message in the chat display.

        Called via:  broker.store_message → listener → bridge.emit → here
        This is the ONLY place messages are rendered — both for our own
        sent messages (main-thread signal, delivered synchronously) and
        for messages from peers (worker-thread signal, delivered via the
        Qt event queue on the main thread).
        """
        if message.type == "system":
            self._append_system(message.content)
            return
        if message.channel == self._channel:
            is_self = message.sender_id == self._cfg.peer_id
            self._append_msg(message.sender_name, message.content,
                             message.timestamp, is_self=is_self)

    # ---------------------------------------------------------------- #
    #  User actions                                                      #
    # ---------------------------------------------------------------- #

    def _send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()

        from src.core.messaging import Message
        msg = Message.text(
            sender_id   = self._cfg.peer_id,
            sender_name = self._cfg.username,
            channel     = self._channel,
            content     = text,
        )

        # store_message fires the broker listener → bridge.message_received.emit
        # → _on_message → _append_msg.  Because this runs on the main thread
        # the signal is delivered synchronously, so the message appears
        # immediately — no second direct call to _append_msg needed.
        self._broker.store_message(msg)
        self._net.broadcast(msg)

    def _switch_channel(self, current, _previous):
        if not current:
            return
        ch = current.data(Qt.ItemDataRole.UserRole)
        self._channel = ch
        self._ch_header.setText(f"  # {ch}")
        self._input.setPlaceholderText(f"Message  # {ch}")

        # Reload history for the selected channel
        self._chat.clear()
        for msg in self._broker.get_history(ch):
            if msg.type == "system":
                self._append_system(msg.content)
            else:
                is_self = msg.sender_id == self._cfg.peer_id
                self._append_msg(msg.sender_name, msg.content, msg.timestamp, is_self=is_self)

    def _add_peer_dialog(self):
        """
        Show a dialog for manually connecting to a peer by IP address.

        This is the fallback when automatic discovery (broadcast/multicast/
        mDNS) cannot reach a peer — e.g. across restricted subnets or VPNs.
        """
        text, ok = QInputDialog.getText(
            self,
            "Add Peer",
            "Enter the peer's IP address (and optionally :port):\n"
            "Examples:  192.168.20.5   or   10.0.1.100:55001",
            text="",
        )
        if not ok or not text.strip():
            return

        text = text.strip()

        # Parse IP and optional port.
        if ":" in text:
            parts = text.rsplit(":", 1)
            ip = parts[0]
            try:
                port = int(parts[1])
            except ValueError:
                QMessageBox.warning(
                    self, "Invalid Port",
                    f"'{parts[1]}' is not a valid port number.",
                )
                return
        else:
            ip   = text
            port = self._cfg.tcp_port

        # Basic IP validation.
        try:
            socket.inet_aton(ip)
        except socket.error:
            QMessageBox.warning(
                self, "Invalid IP",
                f"'{ip}' is not a valid IPv4 address.",
            )
            return

        self._append_system(f"Connecting to {_escape(ip)}:{port} ...")

        # Run the connection attempt in a background thread so the UI
        # doesn't freeze while waiting for the TCP handshake.
        def _connect():
            success = self._net.connect_to_peer(ip, port)
            if not success:
                self._bridge.network_error.emit(
                    f"Could not connect to {ip}:{port}. "
                    "Make sure the peer is running and the firewall "
                    f"allows TCP port {port}."
                )

        threading.Thread(
            target=_connect, daemon=True, name=f"manual-dial-{ip}",
        ).start()

    def _open_settings(self):
        new_name, ok = QInputDialog.getText(
            self, "Settings", "Change your username:",
            text=self._cfg.username,
        )
        if ok and new_name.strip():
            self._cfg.username = new_name.strip()
            # Broadcast updated presence so others see the new name
            self._net.send_presence("online")
            self._append_system(f"Username changed to <b>{_escape(new_name.strip())}</b>.")

    # ---------------------------------------------------------------- #
    #  Chat display helpers                                              #
    # ---------------------------------------------------------------- #

    def _append_msg(self, sender: str, content: str, ts: str, is_self: bool = False):
        """Append one formatted chat message bubble."""
        colour = "#5865f2" if is_self else "#00b0f4"
        time   = _fmt_time(ts)
        html_block = (
            f'<div style="margin: 2px 16px 6px 16px;">'
            f'  <span style="color:{colour}; font-weight:bold;">'
            f'    {_escape(sender)}'
            f'  </span>'
            f'  <span style="color:#72767d; font-size:11px; margin-left:8px;">'
            f'    {time}'
            f'  </span>'
            f'  <div style="color:#dcddde; margin-top:2px;">'
            f'    {_escape(content)}'
            f'  </div>'
            f'</div>'
        )
        self._chat.append(html_block)
        self._scroll_to_bottom()

    def _append_system(self, html_content: str):
        """Append a dimmed, centred system notification."""
        html_block = (
            f'<div style="text-align:center; margin:6px 0; color:#72767d; font-size:12px;">'
            f'  ─── {html_content} ───'
            f'</div>'
        )
        self._chat.append(html_block)
        self._scroll_to_bottom()

    def _scroll_to_bottom(self):
        cur = self._chat.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        self._chat.setTextCursor(cur)

    def _update_online_count(self):
        n = self._user_list.count()
        self._users_lbl.setText(f"ONLINE — {n}")

    # ---------------------------------------------------------------- #
    #  Window events                                                     #
    # ---------------------------------------------------------------- #

    def closeEvent(self, event):
        self._disc.stop()
        self._net.stop()
        event.accept()
