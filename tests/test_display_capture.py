import base64
import io
import tempfile
from pathlib import Path
import threading
import unittest
from unittest.mock import patch, Mock

from pi_bus_time_display.config import Config
from pi_bus_time_display.server import State, make_handler


PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jWZkAAAAASUVORK5CYII=')


class DisplayCaptureTests(unittest.TestCase):
    def test_native_capture_has_parent_paintable_and_cairo_fallbacks(self):
        source = (Path(__file__).parents[1] / 'native-display' / 'roondeck_native.py').read_text()
        capture = source.split('    def capture_display(self, capture_id, retry=0):', 1)[1].split('    def apply_display_view_request', 1)[0]
        self.assertIn('for strategy in ("parent", "paintable")', capture)
        self.assertIn('Gtk.WidgetPaintable.new(target).snapshot', capture)
        self.assertIn('Gsk.CairoRenderer.new()', capture)
        self.assertIn('cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)', capture)
        self.assertIn('node.draw(context)', capture)

    def test_native_capture_waits_for_wake_and_retries_empty_frames(self):
        source = (Path(__file__).parents[1] / 'native-display' / 'roondeck_native.py').read_text()
        poll = source.split('    def poll(self):', 1)[1].split('    def capture_display', 1)[0]
        self.assertLess(poll.index('GLib.idle_add(self.apply'), poll.index('GLib.timeout_add(350, self.capture_display'))
        capture = source.split('    def capture_display(self, capture_id, retry=0):', 1)[1].split('    def apply_display_view_request', 1)[0]
        self.assertIn('self.wake("screen preview")', capture)
        self.assertIn('if transient and retry < 4:', capture)
        self.assertIn('GLib.timeout_add(250 * (retry + 1)', capture)

    def test_preview_status_requires_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); state=State(Config(),root)
            handler=make_handler(state,root/'config',root/'env',root/'mode').__new__(make_handler(state,root/'config',root/'env',root/'mode'))
            handler.path='/api/admin/preview';handler.authorised=Mock(return_value=False);handler.send_json=Mock()
            handler.do_GET();handler.send_json.assert_not_called()
            handler.authorised.return_value=True
            handler.do_GET();self.assertEqual(handler.send_json.call_args.args[0],200)

    def test_preview_acknowledgement_rejects_remote_and_forwarded_requests(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);state=State(Config(),root);request=state.request_display_view('browse')
            Handler=make_handler(state,root/'config',root/'env',root/'mode');handler=Handler.__new__(Handler)
            handler.path='/api/device/preview';handler.send_json=Mock()
            for address,headers in [('10.0.0.2',{}),('127.0.0.1',{'X-Forwarded-For':'10.0.0.2'})]:
                handler.client_address=(address,1);handler.headers=headers;handler.do_POST()
                self.assertEqual(handler.send_json.call_args.args[0],403)
            payload=__import__('json').dumps({'id':request['id'],'title':'Album'}).encode()
            handler.client_address=('127.0.0.1',1);handler.headers={'Content-Length':str(len(payload))};handler.rfile=io.BytesIO(payload)
            handler.do_POST();self.assertEqual(handler.send_json.call_args.args[0],200)

    def test_preview_acknowledgement_matches_current_command(self):
        state = State(Config())
        request = state.request_display_view('browse')
        with self.assertRaises(ValueError): state.complete_preview({'id':'old'})
        state.complete_preview({'id':request['id'],'title':'Album','items':[{'title':'Track','item_key':'key','action':False,'private':'omit'}]})
        self.assertEqual(state.preview_result['title'], 'Album')
        self.assertNotIn('private', state.preview_result['items'][0])
        state.request_display_view('daily')
        self.assertIsNone(state.preview_result)

    def test_async_preview_capture_returns_a_ticket_then_image(self):
        state = State(Config())
        done = threading.Event()
        def respond():
            done.wait(1)
            return PNG
        with patch.object(state, 'capture_display', side_effect=respond):
            ticket = state.start_preview_capture()
            self.assertEqual(state.preview_capture['status'], 'loading')
            with self.assertRaises(RuntimeError): state.start_preview_capture()
            done.set()
            for _ in range(100):
                if state.preview_capture['status'] == 'ready': break
                threading.Event().wait(.01)
        self.assertEqual(state.preview_capture['id'], ticket)
        self.assertEqual(state.preview_capture['image'], PNG)

    def test_preview_navigation_is_delivered_to_native_display(self):
        state = State(Config())
        request = state.request_display_view('browse', 'open', 'album-key')
        self.assertEqual(request['browse_action'], 'open')
        self.assertEqual(request['item_key'], 'album-key')
        self.assertEqual(state.controls_snapshot()['display_view_request'], request)

    def test_display_view_request_has_a_fresh_identity(self):
        state = State(Config())
        first = state.request_display_view('daily')
        self.assertEqual(state.controls_snapshot()['display_view_request'], first)
        second = state.request_display_view('releases')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(second['view'], 'releases')

    def test_capture_round_trip_is_ephemeral(self):
        state = State(Config())
        def respond(_timeout):
            request_id = state.controls_snapshot()['capture_request']
            state.complete_display_capture({'id': request_id, 'image': base64.b64encode(PNG).decode()})
            return True
        with patch.object(threading.Event, 'wait', side_effect=respond):
            self.assertEqual(state.capture_display(), PNG)
        self.assertIsNone(state.controls_snapshot()['capture_request'])

    def test_capture_failure_is_reported_and_cleared(self):
        state = State(Config())
        def respond(_timeout):
            state.complete_display_capture({'id': state.controls_snapshot()['capture_request'], 'error': 'Display is asleep'})
            return True
        with patch.object(threading.Event, 'wait', side_effect=respond):
            with self.assertRaisesRegex(RuntimeError, 'Display is asleep'):
                state.capture_display()
        self.assertIsNone(state.display_capture)

    def test_capture_timeout_clears_pending_request(self):
        state = State(Config())
        with self.assertRaisesRegex(RuntimeError, 'did not respond'):
            state.capture_display(timeout=0)
        self.assertIsNone(state.display_capture)

    def test_unrequested_capture_is_rejected(self):
        with self.assertRaises(ValueError):
            State(Config()).complete_display_capture({'id': 'fake', 'image': base64.b64encode(PNG).decode()})

    def test_wrong_ticket_invalid_image_and_duplicate_reply_are_rejected(self):
        state = State(Config())
        def respond(_timeout):
            request_id = state.controls_snapshot()['capture_request']
            for data in ({'id':'wrong','image':base64.b64encode(PNG).decode()}, {'id':request_id,'image':'invalid'}, {'id':request_id,'image':base64.b64encode(b'not a PNG').decode()}):
                with self.assertRaises(ValueError):
                    state.complete_display_capture(data)
            data = {'id':request_id,'image':base64.b64encode(PNG).decode()}
            state.complete_display_capture(data)
            with self.assertRaises(ValueError):
                state.complete_display_capture(data)
            return True
        with patch.object(threading.Event, 'wait', side_effect=respond):
            self.assertEqual(state.capture_display(), PNG)

    def test_concurrent_capture_does_not_replace_first_request(self):
        state = State(Config())
        def respond(_timeout):
            request_id = state.controls_snapshot()['capture_request']
            with self.assertRaisesRegex(RuntimeError, 'already in progress'):
                state.capture_display(timeout=0)
            self.assertEqual(state.controls_snapshot()['capture_request'], request_id)
            state.complete_display_capture({'id':request_id,'image':base64.b64encode(PNG).decode()})
            return True
        with patch.object(threading.Event, 'wait', side_effect=respond):
            self.assertEqual(state.capture_display(), PNG)
