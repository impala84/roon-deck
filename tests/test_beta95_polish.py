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
        for rule in (".album-play-menu, .interface-larger .album-play-menu { min-width: 0; padding: 0 12px; }",
                     ".large-display .album-play-menu { min-width: 0; padding: 0 20px; }",
                     ".original-landscape .album-play-menu { min-width: 0; padding: 0 8px; }"):
            self.assertIn(rule, self.code)
        self.assertIn('FamilyIcon("chevron-play", 30 if min(vw, vh) >= 1000 else 18 if vw <= 820 and vh <= 500 else 20)', self.code)

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

    def test_left_column_rows_are_buttons_that_pick_a_sibling(self):
        self.assertIn('row = Gtk.Button(); row.add_css_class("genre-trail-row")', self.code)
        self.assertIn("self.select_genre_sibling(choice, parent_title)", self.code)
        self.assertIn("self.follow_genre_sibling(data): return False", self.code)

    def test_left_column_has_no_visible_scrollbar_and_a_wider_gutter(self):
        self.assertIn("self.browser_trail_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.EXTERNAL)", self.code)
        self.assertIn(".genre-trail { margin-right: 40px; }", self.code)
