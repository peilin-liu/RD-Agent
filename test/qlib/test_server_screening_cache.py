import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, patch

from rdagent.log.server.screening import ScreeningSnapshotCache


class ScreeningCacheTests(unittest.TestCase):
    def test_reuses_data_without_leaking_prediction_mutations(self):
        cache = ScreeningSnapshotCache()
        compute = Mock(return_value=[{"symbol": "TEST.SZ", "ma500_slope": 0.2}])
        first = cache.get(("all", "2026-10-30", "qfq"), compute)
        first[0]["pred_rank"] = 1
        second = cache.get(("all", "2026-10-30", "qfq"), compute)
        self.assertNotIn("pred_rank", second[0])
        self.assertEqual(compute.call_count, 1)
        cache.get(("all", "2026-10-30", "none"), compute)
        cache.get(("all", "2026-10-29", "qfq"), compute)
        cache.get(("csi300", "2026-10-30", "qfq"), compute)
        self.assertEqual(compute.call_count, 4)

    def test_expiry_manual_refresh_and_bounded_eviction(self):
        cache = ScreeningSnapshotCache(ttl=300, max_entries=2)
        compute = Mock(return_value=[])
        with patch("rdagent.log.server.screening.time.monotonic", return_value=100) as clock:
            cache.get("a", compute)
            clock.return_value = 101
            cache.get("a", compute)
            self.assertEqual(compute.call_count, 1)
            cache.get("a", compute, refresh=True)
            self.assertEqual(compute.call_count, 2)
            clock.return_value = 402
            cache.get("a", compute)
            self.assertEqual(compute.call_count, 3)
            cache.get("b", compute)
            cache.get("c", compute)
            cache.get("a", compute)
            self.assertEqual(compute.call_count, 6)

    def test_failed_computation_can_be_retried(self):
        cache = ScreeningSnapshotCache()
        compute = Mock(side_effect=[ValueError("unavailable"), [{"symbol": "TEST.SZ"}]])
        with self.assertRaises(ValueError):
            cache.get("key", compute)
        self.assertEqual(cache.get("key", compute), [{"symbol": "TEST.SZ"}])

    def test_concurrent_requests_only_compute_once(self):
        cache = ScreeningSnapshotCache()
        barrier = threading.Barrier(4)
        entered = threading.Event()
        release = threading.Event()

        def compute():
            entered.set()
            self.assertTrue(release.wait(5))
            return [{"symbol": "TEST.SZ"}]

        calculation = Mock(side_effect=compute)

        def request():
            barrier.wait(timeout=5)
            return cache.get("key", calculation)

        with ThreadPoolExecutor(max_workers=4) as pool:
            results = [pool.submit(request) for _ in range(4)]
            self.assertTrue(entered.wait(5))
            release.set()
            self.assertEqual([future.result(timeout=5) for future in results], [[{"symbol": "TEST.SZ"}]] * 4)
        calculation.assert_called_once()
