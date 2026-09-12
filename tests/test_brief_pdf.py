from unittest.mock import MagicMock, patch

import pytest

from app.brief_pdf import find_chrome_binary, render_pdf


def test_no_binary_found_returns_false_without_raising(monkeypatch, tmp_path):
    monkeypatch.delenv("CHROME_BINARY", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.exists", lambda self: False)

    result = render_pdf("file:///tmp/does-not-matter.html", tmp_path / "out.pdf")

    assert result is False


def test_env_var_binary_used_when_set(monkeypatch, tmp_path):
    monkeypatch.setenv("CHROME_BINARY", "my-chrome")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/local/bin/my-chrome" if name == "my-chrome" else None)

    assert find_chrome_binary() == "/usr/local/bin/my-chrome"


def test_env_var_absolute_path_checked_with_exists(monkeypatch, tmp_path):
    fake_binary = tmp_path / "chrome-bin"
    fake_binary.write_text("")
    monkeypatch.setenv("CHROME_BINARY", str(fake_binary))

    assert find_chrome_binary() == str(fake_binary)


@patch("subprocess.run")
def test_mocked_successful_run_returns_true(mock_run, monkeypatch, tmp_path):
    monkeypatch.setenv("CHROME_BINARY", "fake-chrome")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fake-chrome")

    out_path = tmp_path / "out.pdf"

    def _fake_run(cmd, timeout, capture_output, check):
        out_path.write_bytes(b"%PDF-1.4 fake pdf bytes")
        return MagicMock(returncode=0, stderr=b"")

    mock_run.side_effect = _fake_run

    result = render_pdf("file:///tmp/brief.html", out_path)

    assert result is True
    assert out_path.exists()
    assert out_path.stat().st_size > 0


@patch("subprocess.run")
def test_nonzero_exit_returns_false(mock_run, monkeypatch, tmp_path):
    monkeypatch.setenv("CHROME_BINARY", "fake-chrome")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fake-chrome")
    mock_run.return_value = MagicMock(returncode=1, stderr=b"boom")

    result = render_pdf("file:///tmp/brief.html", tmp_path / "out.pdf")

    assert result is False


@patch("subprocess.run")
def test_zero_exit_but_empty_output_returns_false(mock_run, monkeypatch, tmp_path):
    monkeypatch.setenv("CHROME_BINARY", "fake-chrome")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fake-chrome")
    out_path = tmp_path / "out.pdf"
    out_path.write_bytes(b"")  # exists but empty
    mock_run.return_value = MagicMock(returncode=0, stderr=b"")

    result = render_pdf("file:///tmp/brief.html", out_path)

    assert result is False


@patch("subprocess.run")
def test_subprocess_exception_returns_false_not_raise(mock_run, monkeypatch, tmp_path):
    monkeypatch.setenv("CHROME_BINARY", "fake-chrome")
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/fake-chrome")
    mock_run.side_effect = OSError("boom")

    result = render_pdf("file:///tmp/brief.html", tmp_path / "out.pdf")

    assert result is False


_REAL_CHROME = find_chrome_binary()


@pytest.mark.skipif(_REAL_CHROME is None, reason="No real Chrome/Chromium binary found on this machine")
def test_real_smoke_render_produces_nonempty_pdf(tmp_path):
    html_path = tmp_path / "fixture.html"
    html_path.write_text("<html><body><h1>Brief PDF smoke test</h1></body></html>")
    out_path = tmp_path / "smoke.pdf"

    result = render_pdf(str(html_path), out_path, timeout=30)

    assert result is True
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert out_path.read_bytes().startswith(b"%PDF")
