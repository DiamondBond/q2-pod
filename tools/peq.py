"""Checked Q2 V1.32 PEQ hooks and target ABI imports; no vendor code is distributed."""
import pathlib
import re
import struct
from build import ROOT, FLAGS, FUNCTIONS, check, fileoff, run, segments, sha, symbols

PLAYER_SHA = '9c3f8c6d01f1ba62392622f6098b06a36b3e4f022a5468eaca6a5803e74f8e11'
PLAYER_BASE = 0xe10000  # stock final LOAD ends at 0xe03b58
DEMO_HOOKS = {
    'playset_equalizer_page_init': (0x4b642c, 'peq_page_init', '57001c3c94089c2721e09903'),
    'set_equalizer_value': (0x4f9230, 'peq_stock_eq', '53001c3c90da9c2721e09903'),
}
LIBC = {
    'memset': ('void *', 'void *, int, unsigned'),
    'memcpy': ('void *', 'void *, const void *, unsigned'),
    'memcmp': ('int', 'const void *, const void *, unsigned'),
    'strcmp': ('int', 'const char *, const char *'),
    'strlen': ('unsigned', 'const char *'),
    'calloc': ('void *', 'unsigned, unsigned'),
    'free': ('void', 'void *'),
    'pow': ('double', 'double, double'), 'cos': ('double', 'double'),
    'sin': ('double', 'double'), 'sqrt': ('double', 'double'),
    'fopen': ('void *', 'const char *, const char *'),
    'fread': ('unsigned', 'void *, unsigned, unsigned, void *'),
    'fwrite': ('unsigned', 'const void *, unsigned, unsigned, void *'),
    'fclose': ('int', 'void *'), 'ferror': ('int', 'void *'),
    'fflush': ('int', 'void *'), 'fileno': ('int', 'void *'), 'fsync': ('int', 'int'),
    'rename': ('int', 'const char *, const char *'), 'unlink': ('int', 'const char *'),
    'access': ('int', 'const char *, int'), 'mkdir': ('int', 'const char *, unsigned'),
    'snprintf': ('int', 'char *, unsigned, const char *, ...'),
    'opendir': ('void *', 'const char *'), 'closedir': ('int', 'void *'),
    'readdir': ('struct dirent *', 'void *'),
    'qsort': ('void', 'void *, unsigned, unsigned, int (*)(const void *, const void *)'),
}
UI = {
    'widget_destroy_children': ('int', 'void *'),
    'list_view_create': ('void *', 'void *, int, int, int, int'),
    'scroll_view_create': ('void *', 'void *, int, int, int, int'),
    'list_item_create': ('void *', 'void *, int, int, int, int'),
    'navigator_back': ('int', 'void'),
}

def compile_common(out, binary, player=False):
    got = {}
    for line in run('readelf', '-AW', binary).splitlines():
        words = line.split()
        if len(words) >= 6 and 'UND' in words and re.fullmatch('[0-9a-f]{8}', words[0]):
            got[words[-1].split('@')[0]] = int(words[0], 16)
    gp = 0xb16750 if player else 0xa26cc0
    header = ['struct dirent { unsigned ino, off; unsigned short reclen; unsigned char d_type; char d_name[256]; };']
    asm = ['.set noreorder', '.text']
    for name, (ret, args) in LIBC.items():
        # Unused I/O is removed by --gc-sections in the player payload.
        alias = {'fopen': 'fopen64', 'readdir': 'readdir64', 'pow': '__pow_finite',
                 'sqrt': '__sqrt_finite'}.get(name, name) if player else name
        if alias not in got:
            header.append(f'extern {ret} {name}({args});')
            continue
        address = got[alias]
        header += [f'extern {ret} peq_lib_{name}({args});', f'#define {name} peq_lib_{name}']
        asm += [f'.section .text.peq_lib_{name},"ax",@progbits', f'.globl peq_lib_{name}',
                f'peq_lib_{name}:', f'lui $gp, {gp >> 16}', f'ori $gp, $gp, {gp & 65535}',
                f'lui $t8, {address >> 16}', f'ori $t8, $t8, {address & 65535}',
                'lw $t9, 0($t8)', 'jr $t9', 'nop']
        if name in ('memcpy', 'memset'):
            asm += [f'.globl {name}', f'.set {name}, peq_lib_{name}']
    if not player:
        syms = symbols(binary)
        for name, (ret, args) in (FUNCTIONS | UI).items():
            if name in syms and syms[name]:
                header.append(f'#define {name} (({ret} (*)({args}))0x{syms[name]:x}u)')
    (out/'peq_platform.h').write_text('\n'.join(header)+'\n')
    (out/'peq_imports.S').write_text('\n'.join(asm)+'\n')
    flags = [*FLAGS, '-fno-math-errno', '-ffunction-sections', '-fdata-sections']
    if player: flags += ['-mnan=2008']
    objects = []
    for name in ['peq.c', 'peq_player.c' if player else 'peq_ui.c']:
        obj = out/(name+'.o')
        run('clang', *flags, '-I', out, '-c', ROOT/'patch'/name, '-o', obj)
        objects.append(obj)
    obj = out/'peq_imports.o'
    run('clang', *flags, '-c', out/'peq_imports.S', '-o', obj)
    return [*objects, obj]

