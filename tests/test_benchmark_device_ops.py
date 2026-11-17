from __future__ import annotations

from specfcg.benchmark.device_ops import AdbOps


class RecordingRunner:
    def __init__(self, outputs=None) -> None:
        self.commands: list[list[str]] = []
        self.outputs = list(outputs or [])
        self.i = 0

    def __call__(self, argv: list[str], stdin: bytes | None = None):
        self.commands.append(argv)
        out = b""
        if self.i < len(self.outputs):
            out = self.outputs[self.i]
            self.i += 1
        return 0, out


def test_shell_uses_the_serial_and_returns_text():
    runner = RecordingRunner([b"hello\n"])
    ops = AdbOps("SER", run=runner)

    assert ops.shell("echo hello") == "hello\n"
    assert runner.commands[0] == [
        "adb", "-s", "SER", "shell", "echo", "hello",
    ]


def test_read_file_returns_none_when_absent():
    runner = RecordingRunner([b"ls: No such file or directory\n"])
    ops = AdbOps("SER", run=runner)
    assert ops.read_file("/sdcard/missing.md") is None


def test_read_file_returns_content():
    runner = RecordingRunner([b"alpha\n"])
    ops = AdbOps("SER", run=runner)
    assert ops.read_file("/sdcard/a.md") == "alpha\n"


def test_is_dir_checks_stat():
    runner = RecordingRunner([b"directory\n"])
    ops = AdbOps("SER", run=runner)
    assert ops.is_dir("/sdcard/d") is True

    runner = RecordingRunner([b"regular file\n"])
    ops = AdbOps("SER", run=runner)
    assert ops.is_dir("/sdcard/a.md") is False


def test_write_file_pipes_content_through_stdin():
    runner = RecordingRunner()
    ops = AdbOps("SER", run=runner)
    ops.write_file("/sdcard/a.md", "hello world")

    argv = runner.commands[0]
    assert argv[:5] == ["adb", "-s", "SER", "shell", "cat"]
    assert argv[-1] == "/sdcard/a.md"
    assert runner.commands[0] == argv


def test_remove_quotes_paths_with_spaces():
    runner = RecordingRunner()
    ops = AdbOps("SER", run=runner)
    ops.remove("/sdcard/My Files/a.md")
    assert "'/sdcard/My Files/a.md'" in runner.commands[0][-1]


def test_dump_ui_uses_the_injected_dump():
    ops = AdbOps("SER", run=RecordingRunner(), ui_dump=lambda: "text='Notes'")
    assert ops.dump_ui() == "text='Notes'"


def test_dump_ui_falls_back_to_a_live_dump(monkeypatch):
    import specfcg.benchmark.device_ops as module

    monkeypatch.setattr(module, "_live_ui_dump", lambda serial: f"live:{serial}")
    ops = AdbOps("SER", run=RecordingRunner())
    assert ops.dump_ui() == "live:SER"


def test_focused_package_parses_dumpsys_window():
    runner = RecordingRunner(
        [
            b"  mCurrentFocus=Window{1 u0 com.amaze.filemanager/"
            b"com.amaze.filemanager.ui.activities.MainActivity}\n"
        ]
    )
    ops = AdbOps("SER", run=runner)
    assert ops.focused_package() == "com.amaze.filemanager"


def test_clear_app_uses_pm_clear():
    runner = RecordingRunner()
    ops = AdbOps("SER", run=runner)
    ops.clear_app("org.tasks")
    assert runner.commands[0] == [
        "adb", "-s", "SER", "shell", "pm", "clear", "org.tasks",
    ]


def test_launch_uses_monkey():
    runner = RecordingRunner()
    ops = AdbOps("SER", run=runner)
    ops.launch("org.tasks")
    assert runner.commands[0][:5] == ["adb", "-s", "SER", "shell", "monkey"]
    assert "-p" in runner.commands[0]
