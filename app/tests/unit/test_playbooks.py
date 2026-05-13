"""Playbooks tool reads from a temp directory."""

from pathlib import Path
from unittest.mock import patch

from src.tools import playbooks as pb


def test_list_and_get_playbook(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "playbooks"
    root.mkdir()
    (root / "demo.md").write_text("# Demo\nHello", encoding="utf-8")

    with patch.object(pb, "_playbooks_root", return_value=root):
        listing = pb.list_playbooks()
        assert "demo" in listing
        body = pb.get_playbook("demo")
        assert "Hello" in body
