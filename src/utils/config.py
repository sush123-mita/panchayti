"""
config.py — Application configuration manager.

Loads from config/default_config.json, then overlays user-specific
settings stored in ~/.localdiscord/config.json.
Generates a persistent peer_id (UUID) on first run.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Any


class Config:
    # Paths
    _DEFAULT = Path(__file__).parent.parent.parent / "config" / "default_config.json"
    _USER_DIR = Path.home() / ".localdiscord"
    _USER_FILE = _USER_DIR / "config.json"

    def __init__(self):
        self._data = self._load()

        # --- Assign a persistent peer ID on first run ---
        if "peer_id" not in self._data:
            self._data["peer_id"] = str(uuid.uuid4())
            self._save()

        # --- Default username from OS environment ---
        if "username" not in self._data:
            self._data["username"] = (
                os.environ.get("USERNAME")          # Windows
                or os.environ.get("USER")           # Unix
                or "User"
            )
            self._save()

    # ------------------------------------------------------------------ #
    #  Load / save                                                         #
    # ------------------------------------------------------------------ #
    def _load(self) -> dict:
        data: dict = {}
        if self._DEFAULT.exists():
            with open(self._DEFAULT, encoding="utf-8") as f:
                data = json.load(f)

        if self._USER_FILE.exists():
            with open(self._USER_FILE, encoding="utf-8") as f:
                user = json.load(f)
            data = _deep_merge(data, user)

        return data

    def _save(self):
        self._USER_DIR.mkdir(parents=True, exist_ok=True)
        with open(self._USER_FILE, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    # ------------------------------------------------------------------ #
    #  Dot-path accessor / mutator                                         #
    # ------------------------------------------------------------------ #
    def get(self, key: str, default: Any = None) -> Any:
        """Access nested keys with dot notation: config.get('network.tcp_port')"""
        node = self._data
        for part in key.split("."):
            if not isinstance(node, dict):
                return default
            node = node.get(part)
        return node if node is not None else default

    def set(self, key: str, value: Any):
        """Set a nested key with dot notation and persist."""
        parts = key.split(".")
        node = self._data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
        self._save()

    # ------------------------------------------------------------------ #
    #  Convenience properties                                              #
    # ------------------------------------------------------------------ #
    @property
    def peer_id(self) -> str:
        return self._data["peer_id"]

    @property
    def username(self) -> str:
        return self._data.get("username", "User")

    @username.setter
    def username(self, value: str):
        self._data["username"] = value
        self._save()

    @property
    def tcp_port(self) -> int:
        return self.get("network.tcp_port", 55001)

    @property
    def udp_port(self) -> int:
        return self.get("network.udp_discovery_port", 55000)

    @property
    def discovery_interval(self) -> int:
        return self.get("network.discovery_interval_sec", 5)

    @property
    def multicast_group(self) -> str:
        return self.get("network.multicast_group", "239.192.55.1")

    @property
    def multicast_ttl(self) -> int:
        return self.get("network.multicast_ttl", 4)

    @property
    def relay_host(self) -> str:
        return self.get("network.relay_host", "")

    @property
    def relay_port(self) -> int:
        return self.get("network.relay_port", 55002)

    @property
    def channels(self) -> list[str]:
        return self.get("channels", ["general"])

    @property
    def app_name(self) -> str:
        return self.get("app_name", "LocalDiscord")


# ------------------------------------------------------------------ #
#  Helpers                                                             #
# ------------------------------------------------------------------ #
def _deep_merge(base: dict, override: dict) -> dict:
    result = base.copy()
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result
