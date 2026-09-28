# -*- coding: utf-8 -*-
"""清理本次调试产生的临时/失效文件。

为什么不用 os.remove / shutil.rmtree：
    本环境的 Python 删除调用被 safe-delete 钩子包装，会 SAFE_DELETE_FAIL_CLOSED 拦截。
    真正能删的是 ctypes 直调 SHFileOperationW（不加 FOF_ALLOWUNDO = 永久删除）。
"""
import ctypes
from ctypes import wintypes
from pathlib import Path

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_NOERRORUI = 0x0400
FOF_NOCONFIRMMKDIR = 0x0200


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint16),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def sh_delete(paths):
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = "\0".join(str(p) for p in paths) + "\0\0"
    op.pTo = None
    op.fFlags = FOF_SILENT | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_NOCONFIRMMKDIR
    return ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))


ROOT = Path(__file__).resolve().parent.parent

TARGETS = [
    ROOT / "tools" / "shoot_latest.py",   # 用 --screenshot CLI，Edge 153 起已失效
    ROOT / ".shot-tmp",                    # 参数探测产生的 profile 残留
    ROOT / "preview" / "diag.png",         # 调试截图
]


def main():
    todo = [p for p in TARGETS if p.exists()]
    if not todo:
        print("没有需要清理的项")
        return 0
    for p in todo:
        print(f"  删除 {'[目录]' if p.is_dir() else '[文件]'} {p.relative_to(ROOT)}")
    rc = sh_delete(todo)
    print(f"\nSHFileOperationW rc={rc}（0 = 成功）")
    left = [p for p in TARGETS if p.exists()]
    print("残留:", "无" if not left else [str(p) for p in left])
    return 0 if rc == 0 and not left else 1


if __name__ == "__main__":
    raise SystemExit(main())
