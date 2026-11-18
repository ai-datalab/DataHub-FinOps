import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_demo import back_link_html, copy_text  # noqa: E402


def test_copied_sources_have_the_same_bytes_from_any_checkout(tmp_path):
    for name, newline in (("crlf.js", b"\r\n"), ("lf.js", b"\n")):
        (tmp_path / name).write_bytes(newline.join([b"const a = 1;", b"// \xc3\xa9", b""]))
        copy_text(tmp_path / name, tmp_path / f"out-{name}")
    assert (tmp_path / "out-crlf.js").read_bytes() == (tmp_path / "out-lf.js").read_bytes() == "const a = 1;\n// é\n".encode()


def test_back_link_accepts_site_paths_and_rejects_markup():
    assert back_link_html(None) == ""
    assert back_link_html("/#solutions") == ' <a href="/#solutions">All dashboard demos</a>'
    for bad in ("javascript:alert(1)", '/x" onclick="y', "/<script>", "relative/path", "//evil.example"):
        with pytest.raises(SystemExit):
            back_link_html(bad)
