"""Actual packaged MIPS hook and writer, with synthetic filesystem boundaries."""
from q2emu import Machine, REGS, syms, payload_syms

LIVE = '/mnt/data/config.ini'
TEMP = '/mnt/data/.q2-config.new'
OLD = b'[SYSSET]\nLANGUAGE=2\nBLUETOOTH=0\n[IPOD]\nLIGHT=1\n'
NEW = OLD.replace(b'BLUETOOTH=0', b'BLUETOOTH=1')


class Interrupted(Exception):
    pass


class ConfigMachine(Machine):
    def __init__(self, fail=0, cut=0):
        super().__init__()
        self.files = {LIVE: OLD}
        self.fds = {}
        self.steps = 0
        self.fail, self.cut = fail, cut
        self.err = self.alloc(4)
        self.handlers.pop(syms['toolsWriteConfig'], None)
        for name in ('open', 'read', 'write', 'close', 'fsync', 'rename', 'unlink', '__errno_location'):
            self.handlers[syms[name + '@GLIBC_2.0']] = 'cfg:' + name

    def hook(self, u, address, size, unused):
        name = self.handlers.get(address, '')
        if not name.startswith('cfg:'):
            return super().hook(u, address, size, unused)
        name = name[4:]
        a, b, c, _ = [u.reg_read(r) for r in REGS]
        if name == '__errno_location':
            return self.returns(self.err, clobber=True)
        self.steps += 1
        if self.steps == self.cut:
            raise Interrupted()
        if self.steps == self.fail:
            self.word(self.err, 5)
            return self.returns(-1, clobber=True)
        result = 0
        if name == 'open':
            path = self.text(a)
            assert b in (0x90000, 0xa0000, 0xa0301), hex(b)
            assert path in ('/mnt/data', LIVE, TEMP)
            if b == 0xa0301:
                assert path == TEMP and c == 0o644
                self.files[path] = b''
            result = len(self.fds) + 100
            self.fds[result] = [path, 0]
        elif name == 'read':
            path, pos = self.fds[a]
            data = self.files[path][pos:pos+c]
            if data:
                u.mem_write(b, data)
            self.fds[a][1] += len(data)
            result = len(data)
        elif name == 'write':
            path, _ = self.fds[a]
            assert path == TEMP  # live file is NEVER opened for writing
            self.files[path] += bytes(u.mem_read(b, c))
            result = c
        elif name == 'close':
            self.fds.pop(a)
        elif name == 'fsync':
            assert a in self.fds
        elif name == 'rename':
            assert self.text(a) == TEMP and self.text(b) == LIVE
            self.files[LIVE] = self.files.pop(TEMP)
        elif name == 'unlink':
            assert self.text(a) == TEMP
            self.files.pop(TEMP, None)
        return self.returns(result, clobber=True)

    def save(self):
        return self.call(address=syms['toolsWriteConfig'], gap=0,
                         args=tuple(self.string(s) for s in (LIVE, 'SYSSET', 'BLUETOOTH', '1')))


m = ConfigMachine()
assert m.save() == 0 and m.files[LIVE] == NEW
steps = m.steps
for i in range(1, steps + 1):
    m = ConfigMachine(fail=i)
    m.save()
    assert m.files[LIVE] in (OLD, NEW), ('failure', i)
    m = ConfigMachine(cut=i)
    try:
        m.save()
    except Interrupted:
        pass
    else:
        raise AssertionError(('cut not reached', i))
    assert m.files[LIVE] in (OLD, NEW), ('interruption', i)
print(f'PASS: actual toolsWriteConfig hook, MIPS flags, {steps} failure and interruption points')
