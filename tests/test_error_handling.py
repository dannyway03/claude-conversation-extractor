#!/usr/bin/env python3
"""
Error handling and edge case tests for meaningful coverage
"""

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

# Add parent directory to path before local imports
sys.path.append(str(Path(__file__).parent.parent))

# Local imports after sys.path modification
from extract_claude_logs import ClaudeConversationExtractor, launch_interactive, main


class TestErrorHandling(unittest.TestCase):
    """Test error handling and edge cases"""

    def setUp(self):
        """Set up test environment"""
        self.temp_dir = tempfile.mkdtemp()
        self.claude_dir = Path(self.temp_dir) / "claude" / "projects"
        self.claude_dir.mkdir(parents=True)

    def tearDown(self):
        """Clean up test environment"""
        import shutil

        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_fallback_all_dirs_fail(self):
        """Test init when all directory creation attempts fail"""
        with patch("pathlib.Path.mkdir", side_effect=OSError("Permission denied")):
            with patch("pathlib.Path.touch", side_effect=OSError("No write access")):
                with patch("pathlib.Path.cwd", return_value=Path(self.temp_dir)):
                    extractor = ClaudeConversationExtractor(None, claude_dir=self.claude_dir)
                    self.assertIn("claude-logs", str(extractor.output_dir))

    def test_extract_conversation_permission_error(self):
        """Test extract_conversation with permission error"""
        test_file = Path(self.temp_dir) / "test.jsonl"
        test_file.write_text('{"type": "test"}')

        extractor = ClaudeConversationExtractor(self.temp_dir, claude_dir=self.claude_dir)

        with patch("builtins.open", side_effect=PermissionError("Access denied")):
            with patch("builtins.print") as mock_print:
                result = extractor.extract_conversation(test_file)
                self.assertEqual(result, [])
                mock_print.assert_called()
                args = mock_print.call_args[0][0]
                self.assertIn("Error reading file", args)

    def test_save_as_markdown_write_error(self):
        """Test save_as_markdown with write error"""
        extractor = ClaudeConversationExtractor(self.temp_dir, claude_dir=self.claude_dir)
        conversation = [{"role": "user", "content": "Test", "timestamp": ""}]

        with patch("builtins.open", side_effect=OSError("Disk full")):
            _ = extractor.save_as_markdown(conversation, Path(self.temp_dir) / "test.jsonl")

    def test_list_recent_sessions_no_sessions_messages(self):
        """Test list_recent_sessions prints correct messages when no sessions"""
        extractor = ClaudeConversationExtractor(self.temp_dir, claude_dir=self.claude_dir)

        with patch.object(extractor, "find_sessions", return_value=[]):
            with patch("builtins.print") as mock_print:
                _ = extractor.list_recent_sessions()

                print_calls = [str(call) for call in mock_print.call_args_list]
                self.assertTrue(
                    any("No Claude sessions found" in str(call) for call in print_calls)
                )
                self.assertTrue(
                    any(
                        "Make sure you've used Claude Code" in str(call)
                        for call in print_calls
                    )
                )

    def test_extract_multiple_skip_message(self):
        """Test extract_multiple prints skip message for empty conversations"""
        extractor = ClaudeConversationExtractor(self.temp_dir, claude_dir=self.claude_dir)
        sessions = [Path("test.jsonl")]

        with patch.object(extractor, "extract_conversation", return_value=[]):
            with patch("builtins.print") as mock_print:
                success, total = extractor.extract_multiple(sessions, [0])

                print_calls = [str(call) for call in mock_print.call_args_list]
                self.assertTrue(
                    any("Skipped session" in str(call) for call in print_calls)
                )
                self.assertEqual(success, 0)
                self.assertEqual(total, 1)


