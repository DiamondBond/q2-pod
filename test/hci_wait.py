#!/usr/bin/env python3
"""hciplayer's futex waits (patch/peq_player.c): the built player under Unicorn.

The command thread's store to the play flag goes on through hci_play_wake with every register as it was
and one FUTEX_WAKE_PRIVATE on the flag; the stopped loop's wait is a FUTEX_WAIT_PRIVATE on it while 0;
the pause loop waits on cmd_gen only while no command moved it. Usage: test/hci_wait.py BUILD_DIR"""
import pathlib, struct, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'tools'))
from build import j, jal, machine, read, symbols, word
from peq import CMD_DONE, IDLE_WAIT, PAUSE_WAIT, PLAY_WAKE
from unicorn import UC_HOOK_INTR
from unicorn.mips_const import *

out = pathlib.Path(sys.argv[1])/'peq'
raw = (out/'hciplayer').read_bytes()
ps = symbols(out/'peq.elf')
for (address, _), want in ((IDLE_WAIT, jal(ps['hci_idle_wait'])), (PLAY_WAKE, j(ps['hci_play_wake'])),
                           (PAUSE_WAIT, jal(ps['hci_pause_wait'])), (CMD_DONE, jal(ps['hci_command']))):
    assert struct.unpack_from('<I', raw, address-0x400000)[0] == want, hex(address)
FLAG, STACK, DONE = 0xb10e34, 0x2008000, 0x2000000
GPRS = [r for r in range(UC_MIPS_REG_1, UC_MIPS_REG_31 + 1) if r not in (UC_MIPS_REG_29,)]

def run(entry, regs, end, kernel=lambda u: 0):
    """Syscalls seen running from entry to end; the kernel clobbers every caller-saved register."""
    u = machine(raw, DONE)
    u.reg_write(UC_MIPS_REG_29, STACK)
    for r, v in regs.items(): u.reg_write(r, v)
    seen = []
    def syscall(u, intno, unused):
        a = [u.reg_read(r) for r in (UC_MIPS_REG_V0, UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2)]
        seen.append(tuple(a))
        for r in (UC_MIPS_REG_1, UC_MIPS_REG_3, *range(UC_MIPS_REG_8, UC_MIPS_REG_15 + 1), UC_MIPS_REG_24, UC_MIPS_REG_25):
            u.reg_write(r, 0xdead0000 | r)
        u.reg_write(UC_MIPS_REG_HI, 0x5a5a), u.reg_write(UC_MIPS_REG_LO, 0xa5a5)
        u.reg_write(UC_MIPS_REG_V0, kernel(u)), u.reg_write(UC_MIPS_REG_7, 0)
    u.hook_add(UC_HOOK_INTR, syscall)
    u.emu_start(entry, end, count=10000)
    return u, seen

# The play command: the stock store in the delay slot, then the wake, then stock's 0x4224b4 with every
# register, hi and lo, and the stack as the store left them.
regs = {r: 0x1000 + r for r in GPRS}
regs[UC_MIPS_REG_4], regs[UC_MIPS_REG_2] = 0xb10000, 1  # lui $4, 0xb1 (0x422d78); the flag's value
regs[UC_MIPS_REG_HI], regs[UC_MIPS_REG_LO] = 0x1234, 0x5678
u, seen = run(PLAY_WAKE[0], regs, 0x4224b4)
assert seen == [(4238, FLAG, 129, 1)], seen
assert read(u, FLAG) == 1 and u.reg_read(UC_MIPS_REG_29) == STACK and u.reg_read(UC_MIPS_REG_PC) == 0x4224b4
assert {r: u.reg_read(r) for r in regs} == regs, [r for r in regs if u.reg_read(r) != regs[r]]

# The stopped loop's wait: FUTEX_WAIT_PRIVATE on the flag while 0, with a timeout, and back to its caller.
u, seen = run(ps['hci_idle_wait'], {UC_MIPS_REG_4: 10000, UC_MIPS_REG_31: DONE}, DONE)
assert len(seen) == 1 and seen[0][:4] == (4238, FLAG, 128, 0), seen

# The pause loop: a wait while cmd_gen is as last seen; none once a command moved it.
gen = ps['cmd_gen']
u = machine(raw, DONE)
seen = []
def syscall(u, intno, unused):
    seen.append(tuple(u.reg_read(r) for r in (UC_MIPS_REG_V0, UC_MIPS_REG_A0, UC_MIPS_REG_A1, UC_MIPS_REG_A2)))
    u.reg_write(UC_MIPS_REG_V0, 0), u.reg_write(UC_MIPS_REG_7, 0)
u.hook_add(UC_HOOK_INTR, syscall)
def pause_wait():
    u.reg_write(UC_MIPS_REG_29, STACK), u.reg_write(UC_MIPS_REG_31, DONE)
    u.emu_start(ps['hci_pause_wait'], DONE, count=10000)
word(u, gen, 5); pause_wait()  # moved from the 0 last seen: no wait, 5 is seen
pause_wait()                   # unchanged: waits while it is 5
word(u, gen, 6); pause_wait()  # a command while the loop checked: no wait
assert seen == [(4238, gen, 128, 5)], seen
print('hciplayer futex waits: the play wake keeps every register; the stopped and paused loops wait only while nothing changed.')
