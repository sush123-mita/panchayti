#!/usr/bin/env python3
"""
create_deb.py — Build localdiscord_1.0.0_all.deb using only Python stdlib.

Works on Windows, macOS, and Linux — no dpkg-deb / fakeroot needed.

A .deb file is an ar(1) archive containing three members in order:
  1. debian-binary   — plain text "2.0\n"
  2. control.tar.gz  — DEBIAN/ maintainer scripts + control metadata
  3. data.tar.gz     — the actual filesystem tree (usr/...)
"""

import gzip
import hashlib
import io
import os
import tarfile
import time
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
PKG_NAME    = "localdiscord"
PKG_VERSION = "1.0.4"
PKG_ARCH    = "all"

ROOT     = Path(__file__).parent.resolve()
DIST     = ROOT / "dist"
DEB_OUT  = DIST / f"{PKG_NAME}_{PKG_VERSION}_{PKG_ARCH}.deb"
DEBIAN   = ROOT / "debian"

MTIME = int(time.time())   # same timestamp for every entry


# ── ar archive helpers ────────────────────────────────────────────────────────
#
# ar entry header layout (exactly 60 bytes):
#   Identifier        16 bytes  ASCII, space-padded
#   Modification time 12 bytes  decimal string, space-padded
#   Owner ID           6 bytes  decimal string, space-padded
#   Group ID           6 bytes  decimal string, space-padded
#   File mode          8 bytes  octal string, space-padded
#   File size         10 bytes  decimal string, space-padded (actual bytes, before padding)
#   Magic              2 bytes  0x60 0x0A  (grave + newline)
# Then file data, padded to even length with 0x0A if necessary.

AR_GLOBAL_MAGIC = b"!<arch>\n"
AR_ENTRY_MAGIC  = b"`\n"

def _ar_entry(name: str, data: bytes) -> bytes:
    actual_size = len(data)
    # Pad data to an even number of bytes (ar requirement)
    padded_data = data + (b"\n" if actual_size % 2 else b"")

    header = (
        f"{name:<16}"         # identifier  (16)
        f"{MTIME:<12}"        # mtime       (12)
        f"{'0':<6}"           # uid         ( 6)
        f"{'0':<6}"           # gid         ( 6)
        f"{'100644':<8}"      # mode        ( 8)  octal notation
        f"{actual_size:<10}"  # file size   (10)
    ).encode("ascii") + AR_ENTRY_MAGIC   # magic (2)  → total = 60 bytes

    assert len(header) == 60, f"ar header must be 60 bytes, got {len(header)}"
    return header + padded_data


def build_ar(members: list[tuple[str, bytes]]) -> bytes:
    """Assemble an ar archive from (name, data) pairs."""
    out = bytearray(AR_GLOBAL_MAGIC)
    for name, data in members:
        out += _ar_entry(name, data)
    return bytes(out)


# ── tar helpers ───────────────────────────────────────────────────────────────

def _tar_info(name: str, size: int = 0, mode: int = 0o644,
              is_dir: bool = False) -> tarfile.TarInfo:
    info          = tarfile.TarInfo(name=name)
    info.mtime    = MTIME
    info.uid      = 0
    info.gid      = 0
    info.uname    = "root"
    info.gname    = "root"
    info.mode     = mode
    if is_dir:
        info.type = tarfile.DIRTYPE
    else:
        info.type = tarfile.REGTYPE
        info.size = size
    return info


