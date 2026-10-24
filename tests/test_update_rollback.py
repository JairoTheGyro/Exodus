"""Exodus home-server safety net in scripts/update_local.py: a data backup
before updating, a rollback image before rebuilding, and --rollback.

Uses the same fake Git/Docker runner as tests/test_update_local.py; nothing
real is pulled, built, tagged or reset.
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_update_local import NEW, OLD, FakeRunner, updater

IMAGE = 'sovereign-hub-odysseus:latest'
ROLLBACK = 'sovereign-hub-odysseus:rollback'


class SafetyNetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        for name in updater.DEFAULT_FILES:
            (self.root / name).write_text('services: {}\n')
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/odysseus-backup').write_text('# stand-in\n')
        self.runner = FakeRunner(self.root)
        for config in (self.runner.current, self.runner.future):
            config['services']['odysseus']['image'] = IMAGE
        self.messages = []

    def update(self, **kwargs):
        return updater.update(self.runner, self.root, say=self.messages.append, **kwargs)

    def rollback(self):
        return updater.rollback(self.runner, self.root, say=self.messages.append)

    def index(self, predicate):
        return next(i for i, call in enumerate(self.runner.calls) if predicate(call))

    def state(self):
        return json.loads((self.root / '.git/exodus-update.json').read_text())

    def test_data_is_backed_up_before_pulling(self):
        self.update()
        backup = self.index(lambda c: c[0] == sys.executable)
        self.assertEqual(self.runner.calls[backup][1:], [str(self.root / 'scripts/odysseus-backup'), 'snapshot'])
        self.assertLess(backup, self.index(lambda c: c[:2] == ['git', 'pull']))

    def test_backup_can_be_skipped_and_is_skipped_when_nothing_is_new(self):
        self.update(backup=False)
        self.assertFalse(any(c[0] == sys.executable for c in self.runner.calls))
        self.runner.calls.clear()
        self.update()  # already up to date: head == target
        self.assertFalse(any(c[0] == sys.executable for c in self.runner.calls))

    def test_failed_backup_stops_before_anything_changes(self):
        self.runner.fail_backup = True
        with self.assertRaises(updater.UpdateError):
            self.update()
        self.assertFalse(any(c[:2] in (['git', 'pull'], ['docker', 'tag']) for c in self.runner.calls))
        self.assertEqual(self.runner.head, OLD)

    def test_missing_backup_tool_stops_the_update(self):
        (self.root / 'scripts/odysseus-backup').unlink()
        with self.assertRaises(updater.UpdateError) as caught:
            self.update()
        self.assertIn('--no-backup', str(caught.exception))
        self.assertFalse(any(c[:2] == ['git', 'pull'] for c in self.runner.calls))

    def test_rebuild_keeps_the_previous_image_first(self):
        self.runner.paths = ['requirements.txt']
        plan = self.update()
        self.assertIn('odysseus', plan.build)
        tag = self.index(lambda c: c == ['docker', 'tag', IMAGE, ROLLBACK])
        build = self.index(lambda c: c[:2] == ['docker', 'compose'] and 'build' in c)
        self.assertLess(tag, build)
        point = self.state()['rollback']
        self.assertEqual(point['commit'], OLD)
        self.assertEqual(point['images'], {'odysseus': [IMAGE, ROLLBACK]})
        self.assertIn('odysseus', point['services'])
        self.assertTrue(any('Rollback point saved' in m for m in self.messages))

    def test_a_never_built_image_is_simply_not_kept(self):
        self.runner.paths = ['requirements.txt']
        self.runner.missing_images = {IMAGE}
        self.update()
        self.assertFalse(any(c[:2] == ['docker', 'tag'] for c in self.runner.calls))
        self.assertEqual(self.state()['rollback']['images'], {})

    def test_failed_reload_points_to_rollback_and_never_resets_on_its_own(self):
        self.runner.fail_up = True
        with self.assertRaises(updater.UpdateError) as caught:
            self.update()
        self.assertIn('--rollback', str(caught.exception))
        self.assertEqual(self.runner.head, NEW)
        self.assertFalse(any(c[:2] == ['git', 'reset'] for c in self.runner.calls))

    def test_rollback_restores_code_image_and_services(self):
        self.runner.paths = ['requirements.txt']
        self.update()
        self.runner.calls.clear()
        self.assertEqual(self.rollback(), OLD)
        self.assertEqual(self.runner.head, OLD)
        self.assertIn(['git', 'reset', '--hard', OLD], self.runner.calls)
        self.assertIn(['docker', 'tag', ROLLBACK, IMAGE], self.runner.calls)
        up = next(c for c in self.runner.calls if c[:2] == ['docker', 'compose'] and 'up' in c)
        self.assertIn('--no-build', up)
        self.assertIn('odysseus', up)
        self.assertEqual(self.state(), {'applied': OLD})
        with self.assertRaises(updater.UpdateError) as caught:
            self.rollback()  # the point is used up
        self.assertIn('no saved rollback point', str(caught.exception))

    def test_rollback_guards(self):
        with self.assertRaises(updater.UpdateError):
            self.rollback()  # nothing saved yet
        self.update()
        self.runner.dirty = ' M static/app.js\0'
        with self.assertRaises(updater.UpdateError):
            self.rollback()
        self.runner.dirty = ''
        self.runner.branch = 'feature'
        with self.assertRaises(updater.UpdateError):
            self.rollback()
        self.assertFalse(any(c[:2] == ['git', 'reset'] for c in self.runner.calls))

    def test_a_tampered_rollback_point_is_refused(self):
        self.runner.paths = ['requirements.txt']
        self.update()
        state = self.state()
        state['rollback']['images']['odysseus'] = [IMAGE, 'evil/image:latest']
        (self.root / '.git/exodus-update.json').write_text(json.dumps(state))
        with self.assertRaises(updater.UpdateError):
            self.rollback()
        self.assertFalse(any(c[:2] == ['docker', 'tag'] and c[2] == 'evil/image:latest' for c in self.runner.calls))

    def test_rollback_tag_names(self):
        self.assertEqual(updater.rollback_tag('sovereign-hub-odysseus:latest'), 'sovereign-hub-odysseus:rollback')
        self.assertEqual(updater.rollback_tag('sovereign-hub-harness'), 'sovereign-hub-harness:rollback')
        self.assertEqual(updater.rollback_tag('ghcr.io/me/exodus:1.2'), 'ghcr.io/me/exodus:rollback')
        for bad in (None, '', 'UPPER:case', 'a b', 'x;rm -rf /'):
            self.assertIsNone(updater.rollback_tag(bad))

    def test_command_line_flags(self):
        with patch.object(updater, 'update') as update, patch.object(updater, 'rollback') as rollback:
            self.assertEqual(updater.main(['--no-backup']), 0)
            self.assertFalse(update.call_args.kwargs['backup'])
            self.assertEqual(updater.main(['--rollback']), 0)
            rollback.assert_called_once()


if __name__ == '__main__':
    unittest.main()
