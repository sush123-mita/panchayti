"""
storage.py — JSON file-based persistence for chat messages.

Stores all messages in ~/.localdiscord/messages.json as a flat list.
On startup the file is loaded into memory. Every new message is
appended and the file is flushed from a background writer thread
so the networking layer is never blocked.

Deduplication is by message UUID — duplicates are silently ignored.
"""

import json
import queue
import threading
from pathlib import Path
from typing import List, Optional

from src.utils.logger import get_logger

_log = get_logger("storage")


class StorageManager:
    """
    JSON-file message persistence.

    - write_message()  → enqueues to a background writer thread (thread-safe).
    - get_history()    → reads from the in-memory list (fast, no disk I/O).
    - On init the JSON file is loaded into memory.
    - The writer thread appends new messages and flushes the whole file.
    """

    def __init__(self, file_path: Optional[str] = None):
        if file_path is None:
            data_dir = Path.home() / ".localdiscord"
            data_dir.mkdir(parents=True, exist_ok=True)
            file_path = str(data_dir / "messages.json")

        self._file_path = file_path

        # ---- Load existing messages from disk ----
        self._messages: List[dict] = self._load_file()
        self._seen_ids: set = {m["id"] for m in self._messages}
        self._lock = threading.Lock()

        # ---- Background writer thread ----
        self._write_queue: queue.Queue = queue.Queue()
        self._writer_thread = threading.Thread(
            target=self._writer_loop,
            daemon=True,
            name="json-writer",
        )
        self._writer_thread.start()

        _log.info(
            f"StorageManager ready: {file_path} "
            f"({len(self._messages)} messages loaded)"
        )

    # ---- File I/O ---------------------------------------------------- #

    def _load_file(self) -> List[dict]:
        """Read the JSON file from disk. Returns [] if missing or corrupt."""
        path = Path(self._file_path)
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            _log.warning("messages.json is not a list — starting fresh")
            return []
        except (json.JSONDecodeError, OSError) as e:
            _log.error(f"Failed to load {self._file_path}: {e}")
            return []

    def _flush_to_disk(self):
        """Write the full message list to disk (atomic-ish via write+flush)."""
        try:
            with self._lock:
                snapshot = list(self._messages)
            with open(self._file_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=1)
        except OSError as e:
            _log.error(f"Failed to write {self._file_path}: {e}")

    # ---- Writer thread ----------------------------------------------- #

    def _writer_loop(self):
        """Drain the write queue and flush after each new message."""
        while True:
            item = self._write_queue.get()
            if item is None:
                break  # shutdown sentinel
            try:
                msg_dict = item
                with self._lock:
                    if msg_dict["id"] in self._seen_ids:
                        continue  # duplicate — skip
                    self._seen_ids.add(msg_dict["id"])
                    self._messages.append(msg_dict)
                self._flush_to_disk()
            except Exception as e:
                _log.error(f"Writer error: {e}")

    # ---- Public API -------------------------------------------------- #

    def write_message(self, msg_dict: dict):
        """
        Enqueue a message for writing. Thread-safe, non-blocking.

        msg_dict keys: id, type, sender_id, sender_name,
                       channel, timestamp, content.
        """
        self._write_queue.put(msg_dict)

    def get_history(self, channel: str, limit: int = 200) -> List[dict]:
        """
        Return the most recent messages for a channel.
        Reads from the in-memory list (no disk I/O).
        """
        with self._lock:
            channel_msgs = [m for m in self._messages if m["channel"] == channel]
        # Already in chronological order; take the tail
        return channel_msgs[-limit:]

    def get_dm_channels(self) -> List[str]:
        """Return distinct DM channel IDs that have stored messages."""
        with self._lock:
            return list({m["channel"] for m in self._messages
                         if m["channel"].startswith("dm:")})

    def close(self):
        """Shut down the writer thread and do a final flush."""
        self._write_queue.put(None)  # sentinel
        self._writer_thread.join(timeout=5)
        self._flush_to_disk()
        _log.info("StorageManager closed")
