#!/usr/bin/env python3
"""Run the shipped helper with stand-in Q2 services: python3 test/bluetooth.py."""
import os
from pathlib import Path
import subprocess
import tempfile
import time

root = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory() as directory:
    tmp = Path(directory)
    config, log = tmp/'config.ini', tmp/'log'
    script = (root/'patch/q2bluetooth.sh').read_text().replace('/mnt/data/config.ini', str(config))
    (tmp/'helper').write_text(script)
    mock = tmp/'mock'
    mock.write_text('''#!/usr/bin/env python3
import os, sys, time
from pathlib import Path
name=Path(sys.argv[0]).name
with open(os.environ['LOG'], 'a') as f: f.write(name+' '+' '.join(sys.argv[1:])+'\\n')
mode=os.environ.get('MODE', '')
if name == 'pidof': sys.exit(0 if mode in ('existing','connected','other') else 1)
if name == 'hciconfig': sys.exit(1 if mode == 'no-radio' else 0)
if name == 'hcitool':
    if mode in ('connected','other'): print(' ACL AA:BB:CC:DD:EE:FF handle 1 state 1')
if name == 'dbus-send':
    if sys.argv[-1] == 'string:Paired':
        print('variant boolean '+('false' if mode == 'unpaired' else 'true'))
    elif sys.argv[-1] == 'string:Connected': print('variant boolean '+('true' if mode == 'success' else 'false'))
    elif mode == 'blocked':
        Path(os.environ['BLOCKED']).write_text(str(os.getpid()))
        time.sleep(60)
''')
    mock.chmod(0o755)
    for name in ('pidof','cmd_gpio','hciconfig','rtk_hciattach','bluetoothd','bluealsa2','hcitool','dbus-send','sleep'):
        (tmp/name).symlink_to(mock)
    env = dict(os.environ, PATH=f'{tmp}:'+os.environ['PATH'], LOG=str(log), BLOCKED=str(tmp/'blocked'))
    def run(text, mode=''):
        config.write_text(text)
        log.write_text('')
        subprocess.run(['sh', str(tmp/'helper')], env=dict(env, MODE=mode), check=True, timeout=10)
        return log.read_text().splitlines()
    good = '[SYSSET]\nBLUETOOTH=1\nBTLINKMAC=12:34:56:78:9a:bc\n'
    for text in ('', good.replace('=1','=0'), good.replace('=1','=2'),
                 good.replace('12:34:56:78:9a:bc','$(touch /tmp/unsafe)'),
                 good.replace('12:34:56:78:9a:bc','00:00:00:00:00:00'),
                 good.replace('[SYSSET]','[PLAYSET]'), good+'BLUETOOTH=1\n'):
        assert run(text) == [], text
    lines = run(' [SYSSET] \r\n BLUETOOTH = 1 \r\n BTLINKMAC = 12:34:56:78:9a:bc \r\n')
    assert sum('Device1.Connect' in x for x in lines) == 4
    assert lines.count('sleep 20') == 3
    assert 'cmd_gpio set_func PD20 output1' in lines
    assert sum(x.startswith('rtk_hciattach ') for x in lines) == 1
    assert any('/org/bluez/hci0/dev_12_34_56_78_9A_BC' in x for x in lines)
    for mode in ('existing','connected','other'):
        lines = run(good, mode)
        assert not any(x.startswith(('cmd_gpio ', 'rtk_hciattach ', 'bluetoothd ', 'bluealsa2 ')) for x in lines)
        assert sum('Device1.Connect' in x for x in lines) == (4 if mode == 'existing' else 0)
    lines = run(good, 'success')
    assert sum('Device1.Connect' in x for x in lines) == 1
    assert 'sleep 20' not in lines
    assert all('--reply-timeout=' in x for x in lines if x.startswith('dbus-send '))
    lines = run(good, 'unpaired')
    assert not any('Device1.Connect' in x for x in lines)
    assert sum('string:Paired' in x for x in lines) == 10
    lines = run(good, 'no-radio')
    assert sum(x.startswith('hciconfig ') for x in lines) == 10
    assert not any(x.startswith('dbus-send ') for x in lines)
    config.write_text(good)
    process = subprocess.Popen(['sh', str(tmp/'helper')], env=dict(env, MODE='blocked'))
    for _ in range(200):
        if (tmp/'blocked').exists(): break
        time.sleep(.01)
    assert (tmp/'blocked').exists()
    child = int((tmp/'blocked').read_text())
    process.terminate()
    process.wait(timeout=2)
    try: os.kill(child, 0)
    except ProcessLookupError: pass
    else: raise AssertionError('Connect child survived helper cleanup')
print('Bluetooth settings, service reuse, pairing, bounded retries and cleanup passed.')
