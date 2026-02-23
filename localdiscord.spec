# -*- mode: python ; coding: utf-8 -*-
#
# localdiscord.spec — PyInstaller build specification.
#
# Build a standalone single-file executable:
#   Windows:  pyinstaller localdiscord.spec
#   macOS:    pyinstaller localdiscord.spec
#   Linux:    pyinstaller localdiscord.spec
#
# The output will be in dist/localdiscord[.exe]

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('config/',  'config/'),
        ('assets/',  'assets/'),
    ],
    hiddenimports=[
        # cryptography backends
        'cryptography.hazmat.backends.openssl',
        'cryptography.hazmat.primitives.asymmetric.x25519',
        'cryptography.hazmat.primitives.ciphers.aead',
        'cryptography.hazmat.primitives.kdf.hkdf',
        # zeroconf
        'zeroconf',
        'zeroconf._dns',
        'zeroconf._services',
        # PyQt6
        'PyQt6.QtCore',
        'PyQt6.QtGui',
        'PyQt6.QtWidgets',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ── One-file executable ──────────────────────────────────────────────
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='localdiscord',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,         # Set True to show a console window for debugging
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # Windows: embed an icon if you have one
    # icon='assets/icons/app.ico',
)

# ── macOS .app bundle (comment out if not needed) ────────────────────
# app = BUNDLE(
#     exe,
#     name='LocalDiscord.app',
#     icon='assets/icons/app.icns',
#     bundle_identifier='com.yourdomain.localdiscord',
# )
