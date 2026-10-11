import hashlib
import os
import struct
from pathlib import Path

import pytest

from scenelight import file_verification as module


def test_verified_checksum_reuse_detects_same_size_timestamp_preserving_edits(tmp_path):
    path = tmp_path / "map.bin"
    path.write_bytes(b"original")
    digest, stamp, reused = module.verified_digest(path)
    assert digest == hashlib.sha256(b"original").hexdigest() and not reused
    if stamp is None:
        pytest.skip("Filesystem does not expose a reliable change identity")
    assert module.verified_digest(path, digest, stamp) == (digest, stamp, True)
    old = path.stat()
    path.write_bytes(b"modified")
    os.utime(path, ns=(old.st_atime_ns, old.st_mtime_ns))
    new_digest, _, reused = module.verified_digest(path, digest, stamp)
    assert new_digest == hashlib.sha256(b"modified").hexdigest() and not reused


def test_directory_transfer_reuses_identity_but_file_replacement_does_not(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    path = source / "map.bin"
    path.write_bytes(b"content")
    digest, stamp, _ = module.verified_digest(path)
    target = tmp_path / "destination"
    os.replace(source, target)
    moved = target / path.name
    actual, _, reused = module.verified_digest(moved, digest, stamp)
    assert actual == digest
    if stamp:
        assert reused
    original = moved.stat()
    replacement = target / "replacement.bin"
    replacement.write_bytes(b"changed")
    os.utime(replacement, ns=(original.st_atime_ns, original.st_mtime_ns))
    os.replace(replacement, moved)
    actual, _, reused = module.verified_digest(moved, digest, stamp)
    assert actual != digest and not reused


def test_unknown_change_identity_always_reads_bytes(tmp_path, monkeypatch):
    path = tmp_path / "map"
    path.write_bytes(b"abc")
    digest, stamp, _ = module.verified_digest(path)
    real = module._identity
    monkeypatch.setattr(module, "_identity", lambda stream: (real(stream)[0], None))
    assert module.verified_digest(path, digest, stamp) == (digest, None, False)


def test_stamp_is_bound_to_expected_digest(tmp_path):
    path = tmp_path / "map"
    path.write_bytes(b"abc")
    digest, stamp, _ = module.verified_digest(path)
    actual, _, reused = module.verified_digest(path, "0" * 64, stamp)
    assert actual == digest and not reused


def test_bounded_workers_propagate_errors_and_preserve_order():
    assert list(module.bounded_file_work(lambda number: number * 2, range(30), workers=3)) == list(
        range(0, 60, 2)
    )

    def check(number):
        if number == 7:
            raise OSError("cannot read file")
        return number

    with pytest.raises(OSError, match="cannot read file"):
        list(module.bounded_file_work(check, range(20), workers=2))


def test_open_error_keeps_filename(tmp_path):
    path = tmp_path / "missing.bin"
    with pytest.raises(OSError) as captured:
        module.verified_digest(path)
    assert Path(captured.value.filename) == path


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_active_writer_prevents_cached_checksum_reuse(tmp_path):
    path = tmp_path / "map.bin"
    path.write_bytes(b"original")
    digest, stamp, _ = module.verified_digest(path)
    with path.open("r+b") as writer:
        with pytest.raises(PermissionError):
            module.verified_digest(path, digest, stamp)
        writer.write(b"modified")
        writer.flush()
        with pytest.raises(PermissionError):
            module.verified_digest(path, digest, stamp)
    assert module.verified_digest(path, digest, stamp)[0] != digest


def test_invalid_cached_stamp_falls_back_to_reading_bytes(tmp_path):
    path = tmp_path / "map.bin"
    path.write_bytes(b"original")
    digest, _, _ = module.verified_digest(path)
    actual, _, reused = module.verified_digest(path, digest, "invalid stamp")
    assert actual == digest and not reused


@pytest.mark.parametrize(
    "major,length,usn,expected",
    [
        (2, 64, 53, 53),
        (3, 80, 54, 54),
        (4, 80, 54, None),
        (2, 64, 0, None),
        (2, 64, -1, None),
        (2, 4096, 22, None),
    ],
)
def test_journal_record_versions_and_bounds(major, length, usn, expected):
    data = bytearray(80)
    struct.pack_into("<IHH", data, 0, length, major, 0)
    struct.pack_into("<q", data, 40 if major == 3 else 24, usn)
    assert module._usn_from_record(bytes(data)) == expected
    assert module._usn_from_record(bytes(data[:7])) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows file journal")
def test_rapid_changes_with_identical_timestamps_are_not_reused(tmp_path, monkeypatch):
    real = module._identity

    def identical_times(stream):
        identity, reusable = real(stream)
        identity = (*identity[:3], 1, 1, *identity[5:])
        return identity, identity if reusable is not None else None

    monkeypatch.setattr(module, "_identity", identical_times)
    path = tmp_path / "rapid.bin"
    path.write_bytes(b"original")
    digest, stamp, _ = module.verified_digest(path)
    for value in (b"modified", b"changed!", b"restored"):
        path.write_bytes(value)
        new, next_stamp, reused = module.verified_digest(path, digest, stamp)
        assert new == hashlib.sha256(value).hexdigest() and not reused
        digest, stamp = new, next_stamp


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing and journal coalescing")
def test_open_reader_forces_full_reads_without_reusable_stamps(tmp_path):
    path = tmp_path / "shared.bin"
    path.write_bytes(b"original")
    digest, stamp, _ = module.verified_digest(path)
    with path.open("rb"):
        assert module.verified_digest(path, digest, stamp) == (digest, None, False)
        for value in (b"modified", b"changed!"):
            path.write_bytes(value)
            assert module.verified_digest(path, digest, stamp) == (
                hashlib.sha256(value).hexdigest(),
                None,
                False,
            )


@pytest.mark.skipif(os.name != "nt", reason="Windows journal availability")
def test_unavailable_journal_never_uses_a_timestamp_only_stamp(tmp_path, monkeypatch):
    path = tmp_path / "no-journal.bin"
    path.write_bytes(b"original")
    digest, stamp, _ = module.verified_digest(path)
    monkeypatch.setattr(module, "_windows_usn", lambda handle: None)
    assert module.verified_digest(path, digest, stamp) == (digest, None, False)
    path.write_bytes(b"modified")
    new, stamp, reused = module.verified_digest(path, digest, stamp)
    assert new == hashlib.sha256(b"modified").hexdigest() and stamp is None and not reused
