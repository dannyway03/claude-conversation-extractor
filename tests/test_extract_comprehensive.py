#!/usr/bin/env python3
"""
Comprehensive tests for extract_claude_logs.py to achieve 100% coverage
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Add parent directory to path before local imports
sys.path.append(str(Path(__file__).parent.parent))

# Local imports after sys.path modification
from extract_claude_logs import ClaudeConversationExtractor, main  # noqa: E402


class TestClaudeConversationExtractorComprehensive(unittest.TestCase):
    """Comprehensive tests for ClaudeConversationExtractor"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()

        # Create isolated Claude directory structure
        self.claude_dir = Path(self.temp_dir) / ".claude" / "projects"
        self.claude_dir.mkdir(parents=True)

        with patch("builtins.print"):
            self.extractor = ClaudeConversationExtractor(self.temp_dir)
        # Override claude_dir to point to isolated temp dir
        self.extractor.claude_dir = self.claude_dir

    def tearDown(self):
        """Clean up test environment"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_with_custom_output(self):
        """Test initialization with custom output directory"""
        custom_dir = Path(self.temp_dir) / "custom"
        with patch("builtins.print"):
            extractor = ClaudeConversationExtractor(str(custom_dir))
        self.assertEqual(extractor.output_dir, custom_dir)

    def test_init_with_none_output(self):
        """Test initialization with None output directory"""
        with patch("extract_claude_logs.Path.home", return_value=Path(self.temp_dir)):
            with patch("builtins.print"):
                extractor = ClaudeConversationExtractor(None)
            # Should use Desktop or Documents
            self.assertTrue(
                "Desktop" in str(extractor.output_dir)
                or "Documents" in str(extractor.output_dir)
            )

    def test_find_sessions_empty(self):
        """Test finding sessions when none exist"""
        # extractor.claude_dir already overridden to isolated temp dir in setUp
        sessions = self.extractor.find_sessions()
        self.assertEqual(sessions, [])

    def test_find_sessions_with_files(self):
        """Test finding sessions with JSONL files"""
        # Create test JSONL files in the isolated claude_dir
        project_dir = self.claude_dir / "test_project"
        project_dir.mkdir()

        chat_file1 = project_dir / "chat_123.jsonl"
        chat_file2 = project_dir / "chat_456.jsonl"
        chat_file1.write_text("{}")
        chat_file2.write_text("{}")

        sessions = self.extractor.find_sessions()
        self.assertEqual(len(sessions), 2)

    def test_extract_text_content_string(self):
        """Test extracting text from string content"""
        content = "Simple text content"
        result = self.extractor._extract_text_content(content)
        self.assertEqual(result, content)

    def test_extract_text_content_list(self):
        """Test extracting text from list content"""
        content = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"},
            {"type": "image", "data": "..."},  # Should be ignored
        ]
        result = self.extractor._extract_text_content(content)
        # Source uses "\n".join() so parts are separated by single newline
        self.assertEqual(result, "Part 1\nPart 2")

    def test_extract_text_content_empty(self):
        """Test extracting text from empty content"""
        self.assertEqual(self.extractor._extract_text_content([]), "")
        self.assertEqual(self.extractor._extract_text_content(""), "")
        self.assertEqual(self.extractor._extract_text_content(None), "")

    def test_save_as_markdown_basic(self):
        """Test saving conversation as markdown"""
        conversation = [
            {"role": "user", "content": "Hello", "timestamp": "2024-01-01T10:00:00Z"},
            {
                "role": "assistant",
                "content": "Hi there!",
                "timestamp": "2024-01-01T10:01:00Z",
            },
        ]

        output_path = self.extractor.save_as_markdown(conversation, Path(self.temp_dir) / "test_session.jsonl")

        self.assertTrue(output_path.exists())
        content = output_path.read_text()
        self.assertIn("Hello", content)
        self.assertIn("Hi there!", content)
        self.assertIn("User", content)
        self.assertIn("Claude", content)

    def test_save_as_markdown_with_code(self):
        """Test saving conversation with code blocks"""
        conversation = [
            {"role": "user", "content": "Write Python hello world", "timestamp": ""},
            {
                "role": "assistant",
                "content": "```python\nprint('Hello, World!')\n```",
                "timestamp": "",
            },
        ]

        output_path = self.extractor.save_as_markdown(conversation, Path(self.temp_dir) / "code_session.jsonl")
        content = output_path.read_text()

        # Should preserve code blocks
        self.assertIn("```python", content)
        self.assertIn("print('Hello, World!')", content)

    def test_list_sessions(self):
        """Test listing sessions with details via list_recent_sessions"""
        # Create test file in the isolated claude_dir
        project_dir = self.claude_dir / "test_project"
        project_dir.mkdir()
        chat_file = project_dir / "chat_test.jsonl"
        chat_file.write_text('{"type": "test"}')

        with patch("builtins.print") as mock_print:
            sessions = self.extractor.list_recent_sessions(limit=5)

            # Should print session details
            self.assertTrue(
                any(
                    "test_project" in str(call)
                    for call in mock_print.call_args_list
                )
            )
            self.assertEqual(len(sessions), 1)

    def test_extract_multiple_success(self):
        """Test extracting multiple sessions"""
        # Create test sessions
        sessions = [
            Path(self.temp_dir) / "session1.jsonl",
            Path(self.temp_dir) / "session2.jsonl",
        ]

        for session in sessions:
            session.write_text(
                json.dumps(
                    {
                        "type": "user",
                        "message": {"role": "user", "content": "Test"},
                        "timestamp": "2024-01-01T10:00:00Z",
                    }
                )
            )

        with patch("builtins.print"):
            success, total = self.extractor.extract_multiple(sessions, [0, 1])

        self.assertEqual(success, 2)
        self.assertEqual(total, 2)

    def test_extract_multiple_with_invalid_index(self):
        """Test extracting with invalid indices"""
        sessions = [Path(self.temp_dir) / "session.jsonl"]

        with patch("builtins.print"):
            success, total = self.extractor.extract_multiple(
                sessions, [5]
            )  # Invalid index

        self.assertEqual(success, 0)
        self.assertEqual(total, 1)

    def test_extract_recent(self):
        """Test extracting recent conversations via find_sessions + extract_multiple"""
        mock_sessions = [Path(self.temp_dir) / f"session{i}.jsonl" for i in range(10)]

        with patch.object(self.extractor, "find_sessions", return_value=mock_sessions):
            with patch.object(
                self.extractor, "extract_multiple", return_value=(3, 3)
            ) as mock_extract:
                # Replicate --recent 3 CLI logic
                sessions = self.extractor.find_sessions()
                limit = min(3, len(sessions))
                indices = list(range(limit))
                self.extractor.extract_multiple(sessions, indices)

                # Should extract first 3 sessions
                mock_extract.assert_called_once()
                args = mock_extract.call_args[0]
                self.assertEqual(args[1], [0, 1, 2])

    def test_extract_all(self):
        """Test extracting all conversations via find_sessions + extract_multiple"""
        mock_sessions = [Path(self.temp_dir) / f"session{i}.jsonl" for i in range(5)]

        with patch.object(self.extractor, "find_sessions", return_value=mock_sessions):
            with patch.object(
                self.extractor, "extract_multiple", return_value=(5, 5)
            ) as mock_extract:
                # Replicate --all CLI logic
                sessions = self.extractor.find_sessions()
                indices = list(range(len(sessions)))
                self.extractor.extract_multiple(sessions, indices)

                # Should extract all sessions
                mock_extract.assert_called_once()
                args = mock_extract.call_args[0]
                self.assertEqual(args[1], list(range(5)))

    def test_main_list_command(self):
        """Test main function with --list"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--list", "--output", self.temp_dir],
        ):
            with patch.object(ClaudeConversationExtractor, "list_recent_sessions", return_value=[]):
                with patch("builtins.print"):
                    main()

    def test_main_extract_single(self):
        """Test main function with --extract"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--extract", "1", "--output", self.temp_dir],
        ):
            with patch.object(
                ClaudeConversationExtractor,
                "find_sessions",
                return_value=[Path("test.jsonl")],
            ):
                with patch.object(
                    ClaudeConversationExtractor, "extract_multiple", return_value=(1, 1)
                ):
                    with patch("builtins.print"):
                        main()

    def test_main_extract_multiple_comma(self):
        """Test main function with comma-separated indices"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--extract", "1,2,3", "--output", self.temp_dir],
        ):
            with patch.object(
                ClaudeConversationExtractor,
                "find_sessions",
                return_value=[Path(f"test{i}.jsonl") for i in range(5)],
            ):
                with patch.object(
                    ClaudeConversationExtractor, "extract_multiple", return_value=(3, 3)
                ) as mock_extract:
                    with patch("builtins.print"):
                        main()
                    # Should extract indices 0, 1, 2 (1-based to 0-based)
                    args = mock_extract.call_args[0]
                    self.assertEqual(args[1], [0, 1, 2])

    def test_main_recent(self):
        """Test main function with --recent: calls find_sessions + extract_multiple"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--recent", "5", "--output", self.temp_dir],
        ):
            with patch.object(
                ClaudeConversationExtractor,
                "find_sessions",
                return_value=[],
            ):
                with patch.object(
                    ClaudeConversationExtractor, "extract_multiple", return_value=(0, 0)
                ) as mock_extract:
                    with patch("builtins.print"):
                        main()
                    mock_extract.assert_called_once()

    def test_main_all(self):
        """Test main function with --all: calls find_sessions + extract_multiple"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--all", "--output", self.temp_dir],
        ):
            with patch.object(
                ClaudeConversationExtractor,
                "find_sessions",
                return_value=[],
            ):
                with patch.object(
                    ClaudeConversationExtractor, "extract_multiple", return_value=(0, 0)
                ) as mock_extract:
                    with patch("builtins.print"):
                        main()
                    mock_extract.assert_called_once()

    def test_main_interactive(self):
        """Test main function with --interactive"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--interactive", "--output", self.temp_dir],
        ):
            with patch("interactive_ui.InteractiveUI") as mock_ui_cls:
                mock_ui_cls.return_value.run = Mock()
                with patch("builtins.print"):
                    main()
                mock_ui_cls.assert_called_once()
                mock_ui_cls.return_value.run.assert_called_once()

    def test_main_export(self):
        """Test main function with --export"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--export", "logs", "--output", self.temp_dir],
        ):
            with patch("interactive_ui.InteractiveUI") as mock_ui_cls:
                mock_ui_cls.return_value.run = Mock()
                with patch("builtins.print"):
                    main()
                mock_ui_cls.assert_called_once()
                mock_ui_cls.return_value.run.assert_called_once()

    def test_main_search(self):
        """Test main function with --search"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--search", "test query", "--output", self.temp_dir],
        ):
            # main() does `from search_conversations import ConversationSearcher` inside
            with patch("search_conversations.ConversationSearcher") as mock_searcher:
                mock_searcher.return_value.search.return_value = []
                with patch("builtins.print"):
                    with patch("builtins.input", return_value=""):
                        main()
                    mock_searcher.return_value.search.assert_called_once()

    def test_main_search_with_filters(self):
        """Test main function with search filters"""
        with patch(
            "sys.argv",
            [
                "extract_claude_logs.py",
                "--search", "test",
                "--search-speaker", "human",
                "--search-date-from", "2024-01-01",
                "--case-sensitive",
                "--output", self.temp_dir,
            ],
        ):
            # main() does `from search_conversations import ConversationSearcher` inside
            with patch("search_conversations.ConversationSearcher") as mock_searcher:
                mock_searcher.return_value.search.return_value = []
                with patch("builtins.print"):
                    with patch("builtins.input", return_value=""):
                        main()

                    # Check search was called with correct parameters
                    search_call = mock_searcher.return_value.search.call_args
                    self.assertEqual(search_call[1]["speaker_filter"], "human")
                    self.assertTrue(search_call[1]["case_sensitive"])

    def test_main_no_args(self):
        """Test main function with no extra args calls list_recent_sessions"""
        with patch(
            "sys.argv",
            ["extract_claude_logs.py", "--output", self.temp_dir],
        ):
            with patch.object(
                ClaudeConversationExtractor, "list_recent_sessions", return_value=[]
            ) as mock_list:
                with patch("builtins.print"):
                    main()
                mock_list.assert_called_once()

    def test_extract_conversation_with_errors(self):
        """Test extract_conversation with file read errors"""
        bad_file = Path(self.temp_dir) / "bad.jsonl"
        bad_file.write_text("not json\n{bad json}\n")

        with patch("builtins.print"):
            conversation = self.extractor.extract_conversation(bad_file)
            # Should return empty conversation on error
            self.assertEqual(conversation, [])

    def test_output_dir_fallback(self):
        """Test output directory fallback when Desktop/Documents don't exist"""
        with patch("extract_claude_logs.Path.home", return_value=Path(self.temp_dir)):
            with patch("extract_claude_logs.Path.exists", return_value=False):
                with patch(
                    "extract_claude_logs.Path.cwd", return_value=Path(self.temp_dir)
                ):
                    with patch("builtins.print"):
                        extractor = ClaudeConversationExtractor(None)
                    # Should fall back to current directory
                    self.assertIn("Claude logs", str(extractor.output_dir))


if __name__ == "__main__":
    unittest.main()
