from specfcg.executor.device import Uiautomator2Device
from specfcg.executor.ui import compact_ui


SAMPLE_XML = """<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>
<hierarchy rotation="0">
  <node index="0" class="android.widget.FrameLayout" package="com.android.launcher" text="" resource-id="launcher:home" content-desc="" clickable="true" bounds="[0,2000][100][2100]" />
  <node index="0" class="android.widget.FrameLayout" package="com.example.notes" text="" resource-id="com.example.notes:id/root" content-desc="" clickable="false" bounds="[0,0][1000,2000]">
    <node index="0" class="android.widget.TextView" package="com.example.notes" text="Notes" resource-id="" content-desc="" clickable="false" bounds="[0,0][200,100]" />
    <node index="1" class="android.widget.ImageButton" package="com.example.notes" text="" resource-id="com.example.notes:id/fab" content-desc="New note" clickable="true" bounds="[900,1800][990,1900]" />
    <node index="2" class="android.widget.EditText" package="com.example.notes" text="Trip" resource-id="com.example.notes:id/title" content-desc="" clickable="true" bounds="[0,100][1000,200]" />
  </node>
</hierarchy>"""


def test_compact_ui_keeps_only_target_package_and_meaningful_nodes():
    compact = compact_ui(SAMPLE_XML, "com.example.notes")

    assert "Notes" in compact
    assert "com.example.notes:id/fab" in compact
    assert "New note" in compact
    assert "Trip" in compact
    assert "launcher:home" not in compact
    assert "com.example.notes:id/root" not in compact


def test_compact_ui_falls_back_to_all_packages_when_target_absent():
    compact = compact_ui(SAMPLE_XML, "com.android.permissioncontroller")

    assert "launcher:home" in compact
    assert "com.example.notes:id/fab" in compact


def test_compact_ui_truncates_long_hierarchies():
    nodes = "".join(
        f'<node class="android.widget.TextView" package="app" '
        f'text="item {index}" resource-id="" content-desc="" '
        f'clickable="false" bounds="[0,{index}][10,{index + 1}]" />'
        for index in range(20)
    )
    compact = compact_ui(f"<hierarchy>{nodes}</hierarchy>", "app", max_nodes=5)

    assert "item 4" in compact
    assert "item 5" not in compact
    assert "truncated" in compact


def test_compact_ui_includes_overlay_package_nodes():
    xml = (
        "<hierarchy>"
        "<node class='android.widget.TextView' package='com.example.notes'"
        " text='Groceries' clickable='false' bounds='[0,0][10,10]' />"
        "<node class='android.widget.TextView'"
        " package='com.android.intentresolver' text='Share'"
        " clickable='true' bounds='[0,10][10,20]' />"
        "</hierarchy>"
    )

    compact = compact_ui(
        xml,
        "com.example.notes",
        extra_packages=("com.android.intentresolver",),
    )

    assert "Groceries" in compact
    assert "Share" in compact


def test_compact_ui_returns_short_text_on_malformed_xml():
    assert compact_ui("<hierarchy><node", "app") == "<hierarchy><node"


class _FakeInnerDevice:
    def __init__(self, xml: str) -> None:
        self.xml = xml
        self.started: list[str] = []

    def app_start(self, package: str) -> None:
        self.started.append(package)

    def dump_hierarchy(self) -> str:
        return self.xml


def test_uiautomator2_device_filters_dump_to_started_package():
    device = Uiautomator2Device()
    inner = _FakeInnerDevice(SAMPLE_XML)
    device._device = inner

    device.start_app("com.example.notes")
    compact = device.dump_ui()

    assert inner.started == ["com.example.notes"]
    assert "Trip" in compact
    assert "launcher:home" not in compact


def test_uiautomator2_device_dump_includes_share_chooser():
    device = Uiautomator2Device()
    inner = _FakeInnerDevice(
        "<hierarchy>"
        "<node class='android.widget.TextView' package='com.example.notes'"
        " text='Groceries' clickable='false' bounds='[0,0][10,10]' />"
        "<node class='android.widget.TextView'"
        " package='com.android.intentresolver' text='Share'"
        " clickable='true' bounds='[0,10][10,20]' />"
        "</hierarchy>"
    )
    device._device = inner

    device.start_app("com.example.notes")

    assert "Groceries" in device.dump_ui()
    assert "Share" in device.dump_ui()
