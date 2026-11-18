"""Fail closed on unknown firmware; keep every non-initializer byte recoverable."""
import hashlib
import pathlib
import struct
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]/'tools'))
import bluetoothd


def fixture(monkeypatch):
    raw = bytearray(bluetoothd.STOCK_SIZE)
    at = bluetoothd.CONTEXT_OFFSET
    raw[at:at+len(bluetoothd.CONTEXT)] = bluetoothd.CONTEXT
    monkeypatch.setattr(bluetoothd, 'STOCK_SHA256', hashlib.sha256(raw).hexdigest())
    return bytes(raw)


def test_pinned_hash_and_size_refuse_unknown():
    with pytest.raises(ValueError, match='pinned stock'):
        bluetoothd.patch_daemon(b'')
    with pytest.raises(ValueError, match='pinned stock'):
        bluetoothd.patch_daemon(bytes(bluetoothd.STOCK_SIZE))


def test_only_initializer_changes_and_baseline_recovers(monkeypatch):
    raw = fixture(monkeypatch)
    patched = bluetoothd.patch_daemon(raw)
    assert len(patched) == len(raw)
    assert [i for i, (a, b) in enumerate(zip(raw, patched)) if a != b] == [bluetoothd.OFFSET]
    assert struct.unpack_from('<I', patched, bluetoothd.OFFSET)[0] == bluetoothd.NEW
    restored = bytearray(patched)
    struct.pack_into('<I', restored, bluetoothd.OFFSET, bluetoothd.OLD)
    assert bytes(restored) == raw
    with pytest.raises(ValueError, match='pinned stock'):
        bluetoothd.patch_daemon(patched)


def test_instruction_guard_even_with_test_hash_override(monkeypatch):
    raw = bytearray(fixture(monkeypatch))
    struct.pack_into('<I', raw, bluetoothd.OFFSET, 0)
    monkeypatch.setattr(bluetoothd, 'STOCK_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='instruction'):
        bluetoothd.patch_daemon(bytes(raw))


def test_context_guard_even_with_test_hash_override(monkeypatch):
    raw = bytearray(fixture(monkeypatch))
    raw[bluetoothd.CONTEXT_OFFSET] ^= 1
    monkeypatch.setattr(bluetoothd, 'STOCK_SHA256', hashlib.sha256(raw).hexdigest())
    with pytest.raises(ValueError, match='context'):
        bluetoothd.patch_daemon(bytes(raw))
