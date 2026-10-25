"""Bus Times page."""
from __future__ import annotations

from native_common import PORTRAIT_CONTENT_GAP, elastic_vertical_scroll
from gi.repository import Gtk, Pango


class BusPageMixin:
    def build_bus(self):
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); page.add_css_class("page"); page.add_css_class("bus-page")
        self.bus_clock = self.label("--:--", "clock", 1); self.stop = self.label("Connecting…", "stop"); self.stop_code = self.label("", "stop-code")
        self.stop.set_ellipsize(Pango.EllipsizeMode.END)
        stop_heading = Gtk.Box(spacing=14); stop_heading.set_baseline_position(Gtk.BaselinePosition.CENTER); self.stop.set_valign(Gtk.Align.BASELINE); self.stop_code.set_valign(Gtk.Align.BASELINE); stop_heading.append(self.stop); stop_heading.append(self.stop_code); page.append(self.header(stop_heading, self.bus_clock))
        self.services = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14); self.services.set_vexpand(True)
        self.bus_content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=7); self.bus_content.append(self.services)
        self.bus_scroll = Gtk.ScrolledWindow(); self.bus_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC); self.bus_scroll.set_kinetic_scrolling(True); self.bus_scroll.set_overlay_scrolling(True); self.bus_scroll.set_propagate_natural_height(False); self.bus_scroll.set_propagate_natural_width(False); self.bus_scroll.set_min_content_height(1); self.bus_scroll.set_size_request(-1, 1); self.bus_scroll.set_vexpand(True); self.bus_scroll.set_child(self.bus_content); page.append(self.bus_scroll)
        elastic_vertical_scroll(self.bus_scroll)
        footer = Gtk.Box(); footer.add_css_class("bus-footer"); self.bus_status = self.label("Starting", "muted"); self.updated = self.label("", "muted", 1); self.updated.set_hexpand(True); footer.append(self.bus_status); footer.append(self.updated); self.bus_content.append(footer)
        page.append(self.navigation("bus")); return page

    def render_bus(self, data):
        if not data: self.bus_status.set_text("Bus service unavailable"); return
        self.stop.set_text(data.get('stop_name', 'Bus times')); self.stop_code.set_text(data.get('stop_code', ''))
        while child := self.services.get_first_child(): self.services.remove(child)
        visible = data.get("services", [])[:4]
        portrait = self.window.has_css_class("portrait")
        original_compact = (not portrait and getattr(self, "viewport_width", 800) <= 820
                            and getattr(self, "viewport_height", 480) <= 500 and len(visible) >= 3)
        self.bus_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC if portrait else Gtk.PolicyType.NEVER)
        self.services.set_spacing(24 if portrait else 8 if original_compact else 14)
        self.services.set_valign(Gtk.Align.START if portrait else Gtk.Align.FILL)
        self.services.set_vexpand(not portrait and not original_compact)
        self.bus_content.set_valign(Gtk.Align.START if portrait else Gtk.Align.FILL)
        self.services.set_margin_top((0 if getattr(self, "viewport_width", 800) >= 1000 else PORTRAIT_CONTENT_GAP) if portrait else 0)
        for index, service in enumerate(visible):
            row = Gtk.Box(spacing=12); row.add_css_class("service"); row.add_css_class("service-" + (service.get("colour") or {"40": "blue", "42": "green", "401": "violet"}.get(str(service.get("service")), "amber"))); row.set_vexpand(not original_compact)
            if len(visible) == 3: row.add_css_class("compact")
            elif len(visible) >= 4: row.add_css_class("dense")
            if original_compact:
                row.add_css_class("original-compact"); row.set_size_request(-1, 82 if len(visible) == 3 else 62)
            if portrait:
                self.render_portrait_bus_card(row, service, len(visible))
                self.services.append(row)
                continue
            number = self.label(str(service.get("service", "")), "service-no"); number.set_size_request((150 if len(visible) > 2 else 188) if self.window.has_css_class("high-resolution") else (86 if original_compact else 100 if len(visible) > 2 else 125), -1); number.set_valign(Gtk.Align.CENTER)
            arrivals = Gtk.Box(spacing=8); arrivals.set_hexpand(True)
            if portrait:
                number.set_xalign(.5); number.set_size_request(-1, -1); number.set_valign(Gtk.Align.CENTER)
                count = max(1, len(visible))
                card_budget = (getattr(self, "viewport_height", self.window.get_height()) - 240 - (count - 1) * 24) / count
                large = self.window.has_css_class("large-display")
                route_size = min(344 if large else 216, max(40, round((card_budget - 80) / (2.6 if large else 1.85))))
            font_size = (route_size if self.window.has_css_class("large-display") else round(route_size * .8)) if portrait else (123 if self.window.has_css_class("high-resolution") else 82)
            if not portrait and len(visible) > 2:
                font_size = 38 if original_compact and len(visible) >= 4 else 46 if original_compact else round(font_size / (1.8 if len(visible) >= 4 else 1.4))
            attrs = Pango.AttrList(); attrs.insert(Pango.attr_size_new_absolute(font_size * Pango.SCALE)); number.set_attributes(attrs)
            number.add_css_class("solid-route"); row.append(number)
            for arrival in service.get("arrivals", [])[:2 if portrait else 3]:
                col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); col.set_valign(Gtk.Align.CENTER); minutes = arrival.get("minutes"); value = self.label("Due" if minutes == 0 else str(minutes), "arrival", .5)
                if portrait:
                    due_size = min(344 if self.window.has_css_class("large-display") else 112, max(32, round(route_size * 1.1 if self.window.has_css_class("large-display") else route_size * .68)))
                    if self.window.has_css_class("large-display"):
                        text = "Due" if minutes == 0 else str(minutes)
                        due_size = min(due_size, round((getattr(self, "viewport_width", 1200) - 100) / (2 * max(2, len(text)) * .7)))
                    attrs = Pango.AttrList(); attrs.insert(Pango.attr_size_new_absolute(due_size * Pango.SCALE)); value.set_attributes(attrs)
                col.append(value); col.append(self.label("MIN · LIVE" if arrival.get("monitored") else "MIN · AFTER", "arrival-sub", .5)); col.set_hexpand(True); arrivals.append(col)
            row.append(arrivals); self.services.append(row)
        self.bus_status.set_text("Live from LTA DataMall" if data.get("status") == "ok" and not data.get("stale") else "Offline / last known arrivals")
        updated = data.get("updated_at"); self.updated.set_text("Updated " + updated[11:19] if updated else "")

    def render_portrait_bus_card(self, row, service, count):
        count = max(1, count)
        height = getattr(self, "viewport_height", self.window.get_height())
        width = getattr(self, "viewport_width", self.window.get_width())
        # Reserve the real header, footer and bottom navigation. The previous
        # 240px allowance was optimistic and made a third portrait service
        # extend beneath the fixed navigation on the physical display.
        chrome = 390 if count >= 3 else 300
        gap = 14 if count >= 3 else 24
        budget = max(180, (height - chrome - (count - 1) * gap) / count)
        route_size = max(26, min(110, round(budget * .145)))
        primary_size = max(46, min(248, round(budget * .34)))
        secondary_size = max(24, min(86, round(budget * .115)))
        caption_size = max(14, min(42, round(budget * .055)))
        row.set_orientation(Gtk.Orientation.VERTICAL); row.set_vexpand(False)
        row.set_spacing(max(4, min(16, round(budget * .02))))
        # Budget includes CSS padding, so compact screens can scroll rather
        # than forcing the native window beyond its physical dimensions.
        row.set_size_request(-1, round(budget - (36 if count < 3 else 24)))
        def sized(text, css, size):
            label = self.label(text, css, .5)
            attrs = Pango.AttrList(); attrs.insert(Pango.attr_size_new_absolute(size * Pango.SCALE))
            label.set_attributes(attrs)
            return label
        # Wide (10-inch) portrait: the route badge and the arrival sit close together. With equal
        # columns a long word such as "Due" made the page 1256px wide on a 1200px screen.
        wide_portrait = width >= 1000
        gutter = max(18, round(width * (.02 if wide_portrait else .06)))
        side = round(width * (.04 if wide_portrait else .055))
        top = Gtk.Box(spacing=40 if wide_portrait else gutter); top.add_css_class("bus-primary-row")
        # Equal columns multiply the wider child's minimum width and can push
        # a four-route 480px portrait page beyond the physical viewport.
        top.set_homogeneous(width >= 600 and not wide_portrait); top.set_hexpand(True); top.set_vexpand(True)
        top.set_margin_start(side); top.set_margin_end(side)
        # 10-inch portrait: the route badge and the arrival form one centred group, 40px apart.
        if wide_portrait: top.set_halign(Gtk.Align.CENTER)
        badge_slot = Gtk.Box(); badge_slot.set_hexpand(not wide_portrait); badge_slot.set_valign(Gtk.Align.CENTER)
        badge = Gtk.Box(spacing=12); badge.add_css_class("bus-route-badge"); badge.set_halign(Gtk.Align.CENTER)
        badge.append(sized("ROUTE", "bus-route-word", caption_size))
        number = sized(str(service.get("service", "")), "service-no", route_size)
        number.add_css_class("solid-route"); badge.append(number); badge_slot.append(badge); top.append(badge_slot)
        arrivals = service.get("arrivals", [])[:3]
        minutes = arrivals[0].get("minutes") if arrivals else None
        text = "Due" if minutes == 0 else "—" if minutes is None else str(minutes)
        primary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); primary.set_hexpand(not wide_portrait); primary.set_vexpand(True); primary.set_valign(Gtk.Align.CENTER)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0); content.set_valign(Gtk.Align.CENTER)
        if wide_portrait:
            column = (width - 100 - gutter - 2 * side) / 2
            primary_size = min(primary_size, round(column / (1.9 if text == "Due" else max(2, len(text)) * .75)))
        else:
            primary_size = min(primary_size, round((width - 100) / (max(2, len(text)) * .75)))
        content.append(sized(text, "bus-next", primary_size))
        unit = sized("arriving now" if minutes == 0 else "minutes" if minutes is not None else "no prediction", "bus-next-unit", caption_size)
        if wide_portrait:
            # A large numeral's line box carries ~0.24em of descent; pull the caption up under the digits.
            unit.add_css_class("bus-unit-pull-%d" % max(1, min(16, round(primary_size * .19 / 4))))
            primary.set_size_request(round(column * .92), -1)
        content.append(unit)
        primary.append(content); top.append(primary); row.append(top)
        later = arrivals[1:]
        if later:
            rule = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL); rule.add_css_class("bus-rule")
            rule.set_margin_start(round(width * .055)); rule.set_margin_end(round(width * .055)); row.append(rule)
            row.append(sized("THEN", "bus-then", max(13, round(caption_size * .75))))
            following = Gtk.Box(spacing=12); following.set_homogeneous(True)
            following.set_margin_bottom(max(8, round(budget * .025)))
            for arrival in later:
                value = arrival.get("minutes")
                item = Gtk.Box(spacing=max(4, round(caption_size * .18))); item.set_halign(Gtk.Align.CENTER)
                text = "Due" if value == 0 else str(value)
                size = min(secondary_size, round((width - 110) / (max(1, len(later)) * max(2, len(text)) * .75)))
                item.append(sized(text, "bus-following", max(12, size)))
                if value != 0: item.append(sized("min", "bus-following-unit", max(20, round(secondary_size * .52))))
                following.append(item)
            row.append(following)
