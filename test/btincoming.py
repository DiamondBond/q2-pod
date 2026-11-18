#!/usr/bin/env python3
"""Execute pinned daemon MIPS routines; mock libc/GLib/device/IO boundaries only.

No radio, real daemon, sockets or firmware writes. Pass original daemon and,
optionally, the build's patched daemon to verify actual packaged input too.
"""
import hashlib
import json
import pathlib
import struct
import sys
import subprocess

from unicorn import Uc, UC_ARCH_MIPS, UC_MODE_MIPS32, UC_MODE_LITTLE_ENDIAN, UC_HOOK_CODE
from unicorn.mips_const import UC_MIPS_REG_0, UC_MIPS_REG_PC

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from bluetoothd import STOCK_SHA256, OLD, NEW, OFFSET, patch_daemon

REG = lambda number: UC_MIPS_REG_0 + number
GP = 0x13e420
STACK, STOP, DEVICE, CHANNEL, SEPS, SINK, SETUP = 0x7e0000, 0x7f0000, 0x600000, 0x600100, 0x600200, 0x600300, 0x600400


class Machine:
    def __init__(self, raw):
        self.u = Uc(UC_ARCH_MIPS, UC_MODE_MIPS32 | UC_MODE_LITTLE_ENDIAN)
        self.u.mem_map(0, 0x200000)
        self.u.mem_map(0x400000, 0x400000)
        phoff = struct.unpack_from('<I', raw, 28)[0]
        entsize, count = struct.unpack_from('<HH', raw, 42)
        for i in range(count):
            typ, off, address, _, size, _, _, _ = struct.unpack_from('<8I', raw, phoff+i*entsize)
            if typ == 1:
                self.u.mem_write(address, raw[off:off+size])
        self.heap = 0x410000
        self.session = 0
        self.service = True
        self.role = 'sink'
        self.timer_id = 0
        self.timers = {}
        self.calls = []
        self.freed = []
        self.hooks = {}
        # Dynamic imports, mapped from the actual ELF MIPS GOT metadata.
        shoff = struct.unpack_from('<I', raw, 32)[0]
        entsize, count, names = struct.unpack_from('<HHH', raw, 46)
        sections = [struct.unpack_from('<10I', raw, shoff+i*entsize) for i in range(count)]
        s = sections[names]; strings = raw[s[4]:s[4]+s[5]]
        sections = {strings[s[0]:].split(b'\0', 1)[0].decode(): s for s in sections}
        s = sections['.dynamic']; tags = dict(struct.unpack_from('<II', raw, s[4]+i) for i in range(0, s[5], 8))
        got, sym, st = (sections[n] for n in ('.got', '.dynsym', '.dynstr'))
        strtab = raw[st[4]:st[4]+st[5]]
        self.imports = {}
        for i in range(tags[0x7000000a], got[5]//4):
            no = struct.unpack_from('<I', raw, sym[4]+16*(tags[0x70000013]+i-tags[0x7000000a]))[0]
            name = strtab[no:].split(b'\0', 1)[0].decode()
            self.imports[self.word(got[3]+4*i)] = name
        for off in range(0, sym[5], 16):
            no, address = struct.unpack_from('<II', raw, sym[4]+off)
            name = strtab[no:].split(b'\0', 1)[0].decode()
            if name == 'btd_device_unref': self.hooks[address] = lambda: 0
        self.hooks.update({
            self.got(-0x7c78): lambda: DEVICE,  # btd_device_ref
            self.got(-0x7c74): lambda: 0,  # no cached SDP record needed for constructor
            self.got(-0x7c68): lambda: 0,  # btd_device_add_uuid
            self.got(-0x7ec4): lambda: DEVICE,  # btd_device_get_address
            self.got(-0x7db4): self.bt_get,
            self.got(-0x7e64): self.get_service,
            self.got(-0x7e30): lambda: SINK,
            self.got(-0x7d94): lambda: 0,  # queue_isempty: local endpoint exists
            0x1ebd0: self.set_state,
            0x2021c: lambda: 0,  # no pending requests during channel initialization
            0x50a58: lambda: 0,  # debug output
            0x16144: lambda: SETUP,  # A2DP setup allocation boundary
            0x200dc: self.send_request,
            0x206a8: self.connection_lost,
        })
        self.u.hook_add(UC_HOOK_CODE, self.hook)

    def r(self, n): return self.u.reg_read(REG(n))
    def word(self, address): return struct.unpack('<I', self.u.mem_read(address, 4))[0]
    def put(self, address, value): self.u.mem_write(address, struct.pack('<I', value & 0xffffffff))
    def got(self, relative): return self.word(GP+relative)
    def allocate(self):
        size = self.r(4); address = self.heap
        self.heap += (size+15)&~15
        assert self.heap < 0x500000
        self.u.mem_write(address, bytes(size))
        return address

    def set_state(self):
        self.put(self.r(4)+0x10, self.r(5)); return 0

    def get_service(self):
        uuid = bytes(self.u.mem_read(self.r(5), 36))
        assert uuid.startswith((b'0000110b', b'0000110a'))
        return 0x600500 if self.service and uuid.startswith(b'0000110b' if self.role == 'sink' else b'0000110a') else 0

    def bt_get(self):
        if self.r(6) == 0x10:
            self.put(self.r(5), 0)
            self.u.mem_write(self.r(7), struct.pack('<H', 688))
            ptr = self.word(self.r(29)+0x14)
            self.u.mem_write(ptr, struct.pack('<H', 688))
        return 1

    def send_request(self):
        self.calls.append(('request', self.r(4), self.r(7)))
        return 0

    def connection_lost(self):
        self.calls.append(('lost', self.r(5)))
        self.put(self.r(4)+0x10, 0)
        return 0

    def schedule(self, seconds):
        self.timer_id += 1
        self.timers[self.timer_id] = (seconds, self.r(5), self.r(6), self.r(7))
        self.calls.append(('schedule', seconds, self.r(5)))
        return self.timer_id

    def remove(self):
        timer = self.r(5)
        assert timer in self.timers
        self.timers.pop(timer)
        return 0  # GSource destroy callback is outside selected routine

    def hook(self, u, address, size, data):
        if address == STOP:
            u.emu_stop(); return
        if address in self.hooks:
            result = self.hooks[address]()
        elif address in self.imports:
            name = self.imports[address]
            if name in ('g_malloc0', 'g_try_malloc', 'g_try_malloc0'): result = self.allocate()
            elif name == 'g_timeout_add_seconds_full': result = self.schedule(True)
            elif name == 'g_timeout_add_full': result = self.schedule(False)
            elif name == 'g_main_context_find_source_by_id': result = self.remove()
            elif name == 'g_io_channel_ref': result = self.r(4)
            elif name == 'g_io_add_watch': result = 17
            elif name == 'g_slist_append': result = self.r(4) or self.r(5)
            elif name in ('g_free', 'g_io_channel_unref', 'g_source_remove', 'g_slist_free_full', 'g_io_channel_shutdown'):
                if name == 'g_free': self.freed.append(self.r(4))
                result = 0
            elif name == 'ba2str':
                self.u.mem_write(self.r(5), b'00:11:22:33:44:55\0'); result = 0
            elif name == 'sprintf':
                self.u.mem_write(self.r(4), b'00:11:22:33:44:55\0'); result = 17
            else: raise AssertionError(f'unmocked import {name} at {address:x}')
        else: return
        u.reg_write(REG(2), result)
        u.reg_write(UC_MIPS_REG_PC, self.r(31))

    def call(self, address, *args):
        self.u.reg_write(REG(29), STACK)
        self.u.reg_write(REG(31), STOP)
        self.u.reg_write(REG(25), address)
        for n, value in enumerate(args, 4): self.u.reg_write(REG(n), value)
        self.u.emu_start(address, STOP, count=100000)
        assert self.u.reg_read(UC_MIPS_REG_PC) == STOP, 'instruction bound reached'
        return self.r(2)

    def constructor(self, incoming):
        # Execute constructor and connected callback, preserving actual timer/ref routines.
        self.session = self.call(0x23d48, CHANNEL if incoming else 0, DEVICE, SEPS)
        return self.session

    def reset_site(self, store):
        word = self.word(store)
        assert word >> 26 == 43 and word & 0xffff == 0x458
        base, value = word >> 21 & 31, word >> 16 & 31
        self.u.reg_write(REG(base), self.session)
        if value:
            # Some sites load30 more than one instruction before the store.
            start = {0x21d38:0x21d34, 0x24618:0x24608, 0x24c5c:0x24c4c}[store]
            self.u.emu_start(start, start+4, count=1)
            self.u.emu_start(store, store+4, count=1)
        else:
            self.u.emu_start(store, store+4, count=1)
        return self.word(self.session+0x458)


source = pathlib.Path(sys.argv[1])
raw = (subprocess.check_output(['unsquashfs', '-cat', str(source/'stock.squashfs'), 'usr/bin/bluetoothd'])
       if source.is_dir() else source.read_bytes())
assert hashlib.sha256(raw).hexdigest() == STOCK_SHA256
patched = patch_daemon(raw)
if source.is_dir(): assert (source/'bluetoothd').read_bytes() == patched
if len(sys.argv)>2: assert pathlib.Path(sys.argv[2]).read_bytes() == patched
assert len(raw)==len(patched) and [n for n,(a,b) in enumerate(zip(raw,patched)) if a!=b]==[OFFSET]
results=[]
for label, image, expected in (('stock',raw,30),('patched',patched,1)):
    m=Machine(image); session=m.constructor(True)
    assert m.word(session+0x458)==expected and m.word(session+0x45c)==1
    assert len(m.timers)==1 and m.calls[-1]==('schedule',True,expected)
    assert m.word(session)==1 and m.word(session+0x454)==1
    # Real reference acquisition cancels fallback and balances its held reference.
    m.call(0x20554,session)
    assert not m.timers and m.word(session)==1 and not m.word(session+0x454) and not m.word(session+0x45c)
    # Rearm retains one timer and one held reference; another arm replaces it.
    m.call(0x20608,session);m.call(0x20608,session)
    assert len(m.timers)==1 and m.word(session)==2
    # Null-channel outgoing construction skips incoming flag, grace and timer.
    outgoing=Machine(image);other=outgoing.constructor(False)
    assert not outgoing.timers and outgoing.word(other+0x458)==0 and outgoing.word(other+0x45c)==0
    # Actual expiry enters existing sink discovery; send_request sees Discover1.
    expiry=Machine(image);s=expiry.constructor(True);expiry.timers.clear()
    expiry.call(0x20a28,s)
    assert ('request',s,1) in expiry.calls
    assert not expiry.word(s+0x454) and not expiry.word(s+0x45c)
    assert not expiry.timers
    # The same incoming initializer supports a remote Audio Source too.
    source=Machine(image);source.role='source';s=source.constructor(True);source.timers.clear()
    source.call(0x20a28,s);assert ('request',s,1) in source.calls
    # Missing service fails through the existing timeout cleanup, not a retry loop.
    failed=Machine(image);failed.service=False;s=failed.constructor(True);failed.timers.clear()
    failed.call(0x20a28,s)
    assert ('lost',0x91) in failed.calls and not failed.timers and failed.freed.count(s)==1
    # All normal configured/close/abort reset instructions remain exact executable code.
    for site,value in ((0x21d38,30),(0x2379c,0),(0x23978,0),(0x24618,30),(0x24c5c,30)):
        assert m.reset_site(site)==value,(label,hex(site),m.word(session+0x458))
    # Idle cleanup before configuration uses the initial policy; configured reset uses30.
    idle=Machine(image);s=idle.constructor(True);idle.call(0x20554,s)
    idle.call(0x207bc,s)
    assert idle.calls[-1]==('schedule',True,expected)
    idle.reset_site(0x21d38);idle.call(0x20608,s)
    assert idle.calls[-1]==('schedule',True,30)
    results.append({'image':label,'incoming_seconds':expected,'outgoing_unchanged':True,
                    'seconds_api':True,'expiry_discover_both_roles':True,'missing_service_cleanup':True,
                    'cancel_rearm_balanced':True,'normal_resets_preserved':True})
print(json.dumps({'actual_mips':results,'single_differing_byte':hex(OFFSET),
                  'patched_sha256':hashlib.sha256(patched).hexdigest()},indent=2))
