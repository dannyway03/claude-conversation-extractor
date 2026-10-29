#!/usr/bin/env python3
"""
Aligned tests for extract_claude_logs.py with meaningful coverage
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

# Add parent directory to path before local imports
sys.path.append(str(Path(__file__).parent.parent))

# Local imports after sys.path modification
from extract_claude_logs import ClaudeConversationExtractor, main


class TestClaudeConversationExtractor(unittest.TestCase):
    """Test ClaudeConversationExtractor with proper alignment to actual code"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.claude_dir = Path(self.temp_dir) / ".claude" / "projects"
        self.claude_dir.mkdir(parents=True)
        with patch("builtins.print"):
            with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
                self.extractor = ClaudeConversationExtractor(self.temp_dir)

    def tearDown(self):
        """Clean up test environment"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    # Test initialization
    def test_init_with_custom_output(self):
        """Test initialization with custom output directory"""
        custom_dir = Path(self.temp_dir) / "custom"
        with patch("builtins.print"):
            extractor = ClaudeConversationExtractor(str(custom_dir))
        self.assertEqual(extractor.output_dir, custom_dir)
        self.assertTrue(custom_dir.exists())

    def test_init_with_none_output_fallback(self):
        """Test initialization falls back when directories can't be created"""
        def mkdir_side_effect(self_path, *args, **kwargs):
            # Fail all mkdir calls except the final fallback (exist_ok=True, no parents)
            if kwargs.get("parents"):
                raise OSError("Permission denied")
            # Allow the final fallback mkdir (exist_ok only) to succeed silently

        with patch("pathlib.Path.mkdir", mkdir_side_effect):
            with patch("pathlib.Path.cwd", return_value=Path(self.temp_dir)):
                with patch("builtins.print"):
                    extractor = ClaudeConversationExtractor(None)
                    # Should fall back to current directory
                    self.assertTrue("claude-logs" in str(extractor.output_dir))

    def test_init_creates_output_dir(self):
        """Test that init creates the output directory"""
        output_dir = Path(self.temp_dir) / "test_output"
        with patch("builtins.print"):
            _ = ClaudeConversationExtractor(output_dir)
        self.assertTrue(output_dir.exists())

    # Test find_sessions
    def test_find_sessions_empty(self):
        """Test finding sessions when none exist"""
        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            sessions = self.extractor.find_sessions()
            self.assertEqual(sessions, [])

    def test_find_sessions_with_files(self):
        """Test finding sessions with JSONL files"""
        project_dir = self.claude_dir / "test_project"
        project_dir.mkdir(parents=True)

        (project_dir / "chat_123.jsonl").write_text("{}")
        (project_dir / "chat_456.jsonl").write_text("{}")
        (project_dir / "not_chat.txt").write_text("ignored")

        with patch("pathlib.Path.home", return_value=Path(self.temp_dir)):
            sessions = self.extractor.find_sessions()
            self.assertEqual(len(sessions), 2)
            self.assertTrue(all("chat_" in str(s) for s in sessions))

    def test_find_sessions_with_project_filter(self):
        """Test finding sessions with project path filter"""
        project1 = self.claude_dir / "project1"
        project2 = self.claude_dir / "project2"
        project1.mkdir(parents=True)
        project2.mkdir(parents=True)

        (project1 / "chat_1.jsonl").write_text("{}")
        (project2 / "chat_2.jsonl").write_text("{}")

        # Find only in project1 — self.extractor.claude_dir already points
        # to self.temp_dir/.claude/projects due to the setUp patch
        sessions = self.extractor.find_sessions("project1")
        self.assertEqual(len(sessions), 1)
        self.assertIn("project1", str(sessions[0]))

    # Test extract_conversation
    def test_extract_conversation_valid_jsonl(self):
        """Test extracting valid conversation"""
        jsonl_content = [
            json.dumps(
                {
                    "type": "user",
                    "message": {"role": "user", "content": "Hello"},
                    "timestamp": "2024-01-01T10:00:00Z",
                }
            ),
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "role": "assistant",
                        "content": [{"type": "text", "text": "Hi there!"}],
                    },
                    "timestamp": "2024-01-01T10:01:00Z",
                }
            ),
        ]

        test_file = Path(self.temp_dir) / "test.jsonl"
        test_file.write_text("\n".join(jsonl_content))

        conversation = self.extractor.extract_conversation(test_file)
        self.assertEqual(len(conversation), 2)
        self.assertEqual(conversation[0]["content"], "Hello")
        self.assertEqual(conversation[1]["content"], "Hi there!")

    def test_extract_conversation_with_errors(self):
        """Test extract_conversation handles errors gracefully"""
        test_file = Path(self.temp_dir) / "bad.jsonl"
        test_file.write_text("not json\n{bad json}\n" + json.dumps({"type": "other"}))

        with patch("builtins.print"):
            conversation = self.extractor.extract_conversation(test_file)
            # Should skip bad lines but not crash
            self.assertEqual(conversation, [])

    def test_extract_conversation_nonexistent_file(self):
        """Test extract_conversation with non-existent file"""
        fake_path = Path(self.temp_dir) / "nonexistent.jsonl"

        with patch("builtins.print") as mock_print:
            conversation = self.extractor.extract_conversation(fake_path)
            self.assertEqual(conversation, [])
            # Should print error message
            mock_print.assert_called()

    # Test _extract_text_content
    def test_extract_text_content_string(self):
        """Test extracting text from string content"""
        result = self.extractor._extract_text_content("Simple text")
        self.assertEqual(result, "Simple text")

    def test_extract_text_content_list(self):
        """Test extracting text from list content"""
        content = [
            {"type": "text", "text": "Part 1"},
            {"type": "text", "text": "Part 2"},
            {"type": "image", "data": "..."},  # Should be ignored
        ]
        result = self.extractor._extract_text_content(content)
        self.assertEqual(result, "Part 1\nPart 2")

    def test_extract_text_content_empty(self):
        """Test extracting text from empty content"""
        self.assertEqual(self.extractor._extract_text_content([]), "")
        self.assertEqual(self.extractor._extract_text_content(""), "")
        self.assertEqual(self.extractor._extract_text_content(None), "")

    def test_extract_text_content_other_types(self):
        """Test extracting text from other types"""
        self.assertEqual(self.extractor._extract_text_content(123), "123")
        self.assertEqual(
            self.extractor._extract_text_content({"key": "value"}), "{'key': 'value'}"
        )

    # Test save_as_markdown
    def test_save_as_markdown_basic(self):
        """Test saving basic conversation"""
        conversation = [
            {"role": "user", "content": "Hello", "timestamp": "2024-01-01T10:00:00Z"},
            {
                "role": "assistant",
                "content": "Hi!",
                "timestamp": "2024-01-01T10:01:00Z",
            },
        ]

        output_path = self.extractor.save_as_markdown(conversation, Path(self.temp_dir) / "test_session.jsonl")

        self.assertTrue(output_path.exists())
        content = output_path.read_text()
        self.assertIn("Hello", content)
        self.assertIn("Hi!", content)
        self.assertIn("👤 User", content)
        self.assertIn("🤖 Claude", content)

    def test_save_as_markdown_empty_conversation(self):
        """Test saving empty conversation"""
        result = self.extractor.save_as_markdown([], Path(self.temp_dir) / "empty_session.jsonl")
        self.assertIsNone(result)

    def test_save_as_markdown_no_timestamp(self):
        """Test saving conversation without timestamps"""
        conversation = [
            {"role": "user", "content": "Hello", "timestamp": ""},
            {"role": "assistant", "content": "Hi!", "timestamp": ""},
        ]

        output_path = self.extractor.save_as_markdown(conversation, Path(self.temp_dir) / "no_time.jsonl")
        self.assertTrue(output_path.exists())
        content = output_path.read_text()
        # Should use current date
        self.assertIn(datetime.now().strftime("%Y-%m-%d"), content)

    def test_save_as_markdown_invalid_timestamp(self):
        """Test saving conversation with invalid timestamp"""
        conversation = [
            {"role": "user", "content": "Hello", "timestamp": "invalid-date"}
        ]

        output_path = self.extractor.save_as_markdown(conversation, Path(self.temp_dir) / "bad_time.jsonl")
        self.assertTrue(output_path.exists())
        # Should handle gracefully and use current date
        content = output_path.read_text()
        self.assertIn(datetime.now().strftime("%Y-%m-%d"), content)

    # Test list_recent_sessions
    def test_list_recent_sessions_empty(self):
        """Test listing sessions when none exist"""
        with patch.object(self.extractor, "find_sessions", return_value=[]):
            with patch("builtins.print") as mock_print:
                result = self.extractor.list_recent_sessions()
                self.assertEqual(result, [])
                # Should print error messages
                print_calls = [str(call) for call in mock_print.call_args_list]
                self.assertTrue(
                    any("No Claude sessions found" in str(call) for call in print_calls)
                )

    def test_list_recent_sessions_with_files(self):
        """Test listing sessions with files"""
        # Create actual session files
        mock_sessions = []
        for i in range(15):
            session = Path(self.temp_dir) / f"session{i}.jsonl"
            session.write_text(f'{{"type": "test", "content": "message {i}"}}\n')
            # Set modification time
            timestamp = 1234567890 + i * 1000
            os.utime(session, (timestamp, timestamp))
            mock_sessions.append(session)

        with patch.object(self.extractor, "find_sessions", return_value=mock_sessions):
            with patch("builtins.print"):
                result = self.extractor.list_recent_sessions(limit=5)
                self.assertEqual(len(result), 5)

    # Test extract_multiple
    def test_extract_multiple_success(self):
        """Test extracting multiple sessions successfully"""
        # Create test sessions
        sessions = []
        conversations = []
        for i in range(3):
            session = Path(self.temp_dir) / f"session{i}.jsonl"
            conv = [{"role": "user", "content": f"Test {i}", "timestamp": ""}]
            conversations.append(conv)
            sessions.append(session)

        with patch.object(
            self.extractor, "extract_conversation", side_effect=conversations
        ), patch.object(
            self.extractor, "save_as_markdown", return_value=Path("test.md")
        ), patch("builtins.print"):
            success, total = self.extractor.extract_multiple(
                sessions, [0, 1, 2]
            )
            self.assertEqual(success, 3)
            self.assertEqual(total, 3)

    def test_extract_multiple_with_failures(self):
        """Test extract_multiple with some failures"""
        sessions = [Path("session1.jsonl"), Path("session2.jsonl")]

        # First returns empty, second returns valid
        with patch.object(
            self.extractor,
            "extract_conversation",
            side_effect=[[], [{"role": "user", "content": "Hi"}]],
        ), patch.object(
            self.extractor, "save_as_markdown", return_value=Path("test.md")
        ), patch("builtins.print") as mock_print:
            success, total = self.extractor.extract_multiple(sessions, [0, 1])
            self.assertEqual(success, 1)
            self.assertEqual(total, 2)
            # Should print skip message
            print_calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(any("Skipped" in str(call) for call in print_calls))

    def test_extract_multiple_invalid_indices(self):
        """Test extract_multiple with invalid indices"""
        sessions = [Path("session1.jsonl")]

        with patch("builtins.print") as mock_print:
            success, total = self.extractor.extract_multiple(sessions, [5, -1])
            self.assertEqual(success, 0)
            self.assertEqual(total, 2)
            # Should print error messages
            print_calls = [str(call) for call in mock_print.call_args_list]
            self.assertTrue(
                any("Invalid session number" in str(call) for call in print_calls)
            )


