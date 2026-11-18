"""Pinned Q2 BlueZ incoming AVDTP grace, before its existing discovery fallback."""
import hashlib
import struct

PATH = 'usr/bin/bluetoothd'
STOCK_SHA256 = '6e6d45d66f958a028a523786ae661110b1853bf49b8a50946dd70a0518b4f357'
STOCK_SIZE = 1313952
OFFSET = 0x23ef0
OLD = 0x2403001e  # addiu $3,$zero,30
NEW = 0x24030001  # addiu $3,$zero,1
CONTEXT_OFFSET = 0x23ee0
CONTEXT = bytes.fromhex(
    '010003241000bc8f252800005c0403ae1e00032425300002180002ae'
    '252020020c82998fd4393927b2fe1104580403ae')
POLICY = 'incoming-avdtp-initial-grace-1s'


def patch_daemon(raw: bytes) -> bytes:
    """Only accepted-channel initialization changes; later reset/clear sites stay stock.

    Session+0x458 is used by the seconds timer. This also affects incoming
    preconfiguration idle/failed setup until SetConfiguration/Close/Abort resets it.
    A null-channel outgoing constructor skips the changed branch entirely.
    """
    if len(raw) != STOCK_SIZE or hashlib.sha256(raw).hexdigest() != STOCK_SHA256:
        raise ValueError('Unsupported bluetoothd: pinned stock size/SHA-256 required')
    if struct.unpack_from('<I', raw, OFFSET)[0] != OLD:
        raise ValueError('Unexpected bluetoothd incoming-grace instruction')
    if raw[CONTEXT_OFFSET:CONTEXT_OFFSET + len(CONTEXT)] != CONTEXT:
        raise ValueError('Unexpected bluetoothd incoming-constructor context')
    result = bytearray(raw)
    struct.pack_into('<I', result, OFFSET, NEW)
    return bytes(result)
