"""Screen preview: remote capture and view requests."""
from __future__ import annotations

from native_common import BUS, post_json
import base64
import cairo
import io
import threading
import time
from gi.repository import GLib, Gdk, Graphene, Gsk, Gtk


class ScreenPreviewMixin:
    def capture_display(self, capture_id, retry=0):
        data = {"id": capture_id}
        try:
            # Snapshot the actual live GTK tree.  This captures precisely what
            # RoonDeck rendered (including fetched artwork) and remains reliable
            # when Cage/wlroots uses direct scan-out, where grim can otherwise
            # return an all-black but syntactically valid PNG.
            stack = getattr(self, "stack", None)
            visible_page = stack.get_visible_child_name() if stack is not None else None
            if retry == 0 and (getattr(self, "inactivity_sleeping", False) or visible_page == "sleep"):
                self.wake("screen preview")
                GLib.timeout_add(700, self.capture_display, capture_id, retry + 1)
                return False
            if hasattr(self, "set_screen_power"):
                self.set_screen_power(True)
            self.window.queue_draw()
            width, height = self.window.get_width(), self.window.get_height()
            if width <= 0 or height <= 0:
                raise ValueError("Display has no drawable size")
            # Snapshot the visible client page, not the native window surface.
            # A fullscreen Wayland window can expose only its black backing
            # surface to WidgetPaintable while the child contains the live UI.
            target = self.window.get_child()
            if target is None:
                raise ValueError("Display has no visible page")
            def visible_png(texture):
                pixels = Gdk.pixbuf_get_from_texture(texture)
                if pixels is None:
                    raise ValueError("Screenshot pixels are unavailable")
                raw = pixels.get_pixels()
                channels, stride = pixels.get_n_channels(), pixels.get_rowstride()
                visible = any(raw[y * stride + x * channels + c] > 8
                              and (channels != 4 or raw[y * stride + x * channels + 3] > 8)
                              for y in range(0, pixels.get_height(), 8)
                              for x in range(0, pixels.get_width(), 8)
                              for c in range(3))
                if not visible:
                    raise ValueError("Display capture contains no visible content")
                return bytes(texture.save_to_png_bytes().get_data())

            def render_snapshot(snapshot):
                node = snapshot.to_node()
                if node is None:
                    raise ValueError("Display produced no render node")
                errors = []
                # Render into independent memory first. Asking the active
                # fullscreen KMS/Wayland renderer to read its own scan-out
                # buffer can stall or return no pixels on Raspberry Pi.
                try:
                    bounds = node.get_bounds()
                    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
                    context = cairo.Context(surface)
                    context.translate(-bounds.get_x(), -bounds.get_y())
                    node.draw(context)
                    surface.flush()
                    raw = surface.get_data()
                    if not any(raw[index] > 8 or raw[index + 1] > 8 or raw[index + 2] > 8
                               for index in range(0, len(raw) - 3, 128)):
                        raise ValueError("software render contains no visible content")
                    output = io.BytesIO()
                    surface.write_to_png(output)
                    image = output.getvalue()
                    if image.startswith(b"\x89PNG\r\n\x1a\n"):
                        return image
                    raise ValueError("software renderer returned an invalid image")
                except (cairo.Error, AttributeError, RuntimeError, TypeError, ValueError) as error:
                    errors.append(f"software renderer: {error}")
                live = self.window.get_renderer()
                if live is not None:
                    try:
                        return visible_png(live.render_texture(node, None))
                    except (GLib.Error, RuntimeError, TypeError, ValueError) as error:
                        errors.append(f"live renderer: {error}")
                # Some KMS/Wayland drivers display the live node correctly but
                # cannot read it back through the active renderer.  The Cairo
                # renderer is slower, but it is a reliable capture-only path.
                cairo_renderer = Gsk.CairoRenderer.new()
                try:
                    if not cairo_renderer.realize_for_display(self.window.get_display()):
                        raise RuntimeError("Cairo renderer could not be initialized")
                    return visible_png(cairo_renderer.render_texture(node, None))
                except (GLib.Error, RuntimeError, TypeError, ValueError) as error:
                    errors.append(f"Cairo renderer: {error}")
                finally:
                    if cairo_renderer.is_realized(): cairo_renderer.unrealize()
                raise ValueError("; ".join(errors))

            def add_popovers(snapshot):
                for popup in (getattr(self, "browser_action_popover", None), getattr(self, "browser_sort_popover", None)):
                    if popup is not None and popup.get_mapped():
                        valid, bounds = popup.compute_bounds(target)
                        if valid:
                            snapshot.save()
                            point = Graphene.Point(); point.init(bounds.get_x(), bounds.get_y())
                            snapshot.translate(point)
                            Gtk.WidgetPaintable.new(popup).snapshot(snapshot, float(popup.get_width()), float(popup.get_height()))
                            snapshot.restore()

            attempts = []
            # Prefer the current frame in the parent widget tree.  If a GTK or
            # driver combination refuses that readback, fall back to a fresh
            # WidgetPaintable snapshot of the same visible page.
            for strategy in ("parent", "paintable"):
                try:
                    snapshot = Gtk.Snapshot()
                    if strategy == "parent":
                        self.window.snapshot_child(target, snapshot)
                    else:
                        Gtk.WidgetPaintable.new(target).snapshot(
                            snapshot, float(target.get_width() or width), float(target.get_height() or height))
                    add_popovers(snapshot)
                    image = render_snapshot(snapshot)
                    break
                except (GLib.Error, RuntimeError, TypeError, ValueError) as error:
                    attempts.append(f"{strategy}: {error}")
            else:
                raise ValueError(" | ".join(attempts))
            if len(image) > 8_388_608 or not image.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError("Invalid screenshot")
            data["image"] = base64.b64encode(image).decode("ascii")
        except Exception as error:
            transient = any(text in str(error).lower() for text in (
                "no visible content", "no drawable size", "no visible page",
                "no render node", "pixels are unavailable",
            ))
            if transient and retry < 4:
                self.window.queue_draw()
                GLib.timeout_add(250 * (retry + 1), self.capture_display, capture_id, retry + 1)
                return False
            print(f"RoonDeck display capture failed: {error}", flush=True)
            detail = str(error).strip()[:240]
            data["error"] = f"Display capture failed: {detail}. The previous preview is unchanged."
        if post_json(BUS + "/api/device/display-capture", data, timeout=15) is None:
            print("RoonDeck display capture delivery failed", flush=True)
        return False

    def apply_display_view_request(self, request):
        self.preview_navigation_id = request.get("id")
        if self.preview_navigation_id:
            GLib.timeout_add(150, self.finish_preview_navigation, request, time.monotonic() + 40)
        view = str(request.get("view", ""))
        action = request.get("browse_action")
        if action in {"open", "back", "current", "section"}:
            if popup := (getattr(self, "browser_action_menu", None) or getattr(self, "browser_action_popover", None)):
                self.browser_action_selected["value"] = True
                popup.popdown()
            self.set_mode("roon"); self.set_roon_view("browse")
            self.browser_action_anchor = None
            child = self.browser_list.get_first_child()
            while child:
                if getattr(child, "browse_item_key", None) == request.get("item_key"):
                    self.browser_action_anchor = child; break
                child = child.get_next_sibling()
            payload = {"item_key": request.get("item_key", "")} if action == "open" else {"section": request.get("section", "albums")} if action == "section" else {}
            self.request_browser(action, **payload)
            return False
        if view == "now":
            self.show_roon_now()
            self.set_mode("roon")
        elif view == "details":
            self.set_mode("roon"); self.set_roon_view("details")
        elif view == "settings":
            self.open_settings()
        elif view == "search":
            self.discovery_browser_origin = False
            self.discovery_active = True; self.discovery_section = "browse"
            self.set_mode("roon"); self.set_roon_view("search")
        elif view in {"recent", "daily", "releases", "browse", "surprise"}:
            self.discovery_signature = None
            self.open_discover(view)
        elif view in {"bus", "home"}:
            self.set_mode(view)
        return False

    def finish_preview_navigation(self, request, deadline):
        if request.get("id") != getattr(self, "preview_navigation_id", None): return False
        requested = request.get("view")
        if requested in {"bus", "home", "settings", "details"}: view = requested
        else: view = self.roon_views.get_visible_child_name()
        browser = view in {"browse", "search"}
        loading = (getattr(self, "browser_loading", False) or getattr(self, "browser_rendering", False)) if browser else view == "discover" and (not self.discovery_signature or (getattr(self, "discovery_data", {}) or {}).get("status") == "loading")
        if loading and time.monotonic() < deadline: return True
        data = (self.browser_state or {}) if browser else (getattr(self, "discovery_data", {}) or {}) if view == "discover" else {}
        error = "The display did not finish opening this view." if loading else str(data.get("message") or "Could not open this view") if data.get("error") or data.get("status") in {"error", "unavailable"} else ""
        result = {"id": request["id"], "error": error, "title": data.get("title") or request.get("view", "Display"), "can_back": data.get("can_back", False), "items": data.get("items", []) if browser else []}
        threading.Thread(target=post_json, args=(BUS + "/api/device/preview", result), kwargs={"timeout": 5}, daemon=True).start()
        return False
