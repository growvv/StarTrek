from specfcg.executor.device import FakeDevice, Uiautomator2Device


def test_fake_device_returns_states_in_order():
    d = FakeDevice(["s1", "s2"], [True, False])
    assert d.dump_ui() == "s1"
    assert d.execute("click", "Save") is True
    assert d.dump_ui() == "s2"
    assert d.execute("click", "Missing") is False


def test_fake_device_records_calls():
    d = FakeDevice(["s"], [True])
    d.execute("click", "Save", "extra")
    assert d.calls == [("click", "Save", "extra")]


def test_uiautomator2_device_is_lazy():
    device = Uiautomator2Device()
    assert device.serial is None


class _FakeSelector:
    def __init__(self, selectors: list[dict]) -> None:
        self.selectors = selectors
        self.clicked = False

    def click(self) -> None:
        self.clicked = True


class _FakeU2:
    def __init__(self, hierarchy: str = "<hierarchy />") -> None:
        self.selectors: list[dict] = []
        self.pressed: list[str] = []
        self.hierarchy = hierarchy

    def __call__(self, **kwargs) -> _FakeSelector:
        self.selectors.append(kwargs)
        return _FakeSelector(self.selectors)

    def press(self, key: str) -> None:
        self.pressed.append(key)

    def dump_hierarchy(self) -> str:
        return self.hierarchy


def test_uiautomator2_device_set_app_filters_dump_to_package():
    device = Uiautomator2Device()
    inner = _FakeU2(
        "<hierarchy>"
        "<node package='other.app' text='Launcher' />"
        "<node package='target.app' text='Notes' />"
        "</hierarchy>"
    )
    device._device = inner

    device.set_app("target.app")

    assert "Notes" in device.dump_ui()
    assert "Launcher" not in device.dump_ui()


def test_uiautomator2_device_settles_after_actions(monkeypatch):
    device = Uiautomator2Device()
    device._device = _FakeU2()
    sleeps: list[float] = []
    monkeypatch.setattr(
        "specfcg.executor.device.time.sleep", sleeps.append
    )

    assert device.execute("click", "text=Save") is True

    assert sleeps == [1.0]


def test_uiautomator2_device_presses_named_key():
    device = Uiautomator2Device()
    inner = _FakeU2()
    device._device = inner

    assert device.execute("press", "", "enter") is True
    assert inner.pressed == ["enter"]


def test_uiautomator2_device_combines_target_selectors():
    device = Uiautomator2Device()
    inner = _FakeU2()
    device._device = inner

    assert (
        device.execute(
            "click",
            "resourceId=app:id/note_title|text=Groceries",
        )
        is True
    )

    assert inner.selectors == [
        {"resourceId": "app:id/note_title", "text": "Groceries"}
    ]


def test_uiautomator2_device_supports_content_description_targets():
    device = Uiautomator2Device()
    inner = _FakeU2()
    device._device = inner

    assert device.execute("click", "desc=New note") is True
    assert device.execute("click", "text=Save") is True
    assert device.execute("click", "resourceId=app:id/fab") is True

    assert inner.selectors == [
        {"description": "New note"},
        {"text": "Save"},
        {"resourceId": "app:id/fab"},
    ]
