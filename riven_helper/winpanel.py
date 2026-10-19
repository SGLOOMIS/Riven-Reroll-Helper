"""Translucent, click-through overlay windows (one per panel).

Each panel is its own small top-most layered window showing an RGBA image
with per-pixel alpha, so panels can be translucent and anti-aliased like the
game's UI. Moving or fading a panel only changes the window's position or
opacity (no redraw), which is what lets panels follow cards smoothly.

These are this program's own windows. They never attach to, draw into, or
send anything to the game: they simply sit on top of the screen, ignore the
mouse, and are hidden from screen capture so OCR never reads them.
"""

import ctypes
import ctypes.wintypes as wt

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)
user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.CreateWindowExW.restype = wt.HWND
user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
user32.GetDC.restype = wt.HDC
user32.GetDC.argtypes = [wt.HWND]
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.CreateDIBSection.restype = wt.HBITMAP
gdi32.CreateDIBSection.argtypes = [wt.HDC, ctypes.c_void_p, wt.UINT, ctypes.POINTER(ctypes.c_void_p), wt.HANDLE,
                                   wt.DWORD]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


user32.UpdateLayeredWindow.argtypes = [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                       ctypes.POINTER(wt.POINT), wt.DWORD, ctypes.POINTER(BLENDFUNCTION), wt.DWORD]

WS_POPUP = 0x80000000
WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x80000, 0x20, 0x80
WS_EX_NOACTIVATE, WS_EX_TOPMOST = 0x08000000, 0x8
ULW_ALPHA, AC_SRC_OVER, AC_SRC_ALPHA = 2, 0, 1
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST, SWP_NOMOVE, SWP_NOSIZE, SWP_NOACTIVATE = -1, 0x2, 0x1, 0x10
WDA_EXCLUDEFROMCAPTURE = 0x11
CLASS_NAME = "RivenHelperPanel"

_wndproc = WNDPROC(lambda h, m, w, l: user32.DefWindowProcW(h, m, w, l))   # kept alive for the process
_registered = False


def _register():
    global _registered
    if _registered:
        return
    wc = WNDCLASSW()
    wc.lpfnWndProc = _wndproc
    wc.hInstance = kernel32.GetModuleHandleW(None)
    wc.lpszClassName = CLASS_NAME
    user32.RegisterClassW(ctypes.byref(wc))
    _registered = True


class Panel:
    """One click-through layered window that shows an RGBA PIL image."""

    def __init__(self, hide_from_capture=True):
        _register()
        ex = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        self.hwnd = user32.CreateWindowExW(ex, CLASS_NAME, "Riven Helper", WS_POPUP, 0, 0, 1, 1,
                                           None, None, kernel32.GetModuleHandleW(None), None)
        if hide_from_capture:
            user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)
        self.size = (0, 0)
        self.pos = (0, 0)
        self.alpha = 255
        self.visible = False
        self.image_key = None
        self._mem_dc = None
        self._bitmap = None
        self._old = None

    def set_image(self, img, key=None):
        """Show a new picture (skipped when `key` matches the picture already shown)."""
        if key is not None and key == self.image_key:
            return
        self.image_key = key
        w, h = img.size
        screen = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen)
        bmi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        bits = ctypes.c_void_p()
        bitmap = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        data = img.convert("RGBa").tobytes("raw", "BGRa")          # premultiplied, as Windows wants
        ctypes.memmove(bits, data, len(data))
        old = gdi32.SelectObject(mem, bitmap)
        self._release()
        self._mem_dc, self._bitmap, self._old = mem, bitmap, old
        self.size = (w, h)
        self._update(screen)
        user32.ReleaseDC(None, screen)

    def _update(self, screen=None):
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, max(0, min(255, int(self.alpha))), AC_SRC_ALPHA)
        pt = wt.POINT(int(self.pos[0]), int(self.pos[1]))
        if screen is not None and self._mem_dc:
            size = wt.SIZE(*self.size)
            src = wt.POINT(0, 0)
            user32.UpdateLayeredWindow(self.hwnd, screen, ctypes.byref(pt), ctypes.byref(size), self._mem_dc,
                                       ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA)
        else:   # position / opacity only: no redraw
            user32.UpdateLayeredWindow(self.hwnd, None, ctypes.byref(pt), None, None, None, 0,
                                       ctypes.byref(blend), ULW_ALPHA)

    def place(self, x, y, alpha=None):
        if alpha is not None:
            self.alpha = alpha
        if (int(x), int(y)) == tuple(map(int, self.pos)) and alpha is None:
            return
        self.pos = (x, y)
        if self._mem_dc:
            self._update()

    def show(self):
        if not self.visible and self._mem_dc:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.visible = True
        user32.SetWindowPos(self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)

    def hide(self):
        if self.visible:
            user32.ShowWindow(self.hwnd, SW_HIDE)
            self.visible = False

    def _release(self):
        if self._mem_dc:
            gdi32.SelectObject(self._mem_dc, self._old)
            gdi32.DeleteObject(self._bitmap)
            gdi32.DeleteDC(self._mem_dc)
            self._mem_dc = None

    def destroy(self):
        self._release()
        user32.DestroyWindow(self.hwnd)
