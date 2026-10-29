#!/usr/bin/env python3
"""
Extract clean conversation logs from Claude Code's internal JSONL files

This tool parses the undocumented JSONL format used by Claude Code to store
conversations locally in ~/.claude/projects/ and exports them as clean,
readable markdown files.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def encode_project_path(path_arg: str) -> str:
    """Map a real filesystem path to Claude Code's project directory name.

    Claude Code stores conversations under ``~/.claude/projects/<encoded>``,
    where ``<encoded>`` is the project's source path with ``/`` and ``.``
    each replaced by ``-`` and a leading ``-`` from the absolute root.

    Args:
        path_arg: Path string. May be absolute, relative, contain ``~``,
            ``.``, or ``..``. Will be expanded and resolved before encoding.

    Returns:
        The encoded directory name (no path separator, no leading slash).

    Note:
        Does not validate that the path exists. Follows symlinks via
        ``Path.resolve()`` — if the caller passed a symlink, the encoded
        name reflects the symlink target, not the link path.
    """
    resolved = Path(path_arg).expanduser().resolve()
    return str(resolved).replace("/", "-").replace(".", "-")


class ClaudeConversationExtractor:
    """Extract and convert Claude Code conversations from JSONL to markdown."""

    def __init__(self, output_dir: Path | None = None, claude_dir: Path | None = None):
        """Initialize the extractor with Claude's directory and output location.

        Args:
            output_dir: Directory to save extracted conversations
            claude_dir: Claude's projects directory (defaults to ~/.claude/projects)
        """
        # Determine claude_dir from parameter, env var, or default
        if claude_dir:
            self.claude_dir = Path(claude_dir)
        elif os.environ.get("CLAUDE_DIR"):
            self.claude_dir = Path(os.environ["CLAUDE_DIR"])
        elif os.environ.get("PROJECT_DIR"):
            self.claude_dir = Path(os.environ["PROJECT_DIR"])
        else:
            self.claude_dir = Path.home() / ".claude" / "projects"

        if output_dir:
            self.output_dir = Path(output_dir)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        else:
            # Try multiple possible output directories
            possible_dirs = [
                Path.home() / "Desktop" / "Claude logs",
                Path.home() / "Documents" / "Claude logs",
                Path.home() / "Claude logs",
                Path.cwd() / "claude-logs",
            ]

            # Use the first directory we can create
            for dir_path in possible_dirs:
                try:
                    dir_path.mkdir(parents=True, exist_ok=True)
                    # Test if we can write to it
                    test_file = dir_path / ".test"
                    test_file.touch()
                    test_file.unlink()
                    self.output_dir = dir_path
                    break
                except (OSError, PermissionError) as e:
                    logger.debug(f"Cannot use {dir_path}: {e}")
                    continue
            else:
                # Fallback to current directory — don't raise if mkdir fails
                self.output_dir = Path.cwd() / "claude-logs"
                try:
                    self.output_dir.mkdir(exist_ok=True)
                except (OSError, PermissionError) as e:
                    logger.debug(
                        f"Cannot create fallback directory {self.output_dir}: {e}"
                    )

        print(f"📁 Saving logs to: {self.output_dir}")

    def find_sessions(self, project_path: str | None = None) -> list[Path]:
        """Find all JSONL session files, sorted by most recent first."""
        if project_path:
            search_dir = self.claude_dir / project_path
        else:
            search_dir = self.claude_dir

        sessions = list(search_dir.rglob("*.jsonl")) if search_dir.exists() else []
        return sorted(sessions, key=lambda x: x.stat().st_mtime, reverse=True)

    def extract_conversation(
        self, jsonl_path: Path, detailed: bool = False
    ) -> list[dict[str, str]]:
        """Extract conversation messages from a JSONL file.

        Args:
            jsonl_path: Path to the JSONL file
            detailed: If True, include tool use, MCP responses, and system messages
        """
        conversation = []

        try:
            with open(jsonl_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())

                        # Extract user messages
                        if entry.get("type") == "user" and "message" in entry:
                            msg = entry["message"]
                            if isinstance(msg, dict) and msg.get("role") == "user":
                                content = msg.get("content", "")
                                text = self._extract_text_content(content)

                                if text and text.strip():
                                    conversation.append(
                                        {
                                            "role": "user",
                                            "content": text,
                                            "timestamp": entry.get("timestamp", ""),
                                        }
                                    )

                        # Extract assistant messages
                        elif entry.get("type") == "assistant" and "message" in entry:
                            msg = entry["message"]
                            if isinstance(msg, dict) and msg.get("role") == "assistant":
                                content = msg.get("content", [])
                                text = self._extract_text_content(
                                    content, detailed=detailed
                                )

                                if text and text.strip():
                                    conversation.append(
                                        {
                                            "role": "assistant",
                                            "content": text,
                                            "timestamp": entry.get("timestamp", ""),
                                        }
                                    )

                        # Include tool use and system messages if detailed mode
                        elif detailed:
                            # Extract tool use events
                            if entry.get("type") == "tool_use":
                                tool_data = entry.get("tool", {})
                                tool_name = tool_data.get("name", "unknown")
                                tool_input = tool_data.get("input", {})
                                conversation.append(
                                    {
                                        "role": "tool_use",
                                        "content": f"🔧 Tool: {tool_name}\nInput: {json.dumps(tool_input, indent=2)}",
                                        "timestamp": entry.get("timestamp", ""),
                                    }
                                )

                            # Extract tool results
                            elif entry.get("type") == "tool_result":
                                result = entry.get("result", {})
                                output = result.get("output", "") or result.get(
                                    "error", ""
                                )
                                conversation.append(
                                    {
                                        "role": "tool_result",
                                        "content": f"📤 Result:\n{output}",
                                        "timestamp": entry.get("timestamp", ""),
                                    }
                                )

                            # Extract system messages
                            elif entry.get("type") == "system" and "message" in entry:
                                msg = entry.get("message", "")
                                if msg:
                                    conversation.append(
                                        {
                                            "role": "system",
                                            "content": f"ℹ️ System: {msg}",
                                            "timestamp": entry.get("timestamp", ""),
                                        }
                                    )

                    except json.JSONDecodeError:
                        continue
                    except (KeyError, TypeError, AttributeError) as e:
                        # Silently skip problematic entries
                        logger.debug(f"Skipping problematic entry: {e}")
                        continue

        except OSError as e:
            print(f"❌ Error reading file {jsonl_path}: {e}")

        return conversation

    def _extract_text_content(self, content, detailed: bool = False) -> str:
        """Extract text from various content formats Claude uses.

        Args:
            content: The content to extract from
            detailed: If True, include tool use blocks and other metadata
        """
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            # Extract text from content array
            text_parts = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        text_parts.append(item.get("text", ""))
                    elif detailed and item.get("type") == "tool_use":
                        # Include tool use details in detailed mode
                        tool_name = item.get("name", "unknown")
                        tool_input = item.get("input", {})
                        text_parts.append(f"\n🔧 Using tool: {tool_name}")
                        text_parts.append(
                            f"Input: {json.dumps(tool_input, indent=2)}\n"
                        )
            return "\n".join(text_parts)
        elif content is None:
            return ""
        else:
            return str(content)

    def _format_session_id(self, jsonl_path: Path) -> str:
        """Extract session ID components from file path.

        For subagent sessions (in subagents/ directory), includes parent UUID prefix.
        For regular UUID sessions, uses first 8 characters.

        Args:
            jsonl_path: Path to the JSONL session file

        Returns:
            Formatted session ID string for filename
        """
        session_id = jsonl_path.stem

        # Check if this is a subagent session
        if "subagents" in jsonl_path.parts:
            # Get parent UUID from directory name (parent of 'subagents')
            subagents_idx = jsonl_path.parts.index("subagents")
            parent_uuid = jsonl_path.parts[subagents_idx - 1]
            uuid_prefix = parent_uuid[:8]
            return f"{uuid_prefix}-{session_id}"

        # Regular UUID session
        if re.match(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
            session_id.lower(),
        ):
            return session_id[:8]

        return session_id

    def display_conversation(self, jsonl_path: Path, detailed: bool = False) -> None:
        """Display a conversation in the terminal with pagination.

        Args:
            jsonl_path: Path to the JSONL file
            detailed: If True, include tool use and system messages
        """
        try:
            # Extract conversation
            messages = self.extract_conversation(jsonl_path, detailed=detailed)

            if not messages:
                print("❌ No messages found in conversation")
                return

            # Get session info
            session_id = jsonl_path.stem

            # Clear screen and show header
            print("\033[2J\033[H", end="")  # Clear screen
            print("=" * 60)
            print(f"📄 Viewing: {jsonl_path.parent.name}")
            print(f"Session: {session_id[:8]}...")

            # Get timestamp from first message
            first_timestamp = messages[0].get("timestamp", "")
            if first_timestamp:
                try:
                    dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
                    print(f"Date: {dt.strftime('%Y-%m-%d %H:%M:%S')}")
                except (ValueError, TypeError):
                    pass

            print("=" * 60)
            print("↑↓ to scroll • Q to quit • Enter to continue\n")

            # Display messages with pagination
            lines_shown = 8  # Header lines
            lines_per_page = 30

            for i, msg in enumerate(messages):
                role = msg["role"]
                content = msg["content"]

                # Format role display
                if role == "user" or role == "human":
                    print(f"\n{'─' * 40}")
                    print("👤 HUMAN:")
                    print(f"{'─' * 40}")
                elif role == "assistant":
                    print(f"\n{'─' * 40}")
                    print("🤖 CLAUDE:")
                    print(f"{'─' * 40}")
                elif role == "tool_use":
                    print("\n🔧 TOOL USE:")
                elif role == "tool_result":
                    print("\n📤 TOOL RESULT:")
                elif role == "system":
                    print("\nℹ️ SYSTEM:")
                else:
                    print(f"\n{role.upper()}:")

                # Display content (limit very long messages)
                lines = content.split("\n")
                max_lines_per_msg = 50

                for line_idx, line in enumerate(lines[:max_lines_per_msg]):
                    # Wrap very long lines
                    if len(line) > 100:
                        line = line[:97] + "..."
                    print(line)
                    lines_shown += 1

                    # Check if we need to paginate
                    if lines_shown >= lines_per_page:
                        response = (
                            input("\n[Enter] Continue • [Q] Quit: ").strip().upper()
                        )
                        if response == "Q":
                            print("\n👋 Stopped viewing")
                            return
                        # Clear screen for next page
                        print("\033[2J\033[H", end="")
                        lines_shown = 0

                if len(lines) > max_lines_per_msg:
                    print(
                        f"... [{len(lines) - max_lines_per_msg} more lines truncated]"
                    )
                    lines_shown += 1

            print("\n" + "=" * 60)
            print("📄 End of conversation")
            print("=" * 60)
            input("\nPress Enter to continue...")

        except (OSError, ValueError, KeyError) as e:
            print(f"❌ Error displaying conversation: {e}")
            input("\nPress Enter to continue...")

    def save_as_markdown(
        self, conversation: list[dict[str, str]], jsonl_path: Path
    ) -> Path | None:
        """Save conversation as clean markdown file."""
        if not conversation:
            return None

        # Get timestamp from first message
        first_timestamp = conversation[0].get("timestamp", "")
        if first_timestamp:
            try:
                # Parse ISO timestamp
                dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M:%S")
            except (ValueError, TypeError):
                date_str = datetime.now().strftime("%Y-%m-%d")
                time_str = ""
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = ""

        formatted_session_id = self._format_session_id(jsonl_path)
        filename = f"claude-conversation-{date_str}-{formatted_session_id}.md"
        output_path = self.output_dir / filename

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write("# Claude Conversation Log\n\n")
                f.write(f"Session ID: {jsonl_path.stem}\n")
                f.write(f"Date: {date_str}")
                if time_str:
                    f.write(f" {time_str}")
                f.write("\n\n---\n\n")

                for msg in conversation:
                    role = msg["role"]
                    content = msg["content"]

                    if role == "user":
                        f.write("## 👤 User\n\n")
                        f.write(f"{content}\n\n")
                    elif role == "assistant":
                        f.write("## 🤖 Claude\n\n")
                        f.write(f"{content}\n\n")
                    elif role == "tool_use":
                        f.write("### 🔧 Tool Use\n\n")
                        f.write(f"{content}\n\n")
                    elif role == "tool_result":
                        f.write("### 📤 Tool Result\n\n")
                        f.write(f"{content}\n\n")
                    elif role == "system":
                        f.write("### ℹ️ System\n\n")
                        f.write(f"{content}\n\n")
                    else:
                        f.write(f"## {role}\n\n")
                        f.write(f"{content}\n\n")
                    f.write("---\n\n")
        except OSError as e:
            print(f"❌ Error saving {output_path.name}: {e}")
            return None

        return output_path

    def save_as_json(
        self, conversation: list[dict[str, str]], jsonl_path: Path
    ) -> Path | None:
        """Save conversation as JSON file."""
        if not conversation:
            return None

        # Get timestamp from first message
        first_timestamp = conversation[0].get("timestamp", "")
        if first_timestamp:
            try:
                dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                date_str = datetime.now().strftime("%Y-%m-%d")
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")

        formatted_session_id = self._format_session_id(jsonl_path)
        filename = f"claude-conversation-{date_str}-{formatted_session_id}.json"
        output_path = self.output_dir / filename

        # Create JSON structure
        output = {
            "session_id": jsonl_path.stem,
            "date": date_str,
            "message_count": len(conversation),
            "messages": conversation,
        }

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, indent=2, ensure_ascii=False)
        except OSError as e:
            print(f"❌ Error saving {output_path.name}: {e}")
            return None

        return output_path

    def save_as_html(
        self, conversation: list[dict[str, str]], jsonl_path: Path
    ) -> Path | None:
        """Save conversation as HTML file with syntax highlighting."""
        if not conversation:
            return None

        # Get timestamp from first message
        first_timestamp = conversation[0].get("timestamp", "")
        if first_timestamp:
            try:
                dt = datetime.fromisoformat(first_timestamp.replace("Z", "+00:00"))
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M:%S")
            except (ValueError, TypeError):
                date_str = datetime.now().strftime("%Y-%m-%d")
                time_str = ""
        else:
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = ""

        formatted_session_id = self._format_session_id(jsonl_path)
        filename = f"claude-conversation-{date_str}-{formatted_session_id}.html"
        output_path = self.output_dir / filename

        # HTML template with modern styling
        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Claude Conversation - {formatted_session_id}</title>
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            color: #333;
            max-width: 900px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
        }}
        .header {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            margin-bottom: 20px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        h1 {{
            color: #2c3e50;
            margin: 0 0 10px 0;
        }}
        .metadata {{
            color: #666;
            font-size: 0.9em;
        }}
        .message {{
            background: white;
            padding: 15px 20px;
            margin-bottom: 15px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }}
        .user {{
            border-left: 4px solid #3498db;
        }}
        .assistant {{
            border-left: 4px solid #2ecc71;
        }}
        .tool_use {{
            border-left: 4px solid #f39c12;
            background: #fffbf0;
        }}
        .tool_result {{
            border-left: 4px solid #e74c3c;
            background: #fff5f5;
        }}
        .system {{
            border-left: 4px solid #95a5a6;
            background: #f8f9fa;
        }}
        .role {{
            font-weight: bold;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
        }}
        .content {{
            white-space: pre-wrap;
            word-wrap: break-word;
        }}
        pre {{
            background: #f4f4f4;
            padding: 10px;
            border-radius: 4px;
            overflow-x: auto;
        }}
        code {{
            background: #f4f4f4;
            padding: 2px 4px;
            border-radius: 3px;
            font-family: 'Courier New', monospace;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Claude Conversation Log</h1>
        <div class="metadata">
            <p>Session ID: {jsonl_path.stem}</p>
            <p>Date: {date_str} {time_str}</p>
            <p>Messages: {len(conversation)}</p>
        </div>
    </div>
"""

        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html_content)

                for msg in conversation:
                    role = msg["role"]
                    content = msg["content"]

                    # Escape HTML
                    content = content.replace("&", "&amp;")
                    content = content.replace("<", "&lt;")
                    content = content.replace(">", "&gt;")

                    role_display = {
                        "user": "👤 User",
                        "assistant": "🤖 Claude",
                        "tool_use": "🔧 Tool Use",
                        "tool_result": "📤 Tool Result",
                        "system": "ℹ️ System",
                    }.get(role, role)

                    f.write(f'    <div class="message {role}">\n')
                    f.write(f'        <div class="role">{role_display}</div>\n')
                    f.write(f'        <div class="content">{content}</div>\n')
                    f.write("    </div>\n")

                f.write("\n</body>\n</html>")
        except OSError as e:
            print(f"❌ Error saving {output_path.name}: {e}")
            return None

        return output_path

    def save_conversation(
        self,
        conversation: list[dict[str, str]],
        jsonl_path: Path,
        format: str = "markdown",
    ) -> Path | None:
        """Save conversation in the specified format.

        Args:
            conversation: The conversation data
            jsonl_path: Path to the JSONL session file
            format: Output format ('markdown', 'json', 'html')
        """
        if format == "markdown":
            return self.save_as_markdown(conversation, jsonl_path)
        elif format == "json":
            return self.save_as_json(conversation, jsonl_path)
        elif format == "html":
            return self.save_as_html(conversation, jsonl_path)
        else:
            print(f"❌ Unsupported format: {format}")
            return None

    def get_conversation_preview(self, session_path: Path) -> tuple[str, int]:
        """Get a preview of the conversation's first real user message and message count."""
        try:
            first_user_msg = ""
            msg_count = 0

            with open(session_path, "r", encoding="utf-8") as f:
                for line in f:
                    msg_count += 1
                    if not first_user_msg:
                        try:
                            data = json.loads(line)
                            # Check for user message
                            if data.get("type") == "user" and "message" in data:
                                msg = data["message"]
                                if msg.get("role") == "user":
                                    content = msg.get("content", "")

                                    # Handle list content (common format in Claude JSONL)
                                    if isinstance(content, list):
                                        for item in content:
                                            if (
                                                isinstance(item, dict)
                                                and item.get("type") == "text"
                                            ):
                                                text = item.get("text", "").strip()

                                                # Skip tool results
                                                if text.startswith("tool_use_id"):
                                                    continue

                                                # Skip interruption messages
                                                if "[Request interrupted" in text:
                                                    continue

                                                # Skip Claude's session continuation messages
                                                if (
                                                    "session is being continued"
                                                    in text.lower()
                                                ):
                                                    continue

                                                # Remove XML-like tags (command messages, etc)
                                                import re

                                                text = re.sub(
                                                    r"<[^>]+>", "", text
                                                ).strip()

                                                # Skip command outputs
                                                if "is running" in text and "…" in text:
                                                    continue

                                                # Handle image references - extract text after them
                                                if text.startswith("[Image #"):
                                                    parts = text.split("]", 1)
                                                    if len(parts) > 1:
                                                        text = parts[1].strip()

                                                # If we have real user text, use it
                                                if (
                                                    text and len(text) > 3
                                                ):  # Lower threshold to catch "hello"
                                                    first_user_msg = text[:100].replace(
                                                        "\n", " "
                                                    )
                                                    break

                                    # Handle string content (less common but possible)
                                    elif isinstance(content, str):
                                        import re

                                        content = content.strip()

                                        # Remove XML-like tags
                                        content = re.sub(
                                            r"<[^>]+>", "", content
                                        ).strip()

                                        # Skip command outputs
                                        if "is running" in content and "…" in content:
                                            continue

                                        # Skip Claude's session continuation messages
                                        if (
                                            "session is being continued"
                                            in content.lower()
                                        ):
                                            continue

                                        # Skip tool results and interruptions
                                        if (
                                            not content.startswith("tool_use_id")
                                            and "[Request interrupted" not in content
                                        ) and (
                                            content and len(content) > 3
                                        ):  # Lower threshold to catch short messages
                                            first_user_msg = content[:100].replace(
                                                "\n", " "
                                            )
                        except json.JSONDecodeError:
                            continue

            return first_user_msg or "No preview available", msg_count
        except (OSError, json.JSONDecodeError) as e:
            return f"Error: {str(e)[:30]}", 0

    def list_recent_sessions(
        self, limit: int | None = None, project_path: str | None = None
    ) -> list[Path]:
        """List recent sessions with details."""
        sessions = self.find_sessions(project_path=project_path)

        if not sessions:
            print("❌ No Claude sessions found in ~/.claude/projects/")
            print("💡 Make sure you've used Claude Code and have conversations saved.")
            return []

        print(f"\n📚 Found {len(sessions)} Claude sessions:\n")
        print("=" * 80)

        # Show all sessions if no limit specified
        sessions_to_show = sessions[:limit] if limit else sessions
        for i, session in enumerate(sessions_to_show, 1):
            # Clean up project name (remove hyphens, make readable)
            project = session.parent.name.replace("-", " ").strip()
            if project.startswith("Users"):
                project = (
                    "~/" + "/".join(project.split()[2:])
                    if len(project.split()) > 2
                    else "Home"
                )

            session_id = session.stem
            modified = datetime.fromtimestamp(session.stat().st_mtime)

            # Get file size
            size = session.stat().st_size
            size_kb = size / 1024

            # Get preview and message count
            preview, msg_count = self.get_conversation_preview(session)

            # Print formatted info
            print(f"\n{i}. 📁 {project}")
            print(f"   📄 Session: {session_id[:8]}...")
            print(f"   📅 Modified: {modified.strftime('%Y-%m-%d %H:%M')}")
            print(f"   💬 Messages: {msg_count}")
            print(f"   💾 Size: {size_kb:.1f} KB")
            print(f'   📝 Preview: "{preview}..."')

        print("\n" + "=" * 80)
        return sessions[:limit]

    def extract_multiple(
        self,
        sessions: list[Path],
        indices: list[int],
        format: str = "markdown",
        detailed: bool = False,
    ) -> tuple[int, int]:
        """Extract multiple sessions by index.

        Args:
            sessions: List of session paths
            indices: Indices to extract
            format: Output format ('markdown', 'json', 'html')
            detailed: If True, include tool use and system messages
        """
        success = 0
        total = len(indices)

        for idx in indices:
            if 0 <= idx < len(sessions):
                session_path = sessions[idx]
                conversation = self.extract_conversation(
                    session_path, detailed=detailed
                )
                if conversation:
                    output_path = self.save_conversation(
                        conversation, session_path, format=format
                    )
                    success += 1
                    msg_count = len(conversation)
                    print(
                        f"✅ {success}/{total}: {output_path.name} "
                        f"({msg_count} messages)"
                    )
                else:
                    print(f"⏭️  Skipped session {idx + 1} (no conversation)")
            else:
                print(f"❌ Invalid session number: {idx + 1}")

        return success, total


