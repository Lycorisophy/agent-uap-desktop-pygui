"""win11_* 项目路径沙箱解析与基础写读。"""

from __future__ import annotations

import tempfile
from pathlib import Path

from uap.react.win11_project_fs_skills import (
    create_win11_project_fs_skill_bundle,
    resolve_project_path,
)


def test_resolve_rejects_parent_escape():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "a.txt").write_text("x", encoding="utf-8")
        ok, err, p = resolve_project_path(root, "..\\..\\windows\\system.ini")
        assert ok is False
        assert p is None


def test_resolve_accepts_relative_under_root():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "sub").mkdir()
        (root / "sub" / "f.txt").write_text("hi", encoding="utf-8")
        ok, err, p = resolve_project_path(root, "sub/f.txt")
        assert ok and p is not None
        assert p.read_text(encoding="utf-8") == "hi"


def test_win11_write_and_read_roundtrip():
    with tempfile.TemporaryDirectory() as td:
        bundle = create_win11_project_fs_skill_bundle(td)
        w = bundle["win11_write_file"]
        r = bundle["win11_read_file"]
        out_w = w.execute(path="t.txt", content="abc", create_parent_dirs=True)
        assert "error" not in out_w or out_w.get("error") is None
        out_r = r.execute(path="t.txt")
        assert out_r.get("content") == "abc"


def test_win11_modify_replace_all():
    with tempfile.TemporaryDirectory() as td:
        bundle = create_win11_project_fs_skill_bundle(td)
        bundle["win11_write_file"].execute(path="m.txt", content="foo foo", create_parent_dirs=True)
        m = bundle["win11_modify_file"]
        out = m.execute(path="m.txt", find="foo", replace="bar", replace_all=True)
        assert out.get("replacements") == 2
        txt = Path(td, "m.txt").read_text(encoding="utf-8")
        assert txt == "bar bar"


def test_win11_move_within_root():
    with tempfile.TemporaryDirectory() as td:
        bundle = create_win11_project_fs_skill_bundle(td)
        bundle["win11_write_file"].execute(path="a.txt", content="1", create_parent_dirs=True)
        mv = bundle["win11_move_file"]
        out = mv.execute(source="a.txt", destination="b.txt", overwrite=True)
        assert "error" not in out or not out.get("error")
        assert not Path(td, "a.txt").exists()
        assert Path(td, "b.txt").read_text(encoding="utf-8") == "1"
