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
