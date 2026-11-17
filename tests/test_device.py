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
        self.long_clicked = False

    def click(self) -> None:
        self.clicked = True

    def long_click(self) -> None:
        self.long_clicked = True


class _FakeU2:
    def __init__(self, hierarchy: str = "<hierarchy />") -> None:
        self.selectors: list[dict] = []
        self.pressed: list[str] = []
        self.shelled: list[str] = []
        self.clicks: list[tuple[int, int]] = []
        self.hierarchy = hierarchy

    def __call__(self, **kwargs) -> _FakeSelector:
        self.selectors.append(kwargs)
        return _FakeSelector(self.selectors)

    def press(self, key: str) -> None:
        self.pressed.append(key)

    def shell(self, command: str) -> None:
        self.shelled.append(command)

    def click(self, x: int, y: int) -> None:
        self.clicks.append((x, y))

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


def test_uiautomator2_device_presses_a_numeric_keycode_through_shell():
    """uiautomator2's pressKey only knows key names, not KEYCODE numbers.

    A numeric key needs ``input keyevent``: ESCAPE (111) dismisses the soft
    keyboard without navigating back, which is the only way to reveal a
    dialog button that sits under the keyboard.
    """
    device = Uiautomator2Device()
    inner = _FakeU2()
    device._device = inner

    assert device.execute("press", "", "111") is True
    assert inner.shelled == ["input keyevent 111"]
    assert inner.pressed == []


def test_uiautomator2_device_scopes_a_combined_selector_by_its_id():
    """``id|text=`` means "the node with this id that shows this label".

    Android puts a control's id on its container and the label the user
    reads on a child TextView, so requiring both attributes on one node
    matches nothing (``LinearLayout id=...:menu_new_file`` holding
    ``text='文件'``).  The id scopes the query and the label may be on the
    node itself or inside it.
    """
    device = Uiautomator2Device()
    inner = _FakeXPathU2()
    device._device = inner

    assert (
        device.execute(
            "click",
            "resourceId=app:id/note_title|text=Groceries",
        )
        is True
    )

    assert inner.queries == [
        '(//*[@resource-id="app:id/note_title"]'
        '[@text="Groceries" or .//*[@text="Groceries"]])[1]'
    ]
    assert inner.selectors == []


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


def test_uiautomator2_device_long_clicks():
    device = Uiautomator2Device()
    inner = _FakeU2()
    device._device = inner

    assert device.execute("long_click", "text=bench_probe.md") is True
    assert inner.selectors == [{"text": "bench_probe.md"}]


def test_uiautomator2_device_supports_point_clicks():
    device = Uiautomator2Device()
    inner = _FakeU2()
    device._device = inner

    assert device.execute("click", "xy=850,1196") is True
    assert inner.clicks == [(850, 1196)]


class _FakeAppU2(_FakeU2):
    def __init__(self) -> None:
        super().__init__()
        self.started: list[str] = []
        self.stopped: list[str] = []

    def app_start(self, package: str) -> None:
        self.started.append(package)

    def app_stop(self, package: str) -> None:
        self.stopped.append(package)


def test_start_app_restarts_from_the_launcher_activity():
    device = Uiautomator2Device()
    inner = _FakeAppU2()
    device._device = inner

    device.start_app("de.rampro.activitydiary")

    assert inner.stopped == ["de.rampro.activitydiary"]
    assert inner.started == ["de.rampro.activitydiary"]


def test_start_app_can_resume_an_existing_stack():
    device = Uiautomator2Device()
    inner = _FakeAppU2()
    device._device = inner

    device.start_app("de.rampro.activitydiary", restart=False)

    assert inner.stopped == []
    assert inner.started == ["de.rampro.activitydiary"]


def test_uiautomator2_device_retries_a_label_as_a_content_description():
    """A visible label is a text on some controls and a description on others.

    The card only knows the label, not which attribute carries it, so a
    ``text=`` click that finds nothing must be retried as ``desc=`` before
    the action is reported as failed.
    """

    class _RaisingSelector(_FakeSelector):
        def click(self) -> None:
            raise RuntimeError("UiObjectNotFoundError")

    class _LabelU2(_FakeU2):
        def __call__(self, **kwargs):
            self.selectors.append(kwargs)
            if "text" in kwargs:
                return _RaisingSelector(self.selectors)
            return _FakeSelector(self.selectors)

    device = Uiautomator2Device()
    inner = _LabelU2()
    device._device = inner

    assert device.execute("click", "text=更多选项") is True
    assert inner.selectors == [
        {"text": "更多选项"},
        {"description": "更多选项"},
    ]


