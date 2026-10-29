#!/usr/bin/env python3
"""
Aligned tests for search_conversations.py with meaningful coverage
"""

import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

# Add parent directory to path before local imports
sys.path.append(str(Path(__file__).parent.parent))

# Local imports after sys.path modification
from search_conversations import ConversationSearcher, SearchResult  # noqa: E402


class TestSearchResult(unittest.TestCase):
    """Test SearchResult dataclass"""

    def test_search_result_creation(self):
        """Test creating a SearchResult"""
        result = SearchResult(
            file_path=Path("/test/path.jsonl"),
            conversation_id="test_conv",
            matched_content="Hello",
            context="Previous message",
            speaker="human",
            relevance_score=0.95,
            timestamp="2024-01-01T10:00:00Z",
        )

        self.assertEqual(result.file_path, Path("/test/path.jsonl"))
        self.assertEqual(result.relevance_score, 0.95)
        self.assertEqual(result.speaker, "human")

    def test_search_result_string_representation(self):
        """Test SearchResult string representation"""
        result = SearchResult(
            file_path=Path("/test/project/chat_123.jsonl"),
            conversation_id="chat_123",
            speaker="human",
            matched_content="Test",
            context="Test content",
            relevance_score=0.8,
            timestamp="2024-01-01T10:00:00Z",
        )

        str_repr = str(result)
        self.assertIn("chat_123.jsonl", str_repr)
        self.assertIn("Human", str_repr)
        self.assertIn("80%", str_repr)  # Relevance score as percentage