class TestMainFunction(unittest.TestCase):
    """Test the main() function and command-line interface"""

    def setUp(self):
        """Set up isolated temp dirs for all main() tests"""
        self.temp_dir = tempfile.mkdtemp()
        self.claude_dir = Path(self.temp_dir) / ".claude" / "projects"
        self.claude_dir.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_main_no_args_launches_interactive(self):
        """Test that no arguments lists recent sessions (default action)"""
        with patch("sys.argv", ["extract_claude_logs.py", "--output", self.temp_dir]):
            with patch.object(
                ClaudeConversationExtractor, "list_recent_sessions"
            ) as mock_list:
                with patch("builtins.print"):
                    mock_list.return_value = []
                    main()
                    mock_list.assert_called_once()

    def test_main_list_command(self):
        """Test --list command"""
        with patch("sys.argv", ["extract_claude_logs.py", "--list", "--output", self.temp_dir]):
            with patch.object(
                ClaudeConversationExtractor, "list_recent_sessions"
            ) as mock_list:
                with patch("builtins.print"):
                    mock_list.return_value = []
                    main()
                    mock_list.assert_called_once()

    def test_main_extract_single(self):
        """Test --extract with single index"""
        with patch("sys.argv", ["extract_claude_logs.py", "--extract", "1", "--output", self.temp_dir]):
            mock_sessions = [Path("test1.jsonl"), Path("test2.jsonl")]

            with patch.object(
                ClaudeConversationExtractor, "find_sessions", return_value=mock_sessions
            ), patch.object(
                ClaudeConversationExtractor, "extract_multiple", return_value=(1, 1)
            ) as mock_extract, patch.object(
                ClaudeConversationExtractor, "list_recent_sessions"
            ), patch("builtins.print"):
                main()
                # Should extract index 0 (1-based to 0-based)
                mock_extract.assert_called_once()
                args = mock_extract.call_args[0]
                self.assertEqual(args[1], [0])

    def test_main_extract_multiple(self):
        """Test --extract with multiple indices"""
        with patch("sys.argv", ["extract_claude_logs.py", "--extract", "1,3,5", "--output", self.temp_dir]):
            mock_sessions = [Path(f"test{i}.jsonl") for i in range(10)]

            with patch.object(
                ClaudeConversationExtractor, "find_sessions", return_value=mock_sessions
            ), patch.object(
                ClaudeConversationExtractor, "extract_multiple", return_value=(3, 3)
            ) as mock_extract, patch.object(
                ClaudeConversationExtractor, "list_recent_sessions"
            ), patch("builtins.print"):
                main()
                # Should extract indices 0, 2, 4 (1-based to 0-based)
                args = mock_extract.call_args[0]
                self.assertEqual(args[1], [0, 2, 4])

    def test_main_recent(self):
        """Test --recent command"""
        with patch("sys.argv", ["extract_claude_logs.py", "--recent", "3", "--output", self.temp_dir]):
            mock_sessions = [Path(f"test{i}.jsonl") for i in range(10)]

            with patch.object(
                ClaudeConversationExtractor, "find_sessions", return_value=mock_sessions
            ), patch.object(
                ClaudeConversationExtractor, "extract_multiple", return_value=(3, 3)
            ) as mock_extract, patch.object(
                ClaudeConversationExtractor, "list_recent_sessions"
            ), patch("builtins.print"):
                main()
                # Should extract first 3 sessions
                args = mock_extract.call_args[0]
                self.assertEqual(args[1], [0, 1, 2])

    def test_main_all(self):
        """Test --all command"""
        with patch("sys.argv", ["extract_claude_logs.py", "--all", "--output", self.temp_dir]):
            mock_sessions = [Path(f"test{i}.jsonl") for i in range(5)]

            with patch.object(
                ClaudeConversationExtractor, "find_sessions", return_value=mock_sessions
            ), patch.object(
                ClaudeConversationExtractor, "extract_multiple", return_value=(5, 5)
            ) as mock_extract, patch.object(
                ClaudeConversationExtractor, "list_recent_sessions"
            ), patch("builtins.print"):
                main()
                # Should extract all sessions
                args = mock_extract.call_args[0]
                self.assertEqual(args[1], [0, 1, 2, 3, 4])

    def test_main_output_dir(self):
        """Test --output flag"""
        custom_output = self.temp_dir
        with patch(
            "sys.argv", ["extract_claude_logs.py", "--list", "--output", custom_output]
        ), patch("extract_claude_logs.ClaudeConversationExtractor") as mock_class:
            mock_instance = Mock()
            mock_instance.list_recent_sessions.return_value = []
            mock_class.return_value = mock_instance
            with patch("builtins.print"):
                main()
                # Should initialize with custom output
                mock_class.assert_called_once_with(custom_output, None)

    def test_main_interactive_flag(self):
        """Test --interactive flag launches InteractiveUI"""
        with patch("sys.argv", ["extract_claude_logs.py", "--interactive", "--output", self.temp_dir]):
            with patch("builtins.print"):
                with patch("interactive_ui.InteractiveUI") as mock_ui_cls:
                    mock_ui_cls.return_value.run = Mock()
                    main()
                    mock_ui_cls.assert_called_once()
                    mock_ui_cls.return_value.run.assert_called_once()

    def test_main_search(self):
        """Test --search command"""
        with patch("sys.argv", ["extract_claude_logs.py", "--search", "test query", "--output", self.temp_dir]):
            mock_searcher = Mock()
            mock_searcher.search.return_value = []

            with patch("search_conversations.ConversationSearcher", return_value=mock_searcher):
                with patch("builtins.print"):
                    with patch("builtins.input", return_value=""):
                        main()
                        mock_searcher.search.assert_called_once()

    def test_main_invalid_extract_indices(self):
        """Test --extract with invalid indices"""
        with patch("sys.argv", ["extract_claude_logs.py", "--extract", "abc", "--output", self.temp_dir]):
            with patch("builtins.print") as mock_print:
                with patch.object(ClaudeConversationExtractor, "find_sessions", return_value=[]):
                    main()
                    print_calls = [str(call) for call in mock_print.call_args_list]
                    self.assertTrue(any("Invalid" in str(call) for call in print_calls))


if __name__ == "__main__":
    unittest.main()
