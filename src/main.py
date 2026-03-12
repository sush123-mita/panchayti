"""
main.py — Application entry point.

Wires together all components and starts the Qt event loop.
"""

import sys
import os


def main():
    from PyQt6.QtWidgets import QApplication, QInputDialog
    from PyQt6.QtCore import Qt

    app = QApplication(sys.argv)
    app.setApplicationName("LocalDiscord")
    app.setApplicationDisplayName("LocalDiscord")

    # Import everything after QApplication is created
    from src.utils.logger  import setup_logger
    from src.utils.config  import Config
    from src.core.peer     import PeerRegistry
    from src.core.encryption import EncryptionManager
    from src.core.network  import NetworkManager
    from src.core.discovery import DiscoveryManager
    from src.core.messaging import MessageBroker
    from src.ui.app        import MainWindow
    from src.ui.styles     import DARK_THEME

    setup_logger()
    app.setStyleSheet(DARK_THEME)

    config = Config()

    # --- First-run: ask for a username ---
    default_name = config.username
    if not default_name or default_name in ("User",
            os.environ.get("USERNAME", ""),
            os.environ.get("USER", "")):
        name, ok = QInputDialog.getText(
            None,
            "Welcome to LocalDiscord",
            "Choose a display name for the network:\n"
            "(You can change it later from the settings)",
            text=default_name or "User",
        )
        if ok and name.strip():
            config.username = name.strip()

    # --- Instantiate and wire up components ---
    from src.core.storage import StorageManager

    encryption     = EncryptionManager()
    peer_registry  = PeerRegistry()
    storage        = StorageManager()   # SQLite persistence (~/.localdiscord/messages.db)
    message_broker = MessageBroker(encryption, peer_registry, storage=storage)
    network        = NetworkManager(encryption, peer_registry, message_broker, config)
    discovery      = DiscoveryManager(peer_registry, network, config)

    # --- Create and show the window ---
    window = MainWindow(network, discovery, peer_registry, message_broker, config)
    window.show()

    # --- Start networking (after window is shown so signals are connected) ---
    window.start_network()

    sys.exit(app.exec())
