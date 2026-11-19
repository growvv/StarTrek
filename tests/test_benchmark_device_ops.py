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


def test_contains_selectors_resolve():
    """A list row's description carries the file path, so exact match fails.

    `desc=File meeting-notes.md` never matches a row described as
    `File meeting-notes.md /storage/...`; the contains form is what the trace
    specs need to address it.
    """
    from specfcg.executor.device import Uiautomator2Device

    seen: list[dict] = []

    class Element:
        exists = True

        def click(self) -> None:
            pass

    class U2:
        def __call__(self, **kwargs):
            seen.append(kwargs)
            return Element()

    device = Uiautomator2Device(settle_s=0)
    device._device = U2()

    device._locator("descContains=File meeting-notes.md")
    device._locator("textContains=meeting")

    assert seen[0] == {"descriptionContains": "File meeting-notes.md"}
    assert seen[1] == {"textContains": "meeting"}


def test_a_long_click_can_be_addressed_by_coordinates():
    """A file row's title opens the editor on a long press; its container
    selects.  Coordinates address the row itself."""
    from specfcg.executor.device import Uiautomator2Device

    calls: list[tuple[int, int]] = []

    class U2:
        def long_click(self, x, y):
            calls.append((x, y))

        def __getattr__(self, name):
            return lambda *a, **k: None

    device = Uiautomator2Device(settle_s=0)
    device._device = U2()

    device.execute("long_click", "xy=540,300")

    assert calls == [(540, 300)]
