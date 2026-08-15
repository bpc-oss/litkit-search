from pathlib import Path

from litkit.browser_runtime import (
    browser_launch_args,
    default_profile_dir,
    resolve_browser_executable,
)


def test_resolve_browser_executable_prefers_explicit_env(monkeypatch, tmp_path: Path) -> None:
    fake = tmp_path / "chrome"
    fake.write_text("", encoding="utf-8")
    monkeypatch.setenv("LITKIT_BROWSER_EXECUTABLE", str(fake))

    assert resolve_browser_executable() == str(fake)


def test_default_profile_dir_uses_named_subdirectory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("litkit.browser_runtime.Path.home", lambda: tmp_path)

    assert default_profile_dir("institutional").as_posix().endswith(".litkit/browser/institutional")


def test_browser_launch_args_adds_no_sandbox_for_root_linux(monkeypatch) -> None:
    monkeypatch.setattr("litkit.browser_runtime.sys.platform", "linux")
    monkeypatch.setattr("litkit.browser_runtime.os.geteuid", lambda: 0, raising=False)

    assert "--no-sandbox" in browser_launch_args()
