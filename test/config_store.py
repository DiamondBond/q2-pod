"""Run actual config_store.c against real host files with injected I/O failures.

No device IO. Process-interruption tests do not simulate flash power failure.
"""
import ctypes as C
import os
from pathlib import Path
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='q2-config-test-') as temp:
    d = Path(temp)
    so = d / 'config.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                    '-DQ2_CONFIG_HOST', '-I', str(ROOT / 'test'),
                    str(ROOT / 'patch/config_store.c'), str(ROOT / 'test/config_store_host.c'),
                    '-o', str(so)], check=True)
    lib = C.CDLL(str(so))
    lib.cfg_test_setup.argtypes = [C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_int]
    save = lib.ringnav_config_store
    save.argtypes = [C.c_char_p] * 4
    target = d / 'config.ini'
    old = b'; keep me\n[SYSSET]\nLANGUAGE=2\nBLUETOOTH=0\n[IPOD]\nLIGHT=1\n'
    new = old.replace(b'BLUETOOTH=0', b'BLUETOOTH=1')
    def setup(data=old, fail=0, cut=0, short=0, intr=0):
        target.write_bytes(data)
        lib.cfg_test_setup(os.fsencode(d), fail, cut, short, intr)
    def put(section=b'SYSSET', key=b'BLUETOOTH', value=b'1', path=b'/mnt/data/config.ini'):
        return save(path, section, key, value)

    setup()
    assert put() == 0 and target.read_bytes() == new
    steps = lib.cfg_test_steps()
    for i in range(1, steps + 1):
        setup(fail=i)
        put()
        assert target.read_bytes() in (old, new), ('failed operation', i)
        # A subsequent save must work: errors cannot leave a held lock.
        lib.cfg_test_setup(os.fsencode(d), 0, 0, 0, 0)
        assert put(value=b'2') == 0
    for i in range(1, steps + 1):
        setup(cut=i)
        pid = os.fork()
        if not pid:
            put()
            os._exit(0)
        _, status = os.waitpid(pid, 0)
        assert os.waitstatus_to_exitcode(status) == 77
        assert target.read_bytes() in (old, new), ('interrupted operation', i)
        lib.cfg_test_setup(os.fsencode(d), 0, 0, 0, 0)
        assert put(value=b'2') == 0  # stale temp is never restored over live config
    for short, intr in [(1, 0), (0, 1), (0, 2)]:
        setup(short=short, intr=intr)
        assert put() == 0 and target.read_bytes() == new
    setup(short=2)
    assert put() == -1 and target.read_bytes() == old
    for bad in [b'x' * 65537, old + b'\0', b'[broken\nLANGUAGE=2\n']:
        setup(bad)
        assert put() == -1 and target.read_bytes() == bad
    setup(b';' + b'x' * 65534 + b'\n')
    assert put() == -1 and len(target.read_bytes()) == 65536  # output cap, not just input
    for section, key, value in [(b'bad\nsection', b'X', b'1'),
                                 (b'SYSSET', b'X=Y', b'1'),
                                 (b'SYSSET', b'X', b'bad\nvalue'),
                                 (b'SYSSET', b'X', b'x' * 1025)]:
        setup()
        assert put(section, key, value) == -1 and target.read_bytes() == old
    for initial, expected in [
        (b'[SYSSET]\nLANGUAGE=2\n[IPOD]\nLIGHT=1\n',
         b'[SYSSET]\nLANGUAGE=2\nBLUETOOTH=1\n[IPOD]\nLIGHT=1\n'),
        (b'[IPOD]\nLIGHT=1', b'[IPOD]\nLIGHT=1\n[SYSSET]\nBLUETOOTH=1\n'),
        (b' [SYSSET] \r\n BLUETOOTH =0\r\n', b' [SYSSET] \r\nBLUETOOTH=1\n'),
        (b'[SYSSET]\nBLUETOOTH=0\nBLUETOOTH=2\n',
         b'[SYSSET]\nBLUETOOTH=1\nBLUETOOTH=1\n'),
        (b'', b'[SYSSET]\nBLUETOOTH=1\n'),
    ]:
        setup(initial)
        assert put() == 0 and target.read_bytes() == expected
    setup()
    target.unlink()
    assert put() == 0 and target.read_bytes() == b'[SYSSET]\nBLUETOOTH=1\n'
    setup()
    assert put(path=b'/mnt/data/other.ini') == 42 and lib.cfg_test_passed() == 1
    assert target.read_bytes() == old
    # Competing threads update distinct keys without losing each other's writes.
    # The production lock also serializes the shim's I/O counters.
    setup()
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda i: put(key=('KEY%d' % i).encode()), range(4)))
    assert results == [0] * 4
    for i in range(4):
        assert ('KEY%d=1\n' % i).encode() in target.read_bytes()
    assert b'LANGUAGE=2\n' in target.read_bytes()
    print(f'PASS: {steps} I/O failure points, {steps} process interruption points; '
          'short/zero writes, EINTR, malformed/oversize input, INI updates, '
          'missing file, passthrough, concurrent updates')
