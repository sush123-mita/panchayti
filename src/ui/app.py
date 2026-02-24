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
│  │──────────────────│ │─────────────────────────────────││
│  │ DIRECT MESSAGES  │ │  [📎] [ Message #general … ] [→]││
│  │  ● Alice         │ └─────────────────────────────────┘│
│  │  ● Bob           │                                     │
│  │──────────────────│                                     │
│  │ ONLINE — 2       │                                     │
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

import base64
import html
import mimetypes
import os
import socket
import threading
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import Qt, QObject, pyqtSignal, pyqtSlot, QSize, QUrl
from PyQt6.QtGui import QFont, QTextCursor, QColor, QPalette, QIcon, QDesktopServices
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QTextBrowser,
    QLineEdit, QPushButton, QFrame, QSizePolicy,
    QInputDialog, QMessageBox, QApplication, QFileDialog,
)

from src.ui.styles import DARK_THEME

# Maximum file size for transfer (50 MB)
_MAX_FILE_SIZE = 50 * 1024 * 1024


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


def _human_size(nbytes: int) -> str:
    """Format byte count as a human-readable string."""
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}" if unit != "B" else f"{nbytes} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} TB"


# ------------------------------------------------------------------ #
#  MainWindow                                                          #
# ------------------------------------------------------------------ #