def main():
    parser = argparse.ArgumentParser(
        description="Extract Claude Code conversations to clean markdown files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --list                           # List all available sessions
  %(prog)s --extract 1                      # Extract the most recent session
  %(prog)s --extract 1,3,5                  # Extract specific sessions
  %(prog)s --recent 5                       # Extract 5 most recent sessions
  %(prog)s --all                            # Extract all sessions
  %(prog)s --output ~/my-logs               # Specify output directory
  %(prog)s --claude-dir /custom/path        # Specify Claude projects directory
  %(prog)s --search "python error"          # Search all conversations
  %(prog)s --search-regex "import.*"        # Search with regex
  %(prog)s --format json --all              # Export all as JSON
  %(prog)s --format html --extract 1        # Export session 1 as HTML
  %(prog)s --detailed --extract 1           # Include tool use & system messages
  %(prog)s --project .                      # List sessions for the cwd project
  %(prog)s --project . --recent 1           # Export last session of cwd project
  %(prog)s --project . --all                # Export all sessions of cwd project
  %(prog)s --project . --search "bug fix"   # Search within cwd project only
  %(prog)s --project /path/to/repo --list   # List sessions for another project

Environment Variables:
  CLAUDE_DIR=/custom/path           # Set Claude projects directory
  PROJECT_DIR=/custom/path          # Alternative env var for Claude projects directory
        """,
    )
    parser.add_argument("--list", action="store_true", help="List recent sessions")
    parser.add_argument(
        "--extract",
        type=str,
        help="Extract specific session(s) by number (comma-separated)",
    )
    parser.add_argument(
        "--all", "--logs", action="store_true", help="Extract all sessions"
    )
    parser.add_argument(
        "--recent", type=int, help="Extract N most recent sessions", default=0
    )
    parser.add_argument(
        "--output", type=str, help="Output directory for markdown files"
    )
    parser.add_argument(
        "--claude-dir",
        type=str,
        help=(
            "Claude's projects directory (defaults to ~/.claude/projects). "
            "Can also be set via CLAUDE_DIR or PROJECT_DIR environment variable."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Limit for --list command (default: show all)",
        default=None,
    )
    parser.add_argument(
        "--project",
        type=str,
        default=None,
        help=(
            "Filter to one Claude Code project. Pass a path "
            "(e.g. --project . or --project /path/to/repo). "
            "Resolved relative to cwd."
        ),
    )
    parser.add_argument(
        "--interactive",
        "-i",
        "--start",
        "-s",
        action="store_true",
        help="Launch interactive UI for easy extraction",
    )
    parser.add_argument(
        "--export",
        type=str,
        help="Export mode: 'logs' for interactive UI",
    )

    # Search arguments
    parser.add_argument(
        "--search", type=str, help="Search conversations for text (smart search)"
    )
    parser.add_argument(
        "--search-regex", type=str, help="Search conversations using regex pattern"
    )
    parser.add_argument(
        "--search-date-from", type=str, help="Filter search from date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--search-date-to", type=str, help="Filter search to date (YYYY-MM-DD)"
    )
    parser.add_argument(
        "--search-speaker",
        choices=["human", "assistant", "both"],
        default="both",
        help="Filter search by speaker",
    )
    parser.add_argument(
        "--case-sensitive", action="store_true", help="Make search case-sensitive"
    )

    # Export format arguments
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "html"],
        default="markdown",
        help="Output format for exported conversations (default: markdown)",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Include tool use, MCP responses, and system messages in export",
    )

    args = parser.parse_args()

    # Initialize extractor with optional output directory and claude_dir
    claude_dir_path = Path(args.claude_dir) if args.claude_dir else None
    extractor = ClaudeConversationExtractor(args.output, claude_dir_path)

    project_filter = None
    if args.project:
        project_filter = encode_project_path(args.project)
        project_dir = extractor.claude_dir / project_filter
        if not project_dir.exists():
            resolved = Path(args.project).expanduser().resolve()
            print(
                f"No Claude Code logs found for {resolved}",
                file=sys.stderr,
            )
            sys.exit(1)

    # Handle interactive mode (after project_filter so --project is respected)
    if args.interactive or (args.export and args.export.lower() == "logs"):
        from interactive_ui import InteractiveUI

        ui = InteractiveUI(project_filter=project_filter, claude_dir=claude_dir_path)
        ui.run()
        return

    # Handle search mode
    if args.search or args.search_regex:
        from datetime import datetime

        from search_conversations import ConversationSearcher

        searcher = ConversationSearcher()
        search_dir = extractor.claude_dir / project_filter if project_filter else None

        # Determine search mode and query
        if args.search_regex:
            query = args.search_regex
            mode = "regex"
        else:
            query = args.search
            mode = "smart"

        # Parse date filters
        date_from = None
        date_to = None
        if args.search_date_from:
            try:
                date_from = datetime.strptime(args.search_date_from, "%Y-%m-%d")
            except ValueError:
                print(f"❌ Invalid date format: {args.search_date_from}")
                return

        if args.search_date_to:
            try:
                date_to = datetime.strptime(args.search_date_to, "%Y-%m-%d")
            except ValueError:
                print(f"❌ Invalid date format: {args.search_date_to}")
                return

        # Speaker filter
        speaker_filter = None if args.search_speaker == "both" else args.search_speaker

        # Perform search
        print(f"🔍 Searching for: {query}")
        results = searcher.search(
            query=query,
            search_dir=search_dir,
            mode=mode,
            date_from=date_from,
            date_to=date_to,
            speaker_filter=speaker_filter,
            case_sensitive=args.case_sensitive,
            max_results=30,
        )

        if not results:
            print("❌ No matches found.")
            return

        print(f"\n✅ Found {len(results)} matches across conversations:")

        # Group and display results
        results_by_file = {}
        for result in results:
            if result.file_path not in results_by_file:
                results_by_file[result.file_path] = []
            results_by_file[result.file_path].append(result)

        # Store file paths for potential viewing
        file_paths_list = []
        for file_path, file_results in results_by_file.items():
            file_paths_list.append(file_path)
            print(
                f"\n{len(file_paths_list)}. 📄 {file_path.parent.name} ({len(file_results)} matches)"
            )
            # Show first match preview
            first = file_results[0]
            print(f"   {first.speaker}: {first.matched_content[:100]}...")

        # Offer to view conversations
        if file_paths_list:
            print("\n" + "=" * 60)
            try:
                view_choice = input(
                    f"\nView a conversation? Enter number (1-{len(file_paths_list)}) or press Enter to skip: "
                ).strip()

                if view_choice.isdigit():
                    view_num = int(view_choice)
                    if 1 <= view_num <= len(file_paths_list):
                        selected_path = file_paths_list[view_num - 1]
                        extractor.display_conversation(
                            selected_path, detailed=args.detailed
                        )

                        # Offer to extract after viewing
                        extract_choice = (
                            input("\n📤 Extract this conversation? (y/N): ")
                            .strip()
                            .lower()
                        )
                        if extract_choice == "y":
                            conversation = extractor.extract_conversation(
                                selected_path, detailed=args.detailed
                            )
                            if conversation:
                                if args.format == "json":
                                    output = extractor.save_as_json(
                                        conversation, selected_path
                                    )
                                elif args.format == "html":
                                    output = extractor.save_as_html(
                                        conversation, selected_path
                                    )
                                else:
                                    output = extractor.save_as_markdown(
                                        conversation, selected_path
                                    )
                                print(f"✅ Saved: {output.name}")
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Cancelled")

        return

    # Default action is to list sessions
    if args.list or (
        not args.extract
        and not args.all
        and not args.recent
        and not args.search
        and not args.search_regex
    ):
        sessions = extractor.list_recent_sessions(
            args.limit, project_path=project_filter
        )

        if sessions and not args.list:
            print("\nTo extract conversations:")
            print("  claude-extract --extract <number>      # Extract specific session")
            print("  claude-extract --recent 5              # Extract 5 most recent")
            print("  claude-extract --all                   # Extract all sessions")

    elif args.extract:
        sessions = extractor.find_sessions(project_path=project_filter)

        # Parse comma-separated indices
        indices = []
        for num in args.extract.split(","):
            try:
                idx = int(num.strip()) - 1  # Convert to 0-based index
                indices.append(idx)
            except ValueError:
                print(f"❌ Invalid session number: {num}")
                continue

        if indices:
            print(
                f"\n📤 Extracting {len(indices)} session(s) as {args.format.upper()}..."
            )
            if args.detailed:
                print("📋 Including detailed tool use and system messages")
            success, total = extractor.extract_multiple(
                sessions, indices, format=args.format, detailed=args.detailed
            )
            print(f"\n✅ Successfully extracted {success}/{total} sessions")

    elif args.recent:
        sessions = extractor.find_sessions(project_path=project_filter)
        limit = min(args.recent, len(sessions))
        print(
            f"\n📤 Extracting {limit} most recent sessions as {args.format.upper()}..."
        )
        if args.detailed:
            print("📋 Including detailed tool use and system messages")

        indices = list(range(limit))
        success, total = extractor.extract_multiple(
            sessions, indices, format=args.format, detailed=args.detailed
        )
        print(f"\n✅ Successfully extracted {success}/{total} sessions")

    elif args.all:
        sessions = extractor.find_sessions(project_path=project_filter)
        print(
            f"\n📤 Extracting all {len(sessions)} sessions as {args.format.upper()}..."
        )
        if args.detailed:
            print("📋 Including detailed tool use and system messages")

        indices = list(range(len(sessions)))
        success, total = extractor.extract_multiple(
            sessions, indices, format=args.format, detailed=args.detailed
        )
        print(f"\n✅ Successfully extracted {success}/{total} sessions")


def launch_interactive():
    """Launch the interactive UI directly, or handle search if specified."""
    # If no arguments provided, launch interactive UI
    if len(sys.argv) == 1:
        try:
            from .interactive_ui import InteractiveUI as _InteractiveUI
        except ImportError:
            from interactive_ui import InteractiveUI as _InteractiveUI
        _InteractiveUI().run()
    # Check if 'search' was passed as an argument
    elif len(sys.argv) > 1 and sys.argv[1] == "search":
        # Launch real-time search with viewing capability
        try:
            from .realtime_search import RealTimeSearch, create_smart_searcher
            from .search_conversations import ConversationSearcher
        except ImportError:
            from realtime_search import RealTimeSearch, create_smart_searcher
            from search_conversations import ConversationSearcher

        # Initialize components
        extractor = ClaudeConversationExtractor()
        searcher = ConversationSearcher()
        smart_searcher = create_smart_searcher(searcher)

        # Run search
        rts = RealTimeSearch(smart_searcher, extractor)
        selected_file = rts.run()

        if selected_file:
            # View the selected conversation
            extractor.display_conversation(selected_file)

            # Offer to extract
            try:
                extract_choice = (
                    input("\n📤 Extract this conversation? (y/N): ").strip().lower()
                )
                if extract_choice == "y":
                    conversation = extractor.extract_conversation(selected_file)
                    if conversation:
                        output = extractor.save_as_markdown(conversation, selected_file)
                        print(f"✅ Saved: {output.name}")
            except (EOFError, KeyboardInterrupt):
                print("\n👋 Cancelled")
    else:
        # If other arguments are provided, run the normal CLI
        main()


if __name__ == "__main__":
    main()
