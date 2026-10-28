"""Artwork loading, decoding and thumbnails."""
from __future__ import annotations

from native_common import ROON, fade_rgba_pixels, get_bytes
from urllib.parse import quote, urlencode
import threading
from gi.repository import GLib, Gdk, GdkPixbuf


class ArtworkMixin:
    def thumbnail_worker(self):
        while True:
            key = self.queue_thumbnail_jobs.get()
            hero_size = 1200 if key in self.artist_hero_keys else 256
            discover_size = 640 if min(getattr(self, "viewport_width", 800), getattr(self, "viewport_height", 480)) >= 1000 else 480
            url = f"{ROON}/api/discovery/image?key={quote(key[9:], safe='')}&size={discover_size}" if key.startswith("discover:") else f"{ROON}/api/image?key={quote(key, safe='')}&size={hero_size}"
            image = get_bytes(url, timeout=6.0 if key in self.artist_hero_keys or key.startswith("discover:") else 2.5)
            if image:
                if not hasattr(self, "queue_artwork_light"): self.queue_artwork_light = {}
                self.queue_artwork_light[key] = self.artwork_is_light(image)
            artist_hero = self.decode_artist_hero_artwork(image) if key in self.artist_hero_keys else None
            GLib.idle_add(self.apply_queue_thumbnail, key, self.decode_artwork(image), True, artist_hero, image)

    def artwork_is_light(self, image):
        try:
            loader = GdkPixbuf.PixbufLoader.new(); loader.write(image); loader.close()
            pixbuf = loader.get_pixbuf(); pixels = pixbuf.get_pixels()
            width, height, stride, channels = pixbuf.get_width(), pixbuf.get_height(), pixbuf.get_rowstride(), pixbuf.get_n_channels()
            values = []
            # Sample the central artwork beneath the marker, not its border.
            for fy in (.35, .45, .55, .65):
                for fx in (.35, .45, .55, .65):
                    offset = int(height * fy) * stride + int(width * fx) * channels
                    red, green, blue = pixels[offset:offset + 3]
                    values.append(.2126 * red + .7152 * green + .0722 * blue)
            return sum(values) / len(values) >= 145
        except (GLib.Error, ValueError, TypeError): return False

    def decode_artwork(self, image):
        # Gdk.Texture loading is thread-safe. Keep image decoding out of the
        # touch/animation loop; only widget updates belong on the UI thread.
        if not image: return None
        try: return Gdk.Texture.new_from_bytes(GLib.Bytes.new(image))
        except GLib.Error: return None

    def decode_artist_hero_artwork(self, image):
        """Return the top-weighted crop used by the taller seven-inch hero."""
        if not image: return None
        try:
            loader = GdkPixbuf.PixbufLoader.new(); loader.write(image); loader.close()
            source = loader.get_pixbuf()
            width, height = source.get_width(), source.get_height()
            if width <= 0 or height <= 0: return None
            hero_ratio = .66 if getattr(self, "original_landscape", False) else .68
            target_ratio = 1 / hero_ratio
            if width / height > target_ratio:
                crop_height = height; crop_width = max(1, round(height * target_ratio))
                crop_x = max(0, round((width - crop_width) / 2)); crop_y = 0
            else:
                crop_width = width; crop_height = max(1, round(width / target_ratio))
                crop_x = 0
                # Keep faces higher while preserving the exact hero window.
                crop_y = max(0, round((height - crop_height) * .4))
            cropped = source.new_subpixbuf(crop_x, crop_y, crop_width, crop_height)
            scaled_height = round(960 * hero_ratio)
            scaled = cropped.scale_simple(960, scaled_height, GdkPixbuf.InterpType.BILINEAR)
            # Fade the photograph itself to transparent. Painting a black
            # gradient over it only works on the default black theme and
            # exposes a rectangular edge on user-selected backgrounds.
            output, output_stride = fade_rgba_pixels(scaled.get_pixels(), 960, scaled_height, scaled.get_rowstride(), scaled.get_n_channels())
            faded = GdkPixbuf.Pixbuf.new_from_bytes(GLib.Bytes.new(output), GdkPixbuf.Colorspace.RGB, True, 8, 960, scaled_height, output_stride)
            return Gdk.Texture.new_for_pixbuf(faded)
        except (GLib.Error, ValueError, TypeError): return None

    def load_preview_artwork(self, picture, key):
        if cached := self.preview_artwork_cache.get(key):
            picture.set_paintable(cached)
            return
        def apply(texture):
            if texture:
                self.preview_artwork_cache[key] = texture
                if picture.get_root() is not None: picture.set_paintable(texture)
            return False
        def load():
            url = f"{ROON}/api/discovery/image?key={quote(key[9:], safe='')}&size=640" if key.startswith("discover:") else f"{ROON}/api/image?key={quote(key, safe='')}&size=900"
            GLib.idle_add(apply, self.decode_artwork(get_bytes(url, timeout=5)))
        threading.Thread(target=load, daemon=True).start()

    def retry_visible_thumbnail(self, key):
        needs_image = key not in self.queue_thumbnail_cache or (key in self.artist_hero_keys and key not in self.artist_hero_cache)
        if (self.browser_pictures.get(key) or self.queue_pictures.get(key) or self.discovery_pictures.get(key)) and needs_image and key not in self.queue_thumbnail_pending:
            self.queue_thumbnail_pending.add(key); self.queue_thumbnail_jobs.put(key)
        return False

    def note_missing_artwork(self):
        self.image_misses += 1
        if self.image_misses >= 5:
            self.set_browser_placeholder(self.artwork)
            self.image_key = None
