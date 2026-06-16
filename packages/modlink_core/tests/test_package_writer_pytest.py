from __future__ import annotations

import pytest

from modlink_core.replay.package_writer import ExportPackageWriter


def test_success_creates_target(tmp_path):
    target = tmp_path / "export_bundle"
    with ExportPackageWriter(target) as pkg:
        (pkg.root / "data.txt").write_text("hello")

    assert target.exists()
    assert (target / "data.txt").read_text() == "hello"


def test_success_no_tmp_left(tmp_path):
    target = tmp_path / "export_bundle"
    with ExportPackageWriter(target) as pkg:
        tmp_dir = pkg.root
        (pkg.root / "data.txt").write_text("hello")

    assert not tmp_dir.exists()


def test_failure_cleans_up_tmp(tmp_path):
    target = tmp_path / "export_bundle"
    tmp_dir = None

    with pytest.raises(ValueError, match="intentional"):
        with ExportPackageWriter(target) as pkg:
            tmp_dir = pkg.root
            (pkg.root / "data.txt").write_text("partial")
            raise ValueError("intentional failure")

    assert not target.exists()
    assert tmp_dir is not None and not tmp_dir.exists()


def test_collision_appends_suffix(tmp_path):
    target = tmp_path / "export_bundle"
    target.mkdir()  # pre-existing directory causes collision

    with ExportPackageWriter(target) as pkg:
        (pkg.root / "data.txt").write_text("new")

    expected = tmp_path / "export_bundle_2"
    assert expected.exists()
    assert (expected / "data.txt").read_text() == "new"
    # original untouched
    assert target.exists()
    assert not (target / "data.txt").exists()


def test_root_raises_outside_context(tmp_path):
    writer = ExportPackageWriter(tmp_path / "export_bundle")
    with pytest.raises(RuntimeError, match="context manager"):
        _ = writer.root


def test_nested_dirs_created(tmp_path):
    target = tmp_path / "export_bundle"
    with ExportPackageWriter(target) as pkg:
        nested = pkg.root / "streams" / "eeg"
        nested.mkdir(parents=True)
        (nested / "frame_0.npy").write_bytes(b"\x00\x01\x02")

    assert (target / "streams" / "eeg" / "frame_0.npy").read_bytes() == b"\x00\x01\x02"
