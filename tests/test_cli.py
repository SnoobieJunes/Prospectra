# 2026-07-13 (P0): CLI contract — stubs must exit 2 with an honest "not implemented" message
# (never pretend to work), and generate-example must produce the seeded dataset.

import pytest

from prospectra import __version__
from prospectra.cli import main


def test_scan_is_an_honest_stub(capsys):
    assert main(["scan", "data.csv", "--target", "sales"]) == 2
    assert "P3" in capsys.readouterr().err


def test_run_flow_is_an_honest_stub(capsys):
    assert main(["run-flow", "proj.prospectra", "myflow"]) == 2
    assert "P2" in capsys.readouterr().err


def test_generate_example(tmp_path, capsys):
    out = tmp_path / "ice.csv"
    assert main(["generate-example", str(out), "--days", "10"]) == 0
    assert out.exists()
    assert str(out) in capsys.readouterr().out


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    assert __version__ in capsys.readouterr().out
