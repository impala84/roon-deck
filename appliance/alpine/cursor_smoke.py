"""Verify the cursor file with the real Xcursor loader, not just its bytes."""
import ctypes
from cursor_theme import prepare

class Image(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in ("version", "size", "width", "height", "xhot", "yhot", "delay")] + [("pixels", ctypes.POINTER(ctypes.c_uint32))]

library = ctypes.CDLL("libXcursor.so.1")
library.XcursorFilenameLoadImage.argtypes = [ctypes.c_char_p, ctypes.c_int]
library.XcursorFilenameLoadImage.restype = ctypes.POINTER(Image)
library.XcursorImageDestroy.argtypes = [ctypes.POINTER(Image)]
image = library.XcursorFilenameLoadImage(str(prepare() / "cursors/left_ptr").encode(), 24)
assert image, "Cursor theme could not be decoded"
assert (image.contents.width, image.contents.height, image.contents.pixels[0]) == (24, 24, 0)
library.XcursorImageDestroy(image)
print("Transparent cursor decoded by libXcursor; physical pointer visibility still needs Pi acceptance.")