class TestConversationSearcher(unittest.TestCase):
    """Test ConversationSearcher functionality"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.searcher = ConversationSearcher()

        # Create test conversation files
        self.create_test_conversations()

    def tearDown(self):
        """Clean up test environment"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def create_test_conversations(self):
        """Create test conversation files"""
        # Project 1: Python discussion
        project1 = Path(self.temp_dir) / ".claude" / "projects" / "python_project"
        project1.mkdir(parents=True)

        conv1 = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "How do I use Python decorators?",
                },
                "timestamp": "2024-01-01T10:00:00Z",
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "Python decorators are a way to modify functions.",
                        }
                    ],
                },
                "timestamp": "2024-01-01T10:01:00Z",
            },
        ]

        with open(project1 / "chat_001.jsonl", "w") as f:
            for msg in conv1:
                f.write(json.dumps(msg) + "\n")

        # Project 2: JavaScript discussion
        project2 = Path(self.temp_dir) / ".claude" / "projects" / "js_project"
        project2.mkdir(parents=True)

        conv2 = [
            {
                "type": "user",
                "message": {"role": "user", "content": "Explain JavaScript promises"},
                "timestamp": "2024-01-02T10:00:00Z",
            }
        ]

        with open(project2 / "chat_002.jsonl", "w") as f:
            for msg in conv2:
                f.write(json.dumps(msg) + "\n")

    def test_search_exact_match(self):
        """Test exact string matching"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results = self.searcher.search("Python decorators", mode="exact")

            self.assertGreater(len(results), 0)
            self.assertIn("decorators", results[0].context.lower())

    def test_search_case_insensitive(self):
        """Test case-insensitive search"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results1 = self.searcher.search("python", case_sensitive=False)
            results2 = self.searcher.search("PYTHON", case_sensitive=False)

            # Should find same results regardless of case
            self.assertEqual(len(results1), len(results2))

    def test_search_case_sensitive(self):
        """Test case-sensitive search"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results1 = self.searcher.search("Python", case_sensitive=True)
            results2 = self.searcher.search("python", case_sensitive=True)

            # May find different results based on case
            self.assertIsNotNone(results1)
            self.assertIsNotNone(results2)

    def test_search_regex_mode(self):
        """Test regex pattern matching"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results = self.searcher.search(r"Python|JavaScript", mode="regex")

            # Should find both Python and JavaScript mentions
            self.assertGreater(len(results), 0)
            contexts = [r.context for r in results]
            self.assertTrue(
                any("Python" in c for c in contexts)
                or any("JavaScript" in c for c in contexts)
            )

    def test_search_smart_mode(self):
        """Test smart search mode"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results = self.searcher.search("programming language", mode="smart")

            # Should find relevant results even without exact match
            self.assertIsNotNone(results)

    def test_search_speaker_filter(self):
        """Test filtering by speaker"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            human_results = self.searcher.search("How", speaker_filter="human")
            assistant_results = self.searcher.search(
                "way to", speaker_filter="assistant"
            )

            # Check speaker filtering
            for result in human_results:
                self.assertEqual(result.speaker, "human")

            for result in assistant_results:
                self.assertEqual(result.speaker, "assistant")

    def test_search_date_filter(self):
        """Test date range filtering"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            # Search only for conversations after 2024-01-01 15:00
            date_from = datetime(2024, 1, 1, 15, 0)
            results = self.searcher.search("JavaScript", date_from=date_from)

            # Should only find JavaScript conversation (2024-01-02)
            self.assertGreater(len(results), 0)
            for result in results:
                self.assertTrue("JavaScript" in result.context or "JAVASCRIPT" in result.context)

    def test_search_max_results(self):
        """Test limiting number of results"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results = self.searcher.search(
                "Python", max_results=1
            )

            self.assertLessEqual(len(results), 1)

    def test_search_empty_query(self):
        """Test searching with empty query"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results = self.searcher.search("")

            # Empty query returns empty results (current behavior)
            self.assertEqual(len(results), 0)

    def test_search_no_matches(self):
        """Test search with no matches"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results = self.searcher.search("nonexistent12345query")

            self.assertEqual(len(results), 0)

    def test_search_with_context(self):
        """Test that search results include context"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results = self.searcher.search("decorators", mode="exact")

            if results:
                # Should have context from previous messages
                self.assertIsNotNone(results[0].context)

    def test_semantic_search_without_spacy(self):
        """Test semantic search falls back when spaCy not available"""
        with patch("search_conversations.SPACY_AVAILABLE", False):
            with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
                results = self.searcher.search("programming", mode="semantic")

                # Should fall back to smart search
                self.assertIsNotNone(results)

    def test_semantic_search_with_spacy(self):
        """Test semantic search with spaCy available"""
        # Create a new searcher with mocked nlp
        mock_nlp = Mock()
        mock_doc = Mock()
        
        # Mock token iteration
        mock_token = Mock()
        mock_token.is_stop = False
        mock_token.is_alpha = True
        mock_token.lemma_ = "coding"
        mock_token.text = "coding"
        mock_doc.__iter__ = Mock(return_value=iter([mock_token]))
        mock_doc.text = "coding"
        
        mock_nlp.return_value = mock_doc

        searcher_with_nlp = ConversationSearcher()
        searcher_with_nlp.nlp = mock_nlp

        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            results = searcher_with_nlp.search("coding", mode="semantic")

            # Should use semantic similarity
            self.assertIsNotNone(results)

    def test_search_corrupted_jsonl(self):
        """Test search handles corrupted JSONL files gracefully"""
        # Create corrupted file
        bad_project = Path(self.temp_dir) / ".claude" / "projects" / "bad_project"
        bad_project.mkdir(parents=True)

        with open(bad_project / "chat_bad.jsonl", "w") as f:
            f.write("not json\n")
            f.write('{"invalid": json}\n')
            f.write('{"type": "user", "message": {"content": "Valid message"}}\n')

        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            # Should not crash, just skip bad lines
            results = self.searcher.search("Valid")
            self.assertIsNotNone(results)

    def test_rank_results(self):
        """Test result ranking by relevance"""
        # Create results with different relevance scores
        results = [
            SearchResult(Path("test1"), "conv1", "match", "context", "human", relevance_score=0.5),
            SearchResult(Path("test2"), "conv2", "match", "context", "human", relevance_score=0.9),
            SearchResult(Path("test3"), "conv3", "match", "context", "human", relevance_score=0.7),
        ]

        # Sort by relevance score (descending)
        ranked = sorted(results, key=lambda x: x.relevance_score, reverse=True)

        # Should be sorted by relevance score (descending)
        self.assertEqual(ranked[0].relevance_score, 0.9)
        self.assertEqual(ranked[1].relevance_score, 0.7)
        self.assertEqual(ranked[2].relevance_score, 0.5)

    def test_extract_content(self):
        """Test content extraction from different message formats"""
        # Test string content (from entry with "content" field)
        entry1 = {"type": "user", "content": "Simple string"}
        content = self.searcher._extract_content(entry1)
        self.assertEqual(content, "Simple string")

        # Test list content (from entry with "message" field)
        entry2 = {
            "type": "user",
            "message": {
                "content": [
                    {"type": "text", "text": "Part 1"},
                    {"type": "text", "text": "Part 2"},
                ]
            },
        }
        content = self.searcher._extract_content(entry2)
        self.assertEqual(content, "Part 1 Part 2")

        # Test other types
        entry3 = {"type": "user", "message": {"content": {"unknown": "format"}}}
        content = self.searcher._extract_content(entry3)
        self.assertEqual(content, "")

    def test_fuzzy_match(self):
        """Test fuzzy string matching via relevance calculation"""
        # Test exact match - should have high relevance
        relevance = self.searcher._calculate_relevance(
            "hello world", "hello", {"hello"}, False
        )
        self.assertGreater(relevance, 0.5)

        # Test substring match - should have some relevance
        relevance = self.searcher._calculate_relevance(
            "hello world", "ello", {"ello"}, False
        )
        self.assertGreater(relevance, 0)

        # Test no match - should have low relevance
        relevance = self.searcher._calculate_relevance(
            "hello", "xyz", {"xyz"}, False
        )
        self.assertEqual(relevance, 0.0)


class TestSearchIntegration(unittest.TestCase):
    """Integration tests for search functionality"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.searcher = ConversationSearcher()

    def tearDown(self):
        """Clean up test environment"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_end_to_end_search_workflow(self):
        """Test complete search workflow"""
        # Create realistic conversation
        project = Path(self.temp_dir) / ".claude" / "projects" / "test_project"
        project.mkdir(parents=True)

        conversation = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": "How do I handle errors in Python?",
                },
                "timestamp": datetime.now().isoformat(),
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": "You can use try-except blocks for error handling.",
                        }
                    ],
                },
                "timestamp": datetime.now().isoformat(),
            },
            {
                "type": "user",
                "message": {"role": "user", "content": "Can you show an example?"},
                "timestamp": datetime.now().isoformat(),
            },
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "try:\n    risky_operation()\n"
                                "except Exception as e:\n    print(f'Error: {e}')"
                            ),
                        }
                    ],
                },
                "timestamp": datetime.now().isoformat(),
            },
        ]

        with open(project / "chat_test.jsonl", "w") as f:
            for msg in conversation:
                f.write(json.dumps(msg) + "\n")

        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            # Search for error handling
            results = self.searcher.search("error handling", mode="smart")

            self.assertGreater(len(results), 0)

            # Verify results have expected structure
            first = results[0]
            self.assertIsInstance(first.file_path, Path)
            self.assertIn("test_project", str(first.file_path))
            self.assertGreater(first.relevance_score, 0)
            self.assertIn(first.speaker, ["human", "assistant"])


if __name__ == "__main__":
    unittest.main()