class TestMainFunctionErrorCases(unittest.TestCase):
    """Test main() function error handling"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.claude_dir = Path(self.temp_dir) / "claude" / "projects"
        self.claude_dir.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_main_invalid_extract_number_handling(self):
        """Test main handles invalid extract numbers gracefully"""
        with patch("sys.argv", ["prog", "--extract", "abc,1,xyz",
                                "--claude-dir", str(self.claude_dir)]):
            with patch.object(
                ClaudeConversationExtractor,
                "find_sessions",
                return_value=[Path("test.jsonl")],
            ):
                with patch.object(
                    ClaudeConversationExtractor, "extract_multiple",
                    return_value=(1, 1)
                ) as mock_extract:
                    with patch("builtins.print") as mock_print:
                        main()

                        mock_extract.assert_called_once()
                        args = mock_extract.call_args[0]
                        self.assertEqual(args[1], [0])

                        print_calls = [str(call) for call in mock_print.call_args_list]
                        self.assertTrue(
                            any("Invalid session number: abc" in str(call) for call in print_calls)
                        )
                        self.assertTrue(
                            any("Invalid session number: xyz" in str(call) for call in print_calls)
                        )

    def test_main_all_with_no_sessions(self):
        """Test --all command with no sessions found"""
        with patch("sys.argv", ["prog", "--all", "--claude-dir", str(self.claude_dir)]):
            with patch.object(
                ClaudeConversationExtractor, "find_sessions", return_value=[]
            ):
                with patch.object(
                    ClaudeConversationExtractor, "extract_multiple", return_value=(0, 0)
                ) as mock_extract:
                    with patch("builtins.print"):
                        main()
                        mock_extract.assert_called_once_with(
                            [], [], format="markdown", detailed=False
                        )

    def test_main_search_missing_module_raises(self):
        """Test main propagates ImportError when search_conversations is missing"""
        with patch("sys.argv", ["prog", "--search", "test",
                                "--claude-dir", str(self.claude_dir)]):
            with patch.dict("sys.modules", {"search_conversations": None}):
                with patch("builtins.print"):
                    with self.assertRaises((ImportError, TypeError)):
                        main()

    def test_launch_interactive_no_args_calls_ui(self):
        """Test launch_interactive with no extra args invokes interactive UI"""
        with patch("sys.argv", ["prog"]):
            mock_run = Mock()
            mock_ui_instance = Mock(run=mock_run)
            mock_ui_class = Mock(return_value=mock_ui_instance)
            with patch.dict("sys.modules", {
                "interactive_ui": Mock(InteractiveUI=mock_ui_class)
            }):
                launch_interactive()
                mock_ui_class.assert_called_once_with()
                mock_run.assert_called_once()


class TestSearchFunctionality(unittest.TestCase):
    """Test search functionality in main()"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.claude_dir = Path(self.temp_dir) / "claude" / "projects"
        self.claude_dir.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_main_search_basic(self):
        """Test basic search functionality"""
        with patch("sys.argv", ["prog", "--search", "test query",
                                "--claude-dir", str(self.claude_dir)]):
            mock_searcher = Mock()
            mock_searcher.search.return_value = [
                Mock(
                    file_path=Path("test.jsonl"),
                    conversation_id="123",
                    matched_content="test match",
                    speaker="human",
                    relevance_score=0.9,
                )
            ]

            with patch("extract_claude_logs.datetime") as mock_dt:
                mock_dt.now.return_value = datetime(2024, 1, 1)
                mock_dt.fromisoformat = datetime.fromisoformat

                with patch.dict(
                    "sys.modules",
                    {
                        "search_conversations": Mock(
                            ConversationSearcher=Mock(return_value=mock_searcher)
                        )
                    },
                ), patch("builtins.print") as mock_print:
                    with patch("builtins.input", return_value=""):
                        main()

                    mock_searcher.search.assert_called()

                    print_calls = [str(call) for call in mock_print.call_args_list]
                    self.assertTrue(
                        any("Found 1 matches" in str(call) for call in print_calls)
                    )

    def test_main_search_with_filters(self):
        """Test search with all filter options"""
        with patch(
            "sys.argv",
            [
                "prog",
                "--search", "test",
                "--search-speaker", "human",
                "--search-date-from", "2024-01-01",
                "--search-date-to", "2024-12-31",
                "--case-sensitive",
                "--project", self.temp_dir,
                "--claude-dir", str(self.claude_dir),
            ],
        ):
            mock_searcher = Mock()
            mock_searcher.search.return_value = []

            with patch.dict(
                "sys.modules",
                {
                    "search_conversations": Mock(
                        ConversationSearcher=Mock(return_value=mock_searcher)
                    )
                },
            ), patch("builtins.print"):
                # --project validation will fail if dir doesn't exist under claude_dir;
                # encode the temp_dir path and create the directory so validation passes
                from extract_claude_logs import encode_project_path
                encoded = encode_project_path(self.temp_dir)
                (self.claude_dir / encoded).mkdir(parents=True, exist_ok=True)
                main()

                mock_searcher.search.assert_called_once()
                call_kwargs = mock_searcher.search.call_args[1]
                self.assertEqual(call_kwargs["speaker_filter"], "human")
                self.assertTrue(call_kwargs["case_sensitive"])
                self.assertIsNotNone(call_kwargs["search_dir"])


class TestInteractiveMode(unittest.TestCase):
    """Test interactive mode functionality"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.claude_dir = Path(self.temp_dir) / "claude" / "projects"
        self.claude_dir.mkdir(parents=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_main_interactive_flag_launches_ui(self):
        """Test --interactive flag instantiates InteractiveUI and calls run()"""
        with patch("sys.argv", ["prog", "--interactive",
                                "--claude-dir", str(self.claude_dir)]):
            mock_ui = Mock()
            with patch("interactive_ui.InteractiveUI", return_value=mock_ui) as mock_cls:
                main()
                mock_cls.assert_called_once()
                mock_ui.run.assert_called_once()

    def test_main_export_flag_launches_ui(self):
        """Test --export logs flag instantiates InteractiveUI and calls run()"""
        with patch("sys.argv", ["prog", "--export", "logs",
                                "--claude-dir", str(self.claude_dir)]):
            mock_ui = Mock()
            with patch("interactive_ui.InteractiveUI", return_value=mock_ui) as mock_cls:
                main()
                mock_cls.assert_called_once()
                mock_ui.run.assert_called_once()

    def test_main_interactive_passes_project_filter(self):
        """Test --interactive with --project passes the filter to InteractiveUI"""
        encoded = "test-project"
        project_dir = self.claude_dir / encoded
        project_dir.mkdir(parents=True)
        with patch("sys.argv", ["prog", "--interactive",
                                "--project", self.temp_dir,
                                "--claude-dir", str(self.claude_dir)]):
            mock_ui = Mock()
            with patch("interactive_ui.InteractiveUI", return_value=mock_ui) as mock_cls:
                with patch("extract_claude_logs.encode_project_path", return_value=encoded):
                    main()
                    call_kwargs = mock_cls.call_args[1]
                    self.assertIsNotNone(call_kwargs.get("project_filter"))

    def test_launch_interactive_no_args_calls_interactive_main(self):
        """Test launch_interactive() with no args launches interactive UI"""
        with patch("sys.argv", ["prog"]):
            mock_run = Mock()
            mock_ui_instance = Mock(run=mock_run)
            mock_ui_class = Mock(return_value=mock_ui_instance)
            with patch("interactive_ui.InteractiveUI", mock_ui_class):
                launch_interactive()
                mock_ui_class.assert_called_once_with()
                mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
