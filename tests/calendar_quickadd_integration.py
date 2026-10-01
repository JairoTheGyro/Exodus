"""Real local parsing + persistence; isolated DB, never the user's calendar.

Run in the dependency container: python tests/calendar_quickadd_integration.py
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, patch

import home_integration as fixture
from routes.calendar_routes import setup_calendar_routes
from src.calendar_quick_add import parse_quick_add
from core.database import CalendarEvent

fixture.app.include_router(setup_calendar_routes())
NOW = datetime(2026, 9, 30, 10, 0, tzinfo=ZoneInfo('America/New_York'))


class CalendarQuickAdd(unittest.TestCase):
    def setUp(self):
        self.client = fixture.TestClient(fixture.app)
        self.client.headers['x-test-user'] = 'calendar-audit'
        self.client.patch('/api/home/profile', json={'mode': 'full'})
        with fixture.SessionLocal() as db:
            db.query(CalendarEvent).delete()
            db.commit()

    def test_local_phrases(self):
        cases = [
            ('Meeting tomorrow at 3pm', 'Meeting', '2026-10-01T15:00:00', '2026-10-01T16:00:00'),
            ('Gym Friday 8am', 'Gym', '2026-10-02T08:00:00', '2026-10-02T09:00:00'),
            ('Finish report next Monday', 'Finish report', '2026-10-05', '2026-10-06'),
            ('Team catchup tomorrow at 2pm', 'Team catchup', '2026-10-01T14:00:00', '2026-10-01T15:00:00'),
            ('Standup today at 14:30 for 30 minutes', 'Standup', '2026-09-30T14:30:00', '2026-09-30T15:00:00'),
            ('Lunch on October 2 at noon', 'Lunch', '2026-10-02T12:00:00', '2026-10-02T13:00:00'),
            ('Shift Friday 11pm to 1am', 'Shift', '2026-10-02T23:00:00', '2026-10-03T01:00:00'),
            ('Review tomorrow 2-3pm', 'Review', '2026-10-01T14:00:00', '2026-10-01T15:00:00'),
            ('Stretch in 30 minutes', 'Stretch', '2026-09-30T10:30:00', '2026-09-30T11:30:00'),
            ('Release 2026-12-25', 'Release', '2026-12-25', '2026-12-26'),
        ]
        for text, title, start, end in cases:
            with self.subTest(text=text):
                e = parse_quick_add(text, NOW)['event']
                self.assertEqual((e['summary'], e['dtstart'], e['dtend']), (title, start, end))

    def test_invalid_or_ambiguous_input(self):
        for text in ('', 'Meeting tomorrow at 25pm', 'Meeting 2026-02-30', 'Meeting 10/02/2026', 'a'*2001):
            with self.subTest(text=text[:60]), self.assertRaises(ValueError):
                parse_quick_add(text, NOW)
        self.assertIn('using today', parse_quick_add('A new idea', NOW)['notice'])

    def test_timezone_near_midnight(self):
        from src.user_time import clear_user_time_context, set_user_tz_name, now_user_local
        from datetime import timezone
        clear_user_time_context()
        set_user_tz_name('America/Los_Angeles')
        try:
            now = now_user_local(datetime(2026, 10, 1, 1, tzinfo=timezone.utc))
            self.assertEqual(parse_quick_add('Meeting tomorrow at 3pm', now)['event']['dtstart'], '2026-10-01T15:00:00')
        finally:
            clear_user_time_context()

    def test_parse_save_and_home_query_both_modes_without_inference(self):
        for mode in ('full', 'ai-free'):
            self.client.patch('/api/home/profile', json={'mode':mode})
            with patch('src.user_time.now_user_local', return_value=NOW), \
                 patch('src.endpoint_resolver.resolve_endpoint', side_effect=AssertionError('No provider allowed')) as resolver, \
                 patch('src.llm_core.llm_call_async', side_effect=AssertionError('No inference allowed')) as llm:
                r = self.client.post('/api/calendar/quick-parse', json={'text':'Team catchup tomorrow at 2pm', 'tz':'America/New_York'})
                self.assertEqual(r.status_code, 200, r.text)
                e = r.json()['event']
                self.assertEqual(e['summary'], 'Team catchup')
                self.assertEqual(e['dtstart'], '2026-10-01T14:00:00')
                # The form converts the wall-clock draft to UTC on save.
                e.update(dtstart='2026-10-01T18:00:00Z', dtend='2026-10-01T19:00:00Z')
                saved = self.client.post('/api/calendar/events', json=e)
                self.assertEqual(saved.status_code, 200, saved.text)
                uid = saved.json()['uid']
                with fixture.SessionLocal() as db:
                    self.assertEqual(db.get(CalendarEvent, uid).summary, 'Team catchup')
                events = self.client.get('/api/calendar/events', params={'start':'2026-10-01T04:00:00Z', 'end':'2026-10-02T04:00:00Z'}).json()['events']
                self.assertIn(uid, [e['uid'] for e in events])
                resolver.assert_not_called()
                llm.assert_not_called()

    def test_optional_provider_failure_keeps_local_result(self):
        with patch('src.user_time.now_user_local', return_value=NOW), \
             patch('src.endpoint_resolver.resolve_endpoint', return_value=('http://unused', 'unused', {})), \
             patch('src.llm_core.llm_call_async', new=AsyncMock(side_effect=ConnectionError('offline'))):
            r = self.client.post('/api/calendar/quick-parse', json={'text':'Meeting tomorrow at 3pm', 'enhance_ai':True})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['parser'], 'local')
        self.assertEqual(r.json()['event']['dtstart'], '2026-10-01T15:00:00')

    def test_ai_free_cannot_opt_into_inference(self):
        self.client.patch('/api/home/profile', json={'mode':'ai-free'})
        with patch('src.endpoint_resolver.resolve_endpoint', side_effect=AssertionError('blocked')) as resolver:
            r = self.client.post('/api/calendar/quick-parse', json={'text':'Meeting tomorrow at 3pm', 'enhance_ai':True})
            self.assertEqual(r.status_code, 200, r.text)
            self.assertEqual(r.json()['parser'], 'local')
            resolver.assert_not_called()

    def test_all_day_positive_duration_and_home_visibility(self):
        r = self.client.post('/api/calendar/events', json={'summary':'One day', 'dtstart':'2026-09-30', 'dtend':'2026-09-30', 'all_day':True})
        uid = r.json()['uid']
        with fixture.SessionLocal() as db:
            e = db.get(CalendarEvent, uid)
            self.assertEqual((e.dtend-e.dtstart).days, 1)
        events = self.client.get('/api/calendar/events', params={'start':'2026-09-30T04:00:00Z', 'end':'2026-10-01T04:00:00Z'}).json()['events']
        self.assertIn(uid, [e['uid'] for e in events])


if __name__ == '__main__':
    unittest.main(verbosity=2)
