# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['D:/WorkBuddyData/ai-daily-briefing/deploy/cli.py'],
    pathex=['D:/WorkBuddyData/ai-daily-briefing'],
    binaries=[],
    datas=[],
    hiddenimports=['feedparser', 'feedparser.encodings', 'feedparser.html', 'feedparser.http', 'feedparser.mixin', 'feedparser.namespaces', 'feedparser.parsers', 'feedparser.sanitizer', 'feedparser.urls', 'sgmllib'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest', 'pydoc', 'distutils', 'email.tests', 'PIL', 'numpy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ai-briefing-update',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