def test_uiautomator2_device_does_not_retry_an_explicit_description():
    class _RaisingSelector(_FakeSelector):
        def click(self) -> None:
            raise RuntimeError("UiObjectNotFoundError")

    class _FailU2(_FakeU2):
        def __call__(self, **kwargs):
            self.selectors.append(kwargs)
            return _RaisingSelector(self.selectors)

    device = Uiautomator2Device()
    inner = _FailU2()
    device._device = inner

    assert device.execute("click", "desc=更多选项") is False
    assert inner.selectors == [{"description": "更多选项"}]


class _FakeXPathSelector:
    def __init__(self, inner: "_FakeXPathU2", query: str) -> None:
        self.inner = inner
        self.query = query
        self.clicked = False

    def click(self) -> None:
        self.clicked = True
        self.inner.clicked_queries.append(self.query)

    def long_click(self) -> None:
        self.clicked = True
        self.inner.clicked_queries.append(self.query)


class _FakeXPathU2(_FakeU2):
    """Records XPath queries instead of resolving them."""

    def __init__(self) -> None:
        super().__init__()
        self.queries: list[str] = []
        self.clicked_queries: list[str] = []

    def xpath(self, query: str) -> _FakeXPathSelector:
        self.queries.append(query)
        return _FakeXPathSelector(self, query)


def test_uiautomator2_device_scopes_a_target_to_the_row_that_shows_a_label():
    """``within=<anchor>|target`` addresses the one control inside the row
    whose visible text is the anchor.

    A list row repeats the same button id on every row.  uiautomator2's
    selector kwargs match the first such node, so the row has to be part of
    the query itself: find the node showing the label, walk to the nearest
    ancestor that contains the control, then select the control under it.
    """
    device = Uiautomator2Device()
    inner = _FakeXPathU2()
    device._device = inner

    assert (
        device.execute(
            "click", "within=text=bench_old.txt|resourceId=app:id/properties"
        )
        is True
    )

    assert inner.queries == [
        '//*[@text="bench_old.txt"]'
        '/ancestor::*[.//*[@resource-id="app:id/properties"]][1]'
        '//*[@resource-id="app:id/properties"]'
    ]
    assert inner.clicked_queries == inner.queries
    assert inner.selectors == []


def test_uiautomator2_device_row_scope_accepts_a_description_anchor():
    device = Uiautomator2Device()
    inner = _FakeXPathU2()
    device._device = inner

    assert (
        device.execute(
            "long_click", "within=desc=Properties|text=bench_old.txt"
        )
        is True
    )

    assert inner.queries == [
        '//*[@content-desc="Properties"]'
        '/ancestor::*[.//*[@text="bench_old.txt"]][1]'
        '//*[@text="bench_old.txt"]'
    ]


class _FakeScrollU2(_FakeXPathU2):
    """A selector that only appears after the list has been scrolled."""

    def __init__(self, hidden_until: int = 1) -> None:
        super().__init__()
        self.scrolls = 0
        self.hidden_until = hidden_until

    def swipe(self, *args) -> None:
        self.scrolls += 1

    def dump_hierarchy(self) -> str:
        # A real list re-renders on every swipe; a fake that returns one
        # fixed dump would read as "the list cannot move".
        return f"<hierarchy scrolled='{self.scrolls}' />"

    def window_size(self) -> tuple[int, int]:
        return (1080, 2400)

    def __call__(self, **kwargs) -> "_FakeScrollSelector":
        self.selectors.append(kwargs)
        return _FakeScrollSelector(self)


class _FakeScrollSelector:
    def __init__(self, inner: _FakeScrollU2) -> None:
        self.inner = inner

    @property
    def exists(self) -> bool:
        return self.inner.scrolls >= self.inner.hidden_until

    def click(self) -> None:
        if not self.exists:
            raise RuntimeError("element not found")

    def long_click(self) -> None:
        self.click()


def test_uiautomator2_device_scrolls_to_a_row_below_the_fold(monkeypatch):
    """A row that exists but sits past the last visible row is still a
    target: the user scrolls to it.  Without this, any plan that names a
    file below the fold fails on its first action even though the file is
    there and every later step would have worked."""
    monkeypatch.setattr("specfcg.executor.device.time.sleep", lambda _s: None)
    device = Uiautomator2Device()
    inner = _FakeScrollU2(hidden_until=2)
    device._device = inner

    assert device.execute("long_click", "text=bench_old.txt") is True
    assert inner.scrolls == 2
