"""Seeing the screen: where the game window is, screenshots of it, and Windows' built-in OCR.

All of this only looks at the screen. Finding the window asks Windows where the window titled
"Warframe" is (or, with "window_title": null, uses the primary monitor without asking at all).
"""

import asyncio
import ctypes
import ctypes.wintypes as wt

import mss
import numpy as np
from PIL import Image, ImageOps

user32 = ctypes.windll.user32
try:
    user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))   # real pixel coordinates on scaled displays
except Exception:
    pass

_MSS = getattr(mss, "MSS", None) or mss.mss


def find_game(window_title):
    """(area, status): the (left, top, width, height) to watch, or None when there's nothing to watch,
    and a sentence for the console saying which.

    With a window title: that window's client area, while it's open, not minimised and in front.
    With None: the whole primary monitor.
    """
    if not window_title:
        with _MSS() as sct:
            m = sct.monitors[1]
            area = m["left"], m["top"], m["width"], m["height"]
        return area, f"watching the primary monitor, {area[2]}x{area[3]}"
    hwnd = user32.FindWindowW(None, window_title)
    if not hwnd:
        return None, f'no window titled "{window_title}" (is the game running?)'
    if user32.IsIconic(hwnd):
        return None, f"{window_title} is minimised"
    if user32.GetForegroundWindow() != hwnd:
        return None, f"paused: {window_title} isn't the active window (click into the game)"
    rect, corner = wt.RECT(), wt.POINT(0, 0)
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    user32.ClientToScreen(hwnd, ctypes.byref(corner))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w < 200 or h < 200:
        return None, f"{window_title}'s window is too small ({w}x{h})"
    return (corner.x, corner.y, w, h), f"watching {window_title}: {w}x{h} at ({corner.x}, {corner.y})"


class Screen:
    """Takes screenshots, keeping one capture session open so repeated grabs are fast."""

    def __init__(self):
        self.sct = _MSS()

    def grab(self, area):
        """The area as a BGRA numpy array."""
        left, top, w, h = area
        shot = self.sct.grab({"left": left, "top": top, "width": w, "height": h})
        return np.frombuffer(shot.bgra, dtype=np.uint8).reshape(shot.height, shot.width, 4)


class Ocr:
    """Windows' built-in text recognition: English when installed (the game's text is English),
    otherwise the language set in Windows."""

    def __init__(self):
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine
        english = [lang for lang in OcrEngine.available_recognizer_languages if lang.language_tag.startswith("en")]
        self.engine = (OcrEngine.try_create_from_language(Language(english[0].language_tag)) if english
                       else OcrEngine.try_create_from_user_profile_languages())
        if self.engine is None:
            raise RuntimeError("Windows OCR is not available. Install an OCR language pack: Settings > "
                               "Time & language > Language & region > your language > Language options.")
        self.language = self.engine.recognizer_language.language_tag
        self.max_size = OcrEngine.max_image_dimension
        self.loop = asyncio.new_event_loop()

    def read(self, image, scale=1.0, invert=False):
        """OCR a PIL image, enlarged by `scale` first (and colours inverted if asked).

        Returns lines; each line is a list of words (text, x, y, w, h) in the image's own pixels.
        """
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter
        img = ImageOps.grayscale(image)
        if invert:
            img = ImageOps.invert(img)
        img = ImageOps.autocontrast(img)
        scale = min(scale, self.max_size / max(img.size))
        if abs(scale - 1.0) > 0.01:
            img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
        writer = DataWriter()
        writer.write_bytes(img.tobytes())
        bitmap = SoftwareBitmap.create_copy_from_buffer(writer.detach_buffer(), BitmapPixelFormat.GRAY8,
                                                        img.width, img.height)
        result = self.loop.run_until_complete(self.engine.recognize_async(bitmap))
        return [[(w.text, w.bounding_rect.x / scale, w.bounding_rect.y / scale,
                  w.bounding_rect.width / scale, w.bounding_rect.height / scale) for w in line.words]
                for line in result.lines]