def build_tar_gz(entries: list[tuple]) -> bytes:
    """
    Build a gzip-compressed tar from a list of:
        (arcname, content_bytes_or_None, unix_mode, is_dir)
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as tar:
        for (arcname, content, mode, is_dir) in entries:
            if is_dir:
                tar.addfile(_tar_info(arcname, mode=mode or 0o755, is_dir=True))
            else:
                data = content or b""
                tar.addfile(
                    _tar_info(arcname, size=len(data), mode=mode or 0o644),
                    io.BytesIO(data),
                )
    return buf.getvalue()


# ── Line-ending normalisation ─────────────────────────────────────────────────

def lf(data: bytes) -> bytes:
    """Ensure Unix LF line endings — critical for shell scripts on Linux."""
    return data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


# ── Collect data entries (the filesystem tree) ────────────────────────────────

def collect_data() -> tuple[list, dict]:
    """
    Returns:
        entries  : list of (arcname, content, mode, is_dir) for data.tar.gz
        md5sums  : {path_without_dot_slash: md5hex}
    """
    entries: list  = []
    md5sums: dict  = {}
    seen_dirs: set = set()

    def ensure_dir(arc: str):
        """Add a directory entry (and all parents) if not already added."""
        arc = arc.rstrip("/")
        parts = arc.split("/")
        for depth in range(2, len(parts) + 1):   # skip "." prefix alone
            d = "/".join(parts[:depth])
            if d not in seen_dirs:
                seen_dirs.add(d)
                entries.append((d, None, 0o755, True))

    def add_file(arc: str, content: bytes, mode: int = 0o644):
        parent = "/".join(arc.split("/")[:-1])
        ensure_dir(parent)
        entries.append((arc, content, mode, False))
        key = arc.lstrip("./")
        md5sums[key] = hashlib.md5(content).hexdigest()

    # ── /usr/bin/localdiscord  (launcher shell script) ──────────────────────
    ensure_dir("./usr/bin")
    launcher_src = (DEBIAN / "launcher.sh").read_bytes()
    add_file(f"./usr/bin/{PKG_NAME}", lf(launcher_src), 0o755)

    # ── /usr/lib/localdiscord/  (Python application source) ─────────────────
    ensure_dir(f"./usr/lib/{PKG_NAME}")

    # src/ tree (exclude __pycache__ and .pyc)
    src_root = ROOT / "src"
    for path in sorted(src_root.rglob("*")):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        rel = path.relative_to(ROOT)
        arc = f"./usr/lib/{PKG_NAME}/{rel.as_posix()}"
        add_file(arc, path.read_bytes())

    # run.py  +  requirements.txt  +  relay_server.py
    for fname in ("run.py", "requirements.txt", "relay_server.py"):
        p = ROOT / fname
        if p.exists():
            add_file(f"./usr/lib/{PKG_NAME}/{fname}", p.read_bytes())

    # config/
    cfg_root = ROOT / "config"
    for path in sorted(cfg_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        arc = f"./usr/lib/{PKG_NAME}/{rel.as_posix()}"
        add_file(arc, path.read_bytes())

    # ── /usr/share/applications/ ─────────────────────────────────────────────
    ensure_dir("./usr/share/applications")
    desktop = (DEBIAN / "localdiscord.desktop").read_bytes()
    add_file(f"./usr/share/applications/{PKG_NAME}.desktop", lf(desktop))

    # ── /usr/share/doc/localdiscord/ ─────────────────────────────────────────
    ensure_dir(f"./usr/share/doc/{PKG_NAME}")

    copyright_data = (DEBIAN / "copyright").read_bytes()
    add_file(f"./usr/share/doc/{PKG_NAME}/copyright", lf(copyright_data))

    # changelog must be gzip-compressed (Debian policy §12.7)
    changelog_raw = (DEBIAN / "changelog").read_bytes()
    add_file(
        f"./usr/share/doc/{PKG_NAME}/changelog.Debian.gz",
        gzip.compress(lf(changelog_raw), compresslevel=9),
    )

    return entries, md5sums


# ── Build control.tar.gz ──────────────────────────────────────────────────────

def build_control_tar(installed_kb: int, md5sums: dict) -> bytes:
    entries = []

    def add(name, content: bytes, mode: int = 0o644):
        entries.append((name, content, mode, False))

    # control  (metadata)
    control_raw = (DEBIAN / "control").read_bytes().decode()
    control_raw = control_raw.replace(
        "Installed-Size: PLACEHOLDER",
        f"Installed-Size: {installed_kb}",
    )
    add("./control", lf(control_raw.encode()))

    # md5sums
    md5_text = "".join(
        f"{digest}  {path}\n"
        for path, digest in sorted(md5sums.items())
    )
    add("./md5sums", md5_text.encode())

    # maintainer scripts (must be executable → 0o755)
    for script in ("postinst", "prerm", "postrm"):
        p = DEBIAN / script
        if p.exists():
            add(f"./{script}", lf(p.read_bytes()), mode=0o755)

    return build_tar_gz(entries)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 62)
    print(f"  Building  {DEB_OUT.name}")
    print("=" * 62)

    DIST.mkdir(parents=True, exist_ok=True)

    # 1. Collect data files
    print("\n[1/4] Collecting application files...")
    data_entries, md5sums = collect_data()

    file_count = sum(1 for e in data_entries if not e[3])
    dir_count  = sum(1 for e in data_entries if e[3])
    total_bytes = sum(len(e[1]) for e in data_entries if not e[3] and e[1])

    print(f"      {file_count} files  +  {dir_count} directories")
    print(f"      ~{total_bytes / 1024:.0f} KB of source data")

    installed_kb = max(1, total_bytes // 1024)

    # 2. Build data.tar.gz
    print("\n[2/4] Compressing data.tar.gz ...")
    data_tar = build_tar_gz(data_entries)
    print(f"      {len(data_tar) / 1024:.1f} KB compressed")

    # 3. Build control.tar.gz
    print("\n[3/4] Compressing control.tar.gz ...")
    ctrl_tar = build_control_tar(installed_kb, md5sums)
    print(f"      {len(ctrl_tar) / 1024:.1f} KB compressed")

    # 4. Assemble the ar archive (.deb)
    print("\n[4/4] Assembling .deb (ar archive)...")
    deb_bytes = build_ar([
        ("debian-binary",  b"2.0\n"),
        ("control.tar.gz", ctrl_tar),
        ("data.tar.gz",    data_tar),
    ])

    DEB_OUT.write_bytes(deb_bytes)
    size_mb = len(deb_bytes) / (1024 * 1024)

    print(f"\n{'=' * 62}")
    print(f"  Done!  {DEB_OUT}")
    print(f"  Size:  {size_mb:.2f} MB")
    print(f"{'=' * 62}")
    print()
    print("  Copy this file to your Ubuntu machine, then run:")
    print(f"    sudo apt install ./{DEB_OUT.name}")
    print()


if __name__ == "__main__":
    main()
