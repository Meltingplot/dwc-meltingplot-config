"""Tests for the dsf-python workarounds applied at daemon import time.

These paper over bugs in the library itself and are the difference between a
working `get_object_model()` and a daemon that cannot read the object model at
all, so they get their own coverage: that each patch does what it claims, that
the values it adds really are the ones DSF reports, and that a patch which no
longer fits the installed library is skipped rather than fatal.

The library is not installed in CI, so the modules the patches reach into are
faked at the exact paths the daemon imports them from. The fakes mirror
dsf-python's own shape: an enum plus a property whose setter coerces through
that enum, which is where the crash comes from.
"""

import importlib.util
import os
import sys
import types
from enum import Enum
from unittest.mock import MagicMock

import pytest


DAEMON_PATH = os.path.join(
    os.path.dirname(__file__), "..", "dsf", "meltingplot-config-daemon.py"
)


def _import_daemon():
    """Import a fresh copy of the daemon, applying the workarounds."""
    spec = importlib.util.spec_from_file_location("daemon_workaround_mod", DAEMON_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _register(monkeypatch, name, module):
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def dsf_stubs(monkeypatch):
    """Fake just enough of dsf-python for the daemon to import and patch.

    Returns the namespace of fakes so a test can inspect what the patches did.
    """
    # --- modules the daemon imports unconditionally ---
    dsf_mod = _register(monkeypatch, "dsf", types.ModuleType("dsf"))
    connections = _register(monkeypatch, "dsf.connections", types.ModuleType("dsf.connections"))
    commands = _register(monkeypatch, "dsf.commands", types.ModuleType("dsf.commands"))
    commands_code = _register(monkeypatch, "dsf.commands.code", types.ModuleType("dsf.commands.code"))
    http = _register(monkeypatch, "dsf.http", types.ModuleType("dsf.http"))
    object_model = _register(monkeypatch, "dsf.object_model", types.ModuleType("dsf.object_model"))

    connections.CommandConnection = MagicMock
    connections.InterceptConnection = MagicMock
    commands_code.CodeResult = MagicMock
    http.HttpEndpointConnection = MagicMock
    http.HttpResponseType = types.SimpleNamespace(
        StatusCode="StatusCode", PlainText="PlainText", JSON="JSON", File="File", URI="URI"
    )
    object_model.HttpEndpointType = types.SimpleNamespace(GET="GET", POST="POST")

    # --- PluginManifest, with the 3.6 bug: _data is a plain dict ---
    md_mod = _register(
        monkeypatch,
        "dsf.object_model.model_dictionary",
        types.ModuleType("dsf.object_model.model_dictionary"),
    )

    class FakeModelDictionary(dict):
        def __init__(self, null_deletes_keys):
            super().__init__()
            self.null_deletes_keys = null_deletes_keys

    md_mod.ModelDictionary = FakeModelDictionary

    plugins_pkg = _register(
        monkeypatch, "dsf.object_model.plugins", types.ModuleType("dsf.object_model.plugins")
    )
    pm_mod = _register(
        monkeypatch,
        "dsf.object_model.plugins.plugin_manifest",
        types.ModuleType("dsf.object_model.plugins.plugin_manifest"),
    )

    class FakePluginManifest:
        def __init__(self):
            self._data = {}
            self.init_ran = True

    pm_mod.PluginManifest = FakePluginManifest
    plugins_pkg.plugin_manifest = pm_mod

    # --- Board, with the 3.6/3.7 bug: BoardState has no "timedOut" ---
    boards_pkg = _register(
        monkeypatch, "dsf.object_model.boards", types.ModuleType("dsf.object_model.boards")
    )
    boards_mod = _register(
        monkeypatch,
        "dsf.object_model.boards.boards",
        types.ModuleType("dsf.object_model.boards.boards"),
    )

    class FakeBoardState(str, Enum):
        unknown = "unknown"
        flashing = "flashing"
        flashFailed = "flashFailed"
        resetting = "resetting"
        running = "running"

    class FakeBoard:
        @property
        def state(self):
            return getattr(self, "_state", None)

        @state.setter
        def state(self, value):
            # Mirrors dsf-python: coerce through the enum, raising on anything
            # it does not know about
            self._state = FakeBoardState(value) if value is not None else None

    boards_mod.BoardState = FakeBoardState
    boards_mod.Board = FakeBoard
    boards_pkg.boards = boards_mod

    # --- NetworkInterface, with the 3.6 bug: no "ethernet" ---
    network_pkg = _register(
        monkeypatch, "dsf.object_model.network", types.ModuleType("dsf.object_model.network")
    )
    nit_mod = _register(
        monkeypatch,
        "dsf.object_model.network.network_interface_type",
        types.ModuleType("dsf.object_model.network.network_interface_type"),
    )
    ni_mod = _register(
        monkeypatch,
        "dsf.object_model.network.network_interface",
        types.ModuleType("dsf.object_model.network.network_interface"),
    )

    class FakeNetworkInterfaceType(str, Enum):
        lan = "lan"
        wifi = "wifi"

    class FakeNetworkInterface:
        @property
        def type(self):
            return getattr(self, "_type", None)

        @type.setter
        def type(self, value):
            self._type = FakeNetworkInterfaceType(value)

    nit_mod.NetworkInterfaceType = FakeNetworkInterfaceType
    ni_mod.NetworkInterfaceType = FakeNetworkInterfaceType
    ni_mod.NetworkInterface = FakeNetworkInterface
    network_pkg.network_interface = ni_mod
    network_pkg.network_interface_type = nit_mod

    dsf_mod.object_model = object_model
    object_model.plugins = plugins_pkg
    object_model.boards = boards_pkg
    object_model.network = network_pkg

    return types.SimpleNamespace(
        ModelDictionary=FakeModelDictionary,
        PluginManifest=FakePluginManifest,
        Board=FakeBoard,
        boards_module=boards_mod,
        NetworkInterface=FakeNetworkInterface,
        ni_module=ni_mod,
        nit_module=nit_mod,
    )


class TestPluginManifestDataWorkaround:
    """PluginManifest._data must end up as a ModelDictionary, not a dict."""

    def test_replaces_the_plain_dict(self, dsf_stubs):
        _import_daemon()
        manifest = dsf_stubs.PluginManifest()
        assert isinstance(manifest._data, dsf_stubs.ModelDictionary)

    def test_keeps_running_the_original_constructor(self, dsf_stubs):
        _import_daemon()
        manifest = dsf_stubs.PluginManifest()
        assert manifest.init_ran is True

    def test_model_dictionary_does_not_delete_on_null(self, dsf_stubs):
        _import_daemon()
        manifest = dsf_stubs.PluginManifest()
        assert manifest._data.null_deletes_keys is False


class TestBoardStateWorkaround:
    """BoardState must accept every state DSF reports, and never raise."""

    def test_accepts_timed_out(self, dsf_stubs):
        _import_daemon()
        board = dsf_stubs.Board()
        board.state = "timedOut"
        assert board.state == "timedOut"

    @pytest.mark.parametrize(
        "value", ["unknown", "flashing", "flashFailed", "resetting", "running"]
    )
    def test_still_accepts_the_original_states(self, dsf_stubs, value):
        _import_daemon()
        board = dsf_stubs.Board()
        board.state = value
        assert board.state == value

    def test_falls_back_to_unknown_for_a_future_state(self, dsf_stubs):
        _import_daemon()
        board = dsf_stubs.Board()
        board.state = "somethingNewInDsf4"
        assert board.state == "unknown"

    def test_accepts_none(self, dsf_stubs):
        _import_daemon()
        board = dsf_stubs.Board()
        board.state = None
        assert board.state is None

    def test_rejects_a_non_string(self, dsf_stubs):
        """An unknown *value* degrades; a wrong *type* still raises.

        DSF sends JSON, so a state is always a string or null. A number would
        mean the library changed how it calls the setter, which is worth
        surfacing rather than papering over.
        """
        _import_daemon()
        board = dsf_stubs.Board()
        with pytest.raises(TypeError):
            board.state = 42

    def test_replaces_the_enum_in_the_module(self, dsf_stubs):
        _import_daemon()
        assert dsf_stubs.boards_module.BoardState("timedOut") == "timedOut"


class TestNetworkInterfaceTypeWorkaround:
    """The interface type must cover both libraries' vocabularies."""

    @pytest.mark.parametrize("value", ["lan", "wifi", "ethernet"])
    def test_accepts_every_known_type(self, dsf_stubs, value):
        """dsf-python 3.6 lacks "ethernet"; 3.7 added it but dropped "lan"."""
        _import_daemon()
        interface = dsf_stubs.NetworkInterface()
        interface.type = value
        assert interface.type == value

    def test_falls_back_to_unknown_for_a_future_type(self, dsf_stubs):
        _import_daemon()
        interface = dsf_stubs.NetworkInterface()
        interface.type = "somethingNewInDsf4"
        assert interface.type == "unknown"

    @pytest.mark.parametrize("value", [None, ""])
    def test_treats_a_missing_type_as_wifi(self, dsf_stubs, value):
        _import_daemon()
        interface = dsf_stubs.NetworkInterface()
        interface.type = value
        assert interface.type == "wifi"

    def test_rejects_a_non_string(self, dsf_stubs):
        """Same rule as Board.state: unknown value degrades, wrong type raises."""
        _import_daemon()
        interface = dsf_stubs.NetworkInterface()
        with pytest.raises(TypeError):
            interface.type = 42

    def test_replaces_the_enum_in_both_modules(self, dsf_stubs):
        _import_daemon()
        assert dsf_stubs.nit_module.NetworkInterfaceType("ethernet") == "ethernet"
        assert dsf_stubs.ni_module.NetworkInterfaceType("ethernet") == "ethernet"


class TestWorkaroundApplication:
    """A workaround that no longer fits the library must not be fatal."""

    def test_a_failing_workaround_is_reported_and_skipped(self, dsf_stubs, capsys):
        daemon = _import_daemon()

        def boom():
            raise AttributeError("property 'state' has no setter")

        daemon._apply_dsf_workaround("BoardState", boom)

        captured = capsys.readouterr()
        assert "BoardState" in captured.err
        assert "AttributeError" in captured.err

    def test_a_missing_library_is_silent(self, dsf_stubs, capsys):
        daemon = _import_daemon()

        def not_installed():
            raise ImportError("No module named 'dsf'")

        daemon._apply_dsf_workaround("PluginManifest.data", not_installed)

        assert capsys.readouterr().err == ""

    def test_a_successful_workaround_says_nothing(self, dsf_stubs, capsys):
        daemon = _import_daemon()
        daemon._apply_dsf_workaround("noop", lambda: None)
        assert capsys.readouterr().err == ""
