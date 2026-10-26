import unittest

from native_source import native_text


class Beta95PolishTests(unittest.TestCase):
    def setUp(self):
        self.code = native_text()

    def test_update_progress_text_is_not_cut_at_32_characters(self):
        self.assertNotIn("self.device_status.set_max_width_chars(32)", self.code)
        self.assertIn("self.device_status.set_max_width_chars(64)", self.code)

    def test_sleep_button_is_narrower_on_every_display(self):
        self.assertIn(".original-landscape .settings-header .settings-utilities .settings-sleep { min-width: 84px; padding: 0 10px; }", self.code)
        self.assertIn(".touch2-7-landscape .settings-header .settings-utilities .settings-sleep { min-width: 112px; padding: 0 14px; }", self.code)

    def test_play_album_arrow_has_no_extra_min_width(self):
        for rule in (".album-play-menu, .interface-larger .album-play-menu { min-width: 0; padding: 0 18px 0 16px; }",
                     ".large-display .album-play-menu { min-width: 0; padding: 0 30px 0 28px; }",
                     ".original-landscape .album-play-menu { min-width: 0; padding: 0 14px 0 12px; }"):
            self.assertIn(rule, self.code)
        self.assertIn('FamilyIcon("chevron-play", 34 if large_portrait else 24 if min(vw, vh) >= 1000 else 14 if vw <= 820 and vh <= 500 else 16)', self.code)

    def test_original_music_cog_is_centred_like_the_bus_and_home_cog(self):
        self.assertIn("Gtk.Align.FILL if original and not full else Gtk.Align.START", self.code)
        self.assertIn(".original-landscape .page-header .discover-utility { min-width: 36px; }", self.code)

    def test_gen2_larger_writeup_is_bigger(self):
        self.assertIn(".touch2-7-landscape.interface-larger .detail-writeup,", self.code)
        self.assertIn("{ font-size: 24px; line-height: 1.25; }", self.code)


if __name__ == "__main__":
    unittest.main()


class GenreBrowserTests(unittest.TestCase):
    def setUp(self):
        self.code = native_text()

    def test_genre_menu_screens_use_the_fixed_size_tile_grid(self):
        self.assertIn('elif items and layout in {"home", "menu"} and (getattr(self, "responsive_portrait", False) or data.get("section") != "genres"):', self.code)

    def test_genre_actions_sit_in_the_left_column_with_inverted_icons(self):
        self.assertIn('row.add_css_class("genre-action-row")', self.code)
        self.assertIn('frame.add_css_class("genre-action-icon")', self.code)
        self.assertIn("items = self.prepare_genre_columns(data, layout, items)", self.code)
        self.assertIn("button.genre-action-row { min-height: 96px;", self.code)
        self.assertIn('short = "Shuffle" if raw.startswith("shuffle")', self.code)
        self.assertIn('self.label("SUB-GENRES", "browser-section")', self.code)

    def test_left_column_has_no_visible_scrollbar_and_a_wider_gutter(self):
        self.assertIn("self.browser_trail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)", self.code)
        self.assertIn(".genre-trail { margin-right: 40px; }", self.code)


class GenreShortcutIconTests(unittest.TestCase):
    def test_genre_list_shortcuts_use_the_larger_key_line_tile_icons(self):
        code = native_text()
        self.assertIn('genre_shortcut = (data.get("section") == "genres" and not key and (row_title in {"artists", "albums", "genre artists", "genre albums"} or row_title.startswith("shuffle")))', code)
        self.assertIn('self.browser_svg_icon(self.browser_tile_symbol(item.get("title"), "genres"), 62) if genre_shortcut', code)


class TenInchSettingsTests(unittest.TestCase):
    def setUp(self):
        self.code = native_text()

    def test_appearance_is_one_row_of_three_dropdowns_on_the_10_inch(self):
        for text in ('["Scaling · Smaller", "Scaling · Standard", "Scaling · Larger"]', '["Theme · Mint", "Theme · Roon"]',
                     '["Background · Gradient", "Background · Black"]', 'appearance_group.append(self.label("APPEARANCE", "eyebrow"))',
                     "self.settings_appearance.set_visible(not graph_layout)"):
            self.assertIn(text, self.code)

    def test_health_line_is_hidden_on_the_10_inch_unless_it_carries_a_message(self):
        self.assertIn('health = text.startswith(("Memory", "Loading diagnostics"))', self.code)

    def test_tapping_a_track_plays_it_without_blanking_the_album(self):
        self.assertIn("else: button.opens_page = not album_profile", self.code)
