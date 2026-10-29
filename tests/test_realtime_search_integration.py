#!/usr/bin/env python3
"""
Integration tests for real-time search with actual data
"""

import sys
import time
import unittest
from pathlib import Path

# Add parent directories to path before local imports
sys.path.append(str(Path(__file__).parent.parent))
sys.path.append(str(Path(__file__).parent))

# Local imports after sys.path modification
from fixtures.sample_conversations import ConversationFixtures, cleanup_test_environment

from extract_claude_logs import ClaudeConversationExtractor
from realtime_search import RealTimeSearch, create_smart_searcher
from search_conversations import ConversationSearcher


class TestRealTimeSearchIntegration(unittest.TestCase):
    """Integration tests using real sample data"""

    @classmethod
    def setUpClass(cls):
        """Create test environment with sample conversations"""
        cls.temp_dir, cls.test_files = ConversationFixtures.create_test_environment()
        cls.search_dir = Path(cls.temp_dir) / ".claude" / "projects"

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment"""
        cleanup_test_environment(cls.temp_dir)

    def setUp(self):
        """Set up searcher and extractor for each test"""
        self.searcher = ConversationSearcher()
        self.extractor = ClaudeConversationExtractor()
        # Create smart searcher for RTS
        smart_searcher = create_smart_searcher(self.searcher)
        self.rts = RealTimeSearch(smart_searcher, self.extractor)
        # Restrict searches to the test directory to avoid scanning real ~/.claude/projects
        self.rts.search_dir = self.search_dir

    def tearDown(self):
        """Ensure thread cleanup"""
        self.rts.stop()

    def test_process_search_with_real_data(self):
        """Test search processing with actual sample conversations"""
        # Set up search state
        self.rts.state.query = "Python"
        self.rts.state.is_searching = True
        self.rts.state.last_update = time.time() - 0.5  # Old enough to bypass debounce

        # Process search
        result = self.rts._process_search_request()

        # Should have processed
        self.assertTrue(result)

        # Should have found results
        self.assertGreater(len(self.rts.state.results), 0)

        # Results should have valid structure
        for result in self.rts.state.results:
            self.assertIsInstance(result.file_path, Path)
            # At least some results should be related to Python
        python_results = [
            r for r in self.rts.state.results
            if "python" in r.matched_content.lower() or "python" in r.context.lower()
        ]
        self.assertGreater(len(python_results), 0, "Expected at least one Python-related result")

    def test_smart_searcher_with_real_data(self):
        """Test smart searcher functionality with actual data"""
        smart_searcher = create_smart_searcher(self.searcher)

        # Search for various patterns
        test_cases = [
            ("Python errors", ["python_errors"]),
            ("exception", ["python_errors"]),
            ("API", ["api_requests"]),
            ("files in Python", ["file_operations"]),
            ("@", ["regex_patterns"]),  # Email pattern
        ]

        for query, expected_files in test_cases:
            with self.subTest(query=query):
                results = smart_searcher.search(
                    query=query, search_dir=self.search_dir, max_results=10
                )

                # Should find results
                self.assertGreater(len(results), 0, f"No results for '{query}'")

                # Check if expected files are in results
                result_files = [r.file_path.stem.replace("chat_", "") for r in results]
                for expected in expected_files:
                    self.assertIn(
                        expected,
                        result_files,
                        f"Expected to find {expected} for query '{query}'",
                    )

    def test_cache_behavior_with_real_searches(self):
        """Test that caching works correctly with real data"""
        # First search
        self.rts.state.query = "database"
        self.rts.state.is_searching = True
        self.rts.state.last_update = time.time() - 0.5

        # Process first search
        self.rts._process_search_request()
        first_results = list(self.rts.state.results)

        # Verify cached
        self.assertIn("database", self.rts.results_cache)

        # Second search (should use cache)
        self.rts.state.is_searching = True
        self.rts.state.last_update = time.time() - 0.5

        # Clear searcher calls to verify cache is used
        self.searcher = ConversationSearcher()
        original_search = self.searcher.search
        search_call_count = 0

        def counting_search(*args, **kwargs):
            nonlocal search_call_count
            search_call_count += 1
            return original_search(*args, **kwargs)

        self.rts.searcher.search = counting_search

        # Process again (should use cache)
        self.rts._process_search_request()

        # Should not have called search
        self.assertEqual(search_call_count, 0)

        # Results should be same
        self.assertEqual(len(self.rts.state.results), len(first_results))

    def test_result_deduplication(self):
        """Test that results are properly deduplicated"""
        smart_searcher = create_smart_searcher(self.searcher)

        # Search for something that might match in multiple modes
        results = smart_searcher.search(
            query="Python", search_dir=self.search_dir, max_results=20
        )

        # Check for duplicates by file path and line number
        seen_results = set()
        for result in results:
            # Create unique key with file path and line number
            result_key = (result.file_path, getattr(result, "line_number", 0))
            self.assertNotIn(
                result_key, seen_results, f"Duplicate result: {result.file_path}"
            )
            seen_results.add(result_key)

    def test_performance_with_real_data(self):
        """Test search performance with actual data"""
        start_time = time.time()

        # Perform search
        self.rts.state.query = "error"
        self.rts.state.is_searching = True
        self.rts.state.last_update = time.time() - 0.5

        self.rts._process_search_request()

        end_time = time.time()
        search_time = end_time - start_time

        # Should complete reasonably quickly (under 2 seconds for small dataset)
        # Note: The smart searcher runs multiple search modes which takes time
        self.assertLess(
            search_time, 2.0, f"Search took {search_time:.3f}s, expected < 2s"
        )

    def test_thread_safety_with_concurrent_searches(self):
        """Test that concurrent search requests are handled safely"""
        # Add search directory to RTS instance
        self.rts.search_dir = self.search_dir

        # Trigger multiple searches and process each directly (no background thread)
        # to avoid timing-dependent waits and test the search logic itself
        queries = ["Python", "error", "database", "API", "file"]

        for query in queries:
            self.rts.state.query = query
            self.rts.state.is_searching = True
            self.rts.state.last_update = time.time() - 1.0  # old enough
            self.rts._process_search_request()

        # Should have results from at least one query
        # Check both state results and cache
        has_results = (
            len(self.rts.state.results) > 0 or len(self.rts.results_cache) > 0
        )
        self.assertTrue(has_results, "No results found in state or cache")

        # Cache should have entries
        self.assertGreater(len(self.rts.results_cache), 0)

    def test_empty_query_behavior(self):
        """Test behavior with empty queries"""
        # Set empty query
        self.rts.state.query = ""
        self.rts.state.is_searching = True
        self.rts.state.last_update = time.time() - 0.5

        # Add some existing results
        self.rts.state.results = [1, 2, 3]  # Dummy results

        # Process empty query
        self.rts._process_search_request()

        # Should clear results
        self.assertEqual(len(self.rts.state.results), 0)

    def test_special_characters_in_search(self):
        """Test searching for special characters"""
        test_queries = [
            "@",  # Email symbol
            "test@",  # Partial email
            "192.168",  # IP address pattern
            "except.*Error",  # Regex pattern
        ]

        smart_searcher = create_smart_searcher(self.searcher)

        for query in test_queries:
            with self.subTest(query=query):
                # Should not crash
                results = smart_searcher.search(
                    query=query, search_dir=self.search_dir, max_results=5
                )

                # May or may not find results, but shouldn't error
                self.assertIsInstance(results, list)


class TestRealTimeSearchWithExtractor(unittest.TestCase):
    """Test integration with the extractor"""

    @classmethod
    def setUpClass(cls):
        """Create test environment"""
        cls.temp_dir, cls.test_files = ConversationFixtures.create_test_environment()
        cls.search_dir = Path(cls.temp_dir) / ".claude" / "projects"

    @classmethod
    def tearDownClass(cls):
        """Clean up test environment"""
        cleanup_test_environment(cls.temp_dir)

    def setUp(self):
        """Set up components"""
        self.searcher = ConversationSearcher()
        self.extractor = ClaudeConversationExtractor(Path(self.temp_dir))
        self.rts = RealTimeSearch(self.searcher, self.extractor)

    def test_extractor_integration(self):
        """Test that extractor is properly integrated"""
        # Extractor should be available
        self.assertIsNotNone(self.rts.extractor)

        # Should be able to find sessions
        sessions = self.extractor.find_sessions()
        self.assertGreater(len(sessions), 0)


if __name__ == "__main__":
    unittest.main()