class MainWindow(QMainWindow):
    """
    Top-level window.  Wires UI <-> business-logic objects together.

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
        self._is_dm   = False                # True when viewing a DM channel

        # --- Thread-safe Qt signal bridge ---
        self._bridge = _Bridge()
        self._bridge.peer_connected.connect(self._on_peer_joined)
        self._bridge.peer_disconnected.connect(self._on_peer_left)
        self._bridge.message_received.connect(self._on_message)

        # Wire network callbacks -> bridge signals
        network.on_peer_connected    = self._bridge.peer_connected.emit
        network.on_peer_disconnected = self._bridge.peer_disconnected.emit
        network.on_error             = self._bridge.network_error.emit

        # Connect error signal
        self._bridge.network_error.connect(self._on_network_error)

        # Single render path: store_message -> broker listener -> bridge.emit -> _on_message
        message_broker.on_message(self._bridge.message_received.emit)

        # Track which channels have been loaded from file
        self._loaded_channels: set = set()

        # DM tracking: dm_channel_id -> {"peer_id": ..., "username": ...}
        self._active_dms: dict[str, dict] = {}

        self._build_ui()

        # Restore DM conversations from persisted history
        self._restore_dm_list()

        # Load persisted history for the initial channel and render it
        self._load_channel_history(self._channel)
        self._render_channel_history(self._channel)

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
        self._ch_list.setMaximumHeight(140)
        for ch in self._cfg.channels:
            item = QListWidgetItem(f"  # {ch}")
            item.setData(Qt.ItemDataRole.UserRole, ch)
            self._ch_list.addItem(item)
        if self._ch_list.count():
            self._ch_list.setCurrentRow(0)
        self._ch_list.currentItemChanged.connect(self._switch_channel)
        vbox.addWidget(self._ch_list)

        # --- Direct Messages section ---
        dm_lbl = QLabel("DIRECT MESSAGES")
        dm_lbl.setObjectName("section_label")
        vbox.addWidget(dm_lbl)

        self._dm_list = QListWidget()
        self._dm_list.setObjectName("channel_list")
        self._dm_list.setMaximumHeight(160)
        self._dm_list.currentItemChanged.connect(self._switch_dm)
        vbox.addWidget(self._dm_list)

        self._no_dm_hint = QLabel("  Click a peer to start DM")
        self._no_dm_hint.setStyleSheet(
            "color: #4f545c; font-size: 11px; padding: 4px 4px;"
        )
        vbox.addWidget(self._no_dm_hint)

        # --- Users section ---
        self._users_lbl = QLabel("ONLINE — 0")
        self._users_lbl.setObjectName("section_label")
        vbox.addWidget(self._users_lbl)

        self._user_list = QListWidget()
        self._user_list.setObjectName("channel_list")
        self._user_list.itemClicked.connect(self._on_peer_clicked)
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

        # Settings button
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

        # Chat message display (QTextBrowser for clickable links)
        self._chat = QTextBrowser()
        self._chat.setObjectName("chat_display")
        self._chat.setReadOnly(True)
        self._chat.setOpenLinks(False)
        self._chat.anchorClicked.connect(self._on_link_clicked)
        vbox.addWidget(self._chat, stretch=1)

        # Message input row
        input_row = QWidget()
        input_row.setObjectName("input_row")
        hb = QHBoxLayout(input_row)
        hb.setContentsMargins(16, 8, 16, 16)
        hb.setSpacing(8)

        # File attach button
        attach_btn = QPushButton("📎")
        attach_btn.setObjectName("attach_btn")
        attach_btn.setFixedSize(42, 42)
        attach_btn.setToolTip("Attach a file")
        attach_btn.setStyleSheet(
            "QPushButton#attach_btn { background: #40444b; color: #dcddde; "
            "font-size: 18px; border-radius: 8px; border: none; }"
            "QPushButton#attach_btn:hover { background: #4f545c; }"
        )
        attach_btn.clicked.connect(self._attach_file)
        hb.addWidget(attach_btn)

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
        # Avoid duplicates in online list
        for i in range(self._user_list.count()):
            if self._user_list.item(i).data(Qt.ItemDataRole.UserRole) == peer.peer_id:
                return

        # Create a blank list item sized to hold the custom widget
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, peer.peer_id)
        item.setData(Qt.ItemDataRole.DisplayRole, peer.username)
        item.setSizeHint(QSize(0, 52))
        self._user_list.addItem(item)

        # Attach the custom name + IP widget to this item
        row_widget = _PeerRow(peer.username, peer.ip)
        self._user_list.setItemWidget(item, row_widget)

        self._update_online_count()
        self._no_peers_hint.setVisible(False)

        # Auto-create a DM entry so the user can chat privately right away
        from src.core.messaging import dm_channel_id
        dm_ch = dm_channel_id(self._cfg.peer_id, peer.peer_id)
        self._ensure_dm_entry(dm_ch, peer.peer_id, peer.username)
        self._update_dm_status(peer.peer_id, online=True)

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
        if self._user_list.count() == 0:
            self._no_peers_hint.setVisible(True)

        # Grey out their DM entry
        self._update_dm_status(peer_id, online=False)

    @pyqtSlot(str)
    def _on_network_error(self, error_msg: str):
        """Show a network error (port taken, firewall, etc.) in the chat."""
        self._append_system(f"⚠ Network error: <b>{_escape(error_msg)}</b>")
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

        Called via:  broker.store_message -> listener -> bridge.emit -> here
        This is the ONLY place messages are rendered — both for our own
        sent messages and for messages from peers.
        """
        if message.type == "system":
            self._append_system(message.content)
            return

        # If a DM arrives for a channel not yet in the sidebar, add it
        if message.channel.startswith("dm:"):
            self._ensure_dm_entry(message.channel, message.sender_id,
                                  message.sender_name)

        if message.channel == self._channel:
            is_self = message.sender_id == self._cfg.peer_id
            if message.type == "file":
                self._append_file_msg(message, is_self=is_self)
            else:
                self._append_msg(message.sender_name, message.content,
                                 message.timestamp, is_self=is_self)

    # ---------------------------------------------------------------- #
    #  DM management                                                     #
    # ---------------------------------------------------------------- #

    def _on_peer_clicked(self, item: QListWidgetItem):
        """Single-click a peer in the online list to open their DM."""
        peer_id = item.data(Qt.ItemDataRole.UserRole)
        username = item.data(Qt.ItemDataRole.DisplayRole) or "Unknown"
        self._open_dm(peer_id, username)

    def _open_dm(self, peer_id: str, username: str):
        """Create or switch to a DM conversation with a peer."""
        from src.core.messaging import dm_channel_id
        dm_ch = dm_channel_id(self._cfg.peer_id, peer_id)

        self._ensure_dm_entry(dm_ch, peer_id, username)

        # Select the DM in the sidebar
        for i in range(self._dm_list.count()):
            if self._dm_list.item(i).data(Qt.ItemDataRole.UserRole) == dm_ch:
                self._ch_list.clearSelection()
                self._dm_list.setCurrentRow(i)
                break

    def _ensure_dm_entry(self, dm_ch: str, peer_id: str, username: str):
        """Add a DM entry to the sidebar if it doesn't exist yet."""
        if dm_ch in self._active_dms:
            return

        other_id = peer_id
        other_name = username
        if peer_id == self._cfg.peer_id:
            parts = dm_ch.split(":")[1:]
            for p in parts:
                if p != self._cfg.peer_id:
                    other_id = p
                    peer_obj = self._peers.get(p)
                    other_name = peer_obj.username if peer_obj else p[:8]
                    break

        self._active_dms[dm_ch] = {"peer_id": other_id, "username": other_name}

        # Check if peer is currently online
        is_online = self._peers.get(other_id) is not None
        dot = "●" if is_online else "○"
        dot_color = "#3ba55c" if is_online else "#72767d"

        item = QListWidgetItem(f"  {dot}  {other_name}")
        item.setData(Qt.ItemDataRole.UserRole, dm_ch)
        # Store peer_id in a secondary role for status updates
        item.setData(Qt.ItemDataRole.ToolTipRole, other_id)
        item.setForeground(QColor("#dcddde") if is_online else QColor("#72767d"))
        self._dm_list.addItem(item)
        self._no_dm_hint.setVisible(False)

    def _update_dm_status(self, peer_id: str, online: bool):
        """Update the green/grey dot and text colour on a DM entry."""
        dot = "●" if online else "○"
        color = QColor("#dcddde") if online else QColor("#72767d")
        for i in range(self._dm_list.count()):
            item = self._dm_list.item(i)
            if item.data(Qt.ItemDataRole.ToolTipRole) == peer_id:
                dm_ch = item.data(Qt.ItemDataRole.UserRole)
                info = self._active_dms.get(dm_ch, {})
                name = info.get("username", "DM")
                item.setText(f"  {dot}  {name}")
                item.setForeground(color)
                break

    def _restore_dm_list(self):
        """Populate the DM sidebar from persisted message history."""
        dm_channels = self._broker.get_dm_channels()
        for dm_ch in dm_channels:
            parts = dm_ch.split(":")[1:]
            other_id = None
            for p in parts:
                if p != self._cfg.peer_id:
                    other_id = p
                    break
            if not other_id:
                continue
            peer_obj = self._peers.get(other_id)
            username = peer_obj.username if peer_obj else other_id[:8]
            rows = self._broker._storage.get_history(dm_ch, limit=1) if self._broker._storage else []
            for row in rows:
                if row["sender_id"] != self._cfg.peer_id:
                    username = row["sender_name"]
                    break
            self._ensure_dm_entry(dm_ch, other_id, username)

    def _switch_dm(self, current, _previous):
        """Handle selecting a DM from the sidebar."""
        if not current:
            return
        dm_ch = current.data(Qt.ItemDataRole.UserRole)
        self._channel = dm_ch
        self._is_dm = True

        info = self._active_dms.get(dm_ch, {})
        peer_name = info.get("username", "DM")
        self._ch_header.setText(f"  @ {peer_name}")
        self._input.setPlaceholderText(f"Message @{peer_name}")

        # Deselect channel list
        self._ch_list.clearSelection()

        # Load and render history
        self._load_channel_history(dm_ch)
        self._render_channel_history(dm_ch)

    def _switch_channel(self, current, _previous):
        """Handle selecting a channel from the sidebar."""
        if not current:
            return
        ch = current.data(Qt.ItemDataRole.UserRole)
        self._channel = ch
        self._is_dm = False
        self._ch_header.setText(f"  # {ch}")
        self._input.setPlaceholderText(f"Message  # {ch}")

        # Deselect DM list
        self._dm_list.clearSelection()

        # Load persisted history from file if not yet loaded
        self._load_channel_history(ch)
        self._render_channel_history(ch)

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

        self._broker.store_message(msg)

        if self._is_dm:
            # Send only to the DM target peer
            target_id = self._dm_target_peer_id()
            if target_id:
                self._net.send_to(target_id, msg)
        else:
            self._net.broadcast(msg)

    def _dm_target_peer_id(self) -> Optional[str]:
        """Extract the other peer's ID from the current DM channel."""
        info = self._active_dms.get(self._channel)
        if info:
            return info["peer_id"]
        return None

    def _attach_file(self):
        """Open a file picker, encode the file, and send it."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select File to Send", "",
            "All Files (*);;Images (*.png *.jpg *.jpeg *.gif *.bmp *.webp)"
        )
        if not file_path:
            return

        path = Path(file_path)
        file_size = path.stat().st_size

        if file_size > _MAX_FILE_SIZE:
            QMessageBox.warning(
                self, "File Too Large",
                f"Maximum file size is {_human_size(_MAX_FILE_SIZE)}.\n"
                f"Selected file is {_human_size(file_size)}.",
            )
            return

        if file_size == 0:
            QMessageBox.warning(self, "Empty File", "Cannot send an empty file.")
            return

        # Read and base64-encode
        file_data = path.read_bytes()
        b64_data = base64.b64encode(file_data).decode("ascii")

        mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        from src.core.messaging import Message
        msg = Message.file(
            sender_id   = self._cfg.peer_id,
            sender_name = self._cfg.username,
            channel     = self._channel,
            file_name   = path.name,
            file_size   = file_size,
            file_type   = mime_type,
            content     = b64_data,
            file_path   = str(path),  # sender already has the file locally
        )

        self._broker.store_message(msg)

        if self._is_dm:
            target_id = self._dm_target_peer_id()
            if target_id:
                self._net.send_to(target_id, msg)
        else:
            self._net.broadcast(msg)

    def _add_peer_dialog(self):
        """Show a dialog for manually connecting to a peer by IP address."""
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

        try:
            socket.inet_aton(ip)
        except socket.error:
            QMessageBox.warning(
                self, "Invalid IP",
                f"'{ip}' is not a valid IPv4 address.",
            )
            return

        self._append_system(f"Connecting to {_escape(ip)}:{port} ...")

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
            self._net.send_presence("online")
            self._append_system(f"Username changed to <b>{_escape(new_name.strip())}</b>.")

    def _on_link_clicked(self, url: QUrl):
        """Handle clicks on file links in chat — open with system default."""
        path = url.toLocalFile()
        if path and Path(path).exists():
            QDesktopServices.openUrl(url)

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

    def _append_file_msg(self, message, is_self: bool = False):
        """Render a file transfer message with optional inline image preview."""
        colour = "#5865f2" if is_self else "#00b0f4"
        time   = _fmt_time(message.timestamp)
        fname  = _escape(message.file_name or "file")
        fsize  = _human_size(message.file_size or 0)
        ftype  = message.file_type or ""
        fpath  = message.file_path or ""

        # Build the file info HTML
        img_html = ""
        if ftype.startswith("image/") and fpath and Path(fpath).exists():
            # Inline image preview — use file:// URL
            file_url = QUrl.fromLocalFile(fpath).toString()
            img_html = (
                f'<div style="margin: 4px 0;">'
                f'  <img src="{file_url}" width="300" '
                f'    style="border-radius: 8px; max-width: 300px;" />'
                f'</div>'
            )

        # Make filename a clickable link if file exists on disk
        if fpath and Path(fpath).exists():
            file_url = QUrl.fromLocalFile(fpath).toString()
            file_link = (
                f'<a href="{file_url}" style="color: #00aff4; text-decoration: none;">'
                f'📄 {fname}</a>'
            )
        else:
            file_link = f'📄 {fname}'

        html_block = (
            f'<div style="margin: 2px 16px 6px 16px;">'
            f'  <span style="color:{colour}; font-weight:bold;">'
            f'    {_escape(message.sender_name)}'
            f'  </span>'
            f'  <span style="color:#72767d; font-size:11px; margin-left:8px;">'
            f'    {time}'
            f'  </span>'
            f'{img_html}'
            f'  <div style="background: #2f3136; border-radius: 8px; '
            f'    padding: 8px 12px; margin-top: 4px; display: inline-block;">'
            f'    {file_link}'
            f'    <span style="color:#72767d; font-size:11px; margin-left:8px;">'
            f'      {fsize}'
            f'    </span>'
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
    #  History loading                                                   #
    # ---------------------------------------------------------------- #

    def _load_channel_history(self, channel: str):
        """Load persisted messages from JSON into broker cache (once per channel)."""
        if channel in self._loaded_channels:
            return
        self._loaded_channels.add(channel)
        self._broker.load_history_from_db(channel)

    def _render_channel_history(self, channel: str):
        """Clear the chat display and render all cached messages for a channel."""
        self._chat.clear()
        messages = self._broker.get_history(channel)
        for msg in messages:
            if msg.type == "system":
                self._append_system(msg.content)
            elif msg.type == "file":
                is_self = msg.sender_id == self._cfg.peer_id
                self._append_file_msg(msg, is_self=is_self)
            else:
                is_self = msg.sender_id == self._cfg.peer_id
                self._append_msg(msg.sender_name, msg.content, msg.timestamp, is_self=is_self)
        db_count = len([m for m in messages if m.type in ("text", "file")])
        if db_count > 0:
            self._append_system(f"Loaded <b>{db_count}</b> message(s) from history")

    # ---------------------------------------------------------------- #
    #  Window events                                                     #
    # ---------------------------------------------------------------- #

    def closeEvent(self, event):
        self._disc.stop()
        self._net.stop()
        if self._broker._storage:
            self._broker._storage.close()
        event.accept()