def patch_demo(data, ps):
    records = {}
    for name, (address, target, original) in DEMO_HOOKS.items():
        off = fileoff(data, address)
        check(data[off:off+12].hex() == original, f'{name}: PEQ prologue mismatch')
        data[off:off+8] = struct.pack('<II', 0x08000000 | (ps[target] >> 2), 0)
        records[name] = dict(address=hex(address), replacement=target, original=original)
    return records

def patch_player(raw, out):
    check(sha(raw) == PLAYER_SHA, 'Unsupported hciplayer binary')
    out.mkdir(exist_ok=True)
    binary = out/'stock-hciplayer'
    binary.write_bytes(raw)
    check(raw[fileoff(raw, 0x893df8):fileoff(raw, 0x893df8)+24].hex() ==
          'ac3d8900cc6388003c3b890098c988000100000024014500', 'EQ descriptor mismatch')
    objects = compile_common(out, binary, True)
    script = out/'link.ld'
    script.write_text('SECTIONS { . = 0xe10000; .text : { *(.text*) } .rodata : { *(.rodata*) } '
                      '.data : { *(.data*) *(.sdata*) } .bss : { *(.bss*) *(.sbss*) } '
                      '__end = .; /DISCARD/ : { *(.comment) *(.note*) *(.pdr) *(.mdebug*) '
                      '*(.MIPS.abiflags) *(.reginfo) } }')
    run('ld.lld', '-m', 'elf32ltsmip', '--gc-sections', '-T', script, '-e', 'peq_open',
        *objects, '-o', out/'peq.elf')
    run('llvm-objcopy', '-O', 'binary', out/'peq.elf', out/'peq.bin')
    ps = symbols(out/'peq.elf')
    payload = (out/'peq.bin').read_bytes()
    data = bytearray(raw)
    off = fileoff(raw, 0x893e0c)
    data[off:off+4] = struct.pack('<I', ps['peq_open'])
    nulls = [(o,p) for o,p in segments(data) if p[0] == 0]
    check(len(nulls) == 1 and nulls[0][0] == segments(data)[-1][0], 'No player PT_NULL slot')
    check(all(p[2]+p[5] < PLAYER_BASE for _,p in segments(data) if p[0] == 1), 'Player mapping overlap')
    append = (len(data)+65535)&~65535
    data.extend(bytes(append-len(data)))
    data.extend(payload)
    struct.pack_into('<8I', data, nulls[0][0], 1, append, PLAYER_BASE, PLAYER_BASE,
                     len(payload), max(len(payload), ps['__end']-PLAYER_BASE), 5, 65536)
    (out/'hciplayer').write_bytes(data)
    return dict(stock_sha256=PLAYER_SHA, sha256=sha(data), payload_sha256=sha(payload),
                descriptor_address='0x893e0c', original='24014500', replacement=hex(ps['peq_open']),
                payload_bytes=len(payload), address=hex(PLAYER_BASE), file_offset=hex(append))
