"""Checked Q2 V1.32 PEQ hooks and target ABI imports; no vendor code is distributed."""
import re
import struct
from build import ROOT, FLAGS, GP, FUNCTIONS, GLOBALS, PRIVATE_FUNCTIONS, append_payload, check, fileoff, run, sha, symbols

PLAYER_SHA = '9c3f8c6d01f1ba62392622f6098b06a36b3e4f022a5468eaca6a5803e74f8e11'
PLAYER_BASE = 0xe10000  # stock final LOAD ends at 0xe03b58
# demux_audio_open's branch to the whole-file frame walk for Xing/VBRI MP3s; see docs/internals.md.
VBR_SCAN = 0x48fb3c
# The audio demuxer's seek slot (demuxer_desc_audio at 0x89fd90) holds demux_audio_seek; see docs/internals.md.
SEEK_SLOT, STOCK_SEEK = 0x89fdbc, 0x48d1ac
# The equalizer filter's descriptor (pinned) and its open slot, which becomes peq_open.
EQ_DESC, EQ_OPEN_SLOT = 0x893df8, 0x893e0c
# Stock skips the equalizer above 48 kHz (address, stock word, patched word); see docs/internals.md.
EQ_RATE_GATES = ((0x42ced0, 0x10400098, 0),            # beqz $v0 to "setequalizer off" -> nop
                 (0x42fd84, 0x1440003b, 0x1000003b))   # bnez $v0 to the insert -> b
LIBC = {
    'memset': ('void *', 'void *, int, unsigned'),
    'memcpy': ('void *', 'void *, const void *, unsigned'),
    'memcmp': ('int', 'const void *, const void *, unsigned'),
    'strcmp': ('int', 'const char *, const char *'),
    'strlen': ('unsigned', 'const char *'),
    'calloc': ('void *', 'unsigned, unsigned'),
    'free': ('void', 'void *'),
    'pow': ('double', 'double, double'), 'cos': ('double', 'double'),
    'sin': ('double', 'double'), 'log': ('double', 'double'),
    'fopen': ('void *', 'const char *, const char *'),
    'fread': ('unsigned', 'void *, unsigned, unsigned, void *'),
    'fwrite': ('unsigned', 'const void *, unsigned, unsigned, void *'),
    'fclose': ('int', 'void *'), 'ferror': ('int', 'void *'),
    'fflush': ('int', 'void *'), 'fileno': ('int', 'void *'), 'fsync': ('int', 'int'),
    'rename': ('int', 'const char *, const char *'), 'unlink': ('int', 'const char *'),
    '__xstat': ('int', 'int, const char *, void *'),
    'access': ('int', 'const char *, int'), 'mkdir': ('int', 'const char *, unsigned'),
    'lseek64': ('long long', 'int, long long, int'), 'read': ('int', 'int, void *, unsigned'),
    'snprintf': ('int', 'char *, unsigned, const char *, ...'),
    '__isoc99_sscanf': ('int', 'const char *, const char *, ...'),  # peq.c peq_number: no strtod in demo's GOT
    'opendir': ('void *', 'const char *'), 'closedir': ('int', 'void *'),
    'readdir': ('struct dirent *', 'void *'),
    'qsort': ('void', 'void *, unsigned, unsigned, int (*)(const void *, const void *)'),
    # libcstl and socket imports for the Play/Pause queue menu in navigation.c
    '_create_deque': ('void *', 'const char *'), 'deque_init': ('void', 'void *'),
    'deque_init_copy': ('void', 'void *, const void *'), 'deque_size': ('unsigned', 'const void *'),
    'deque_at': ('void *', 'const void *, unsigned'), '_deque_push_back': ('void', 'void *, ...'),
    'deque_assign': ('void', 'void *, const void *'), 'deque_clear': ('void', 'void *'),
    'deque_pop_back': ('void', 'void *'),
    'deque_destroy': ('void', 'void *'), 'send': ('int', 'int, const void *, unsigned, int'),
    # Coverflow's art thread (coverflow.c)
    'pthread_create': ('int', 'unsigned long *, const void *, void *(*)(void *), void *'),
    'pthread_join': ('int', 'unsigned long, void **'), 'pthread_detach': ('int', 'unsigned long'), 'pthread_mutex_lock': ('int', 'void *'),
    'pthread_mutex_unlock': ('int', 'void *'), 'statfs': ('int', 'const char *, void *'),
    'strdup': ('char *', 'const char *'),
    'strrchr': ('char *', 'const char *, int'), 'strcasecmp': ('int', 'const char *, const char *'),
    'strncasecmp': ('int', 'const char *, const char *, unsigned'),
    # iPod status bar clock (navigation.c)
    'time': ('long', 'long *'), 'localtime': ('const int *', 'const long *'),
    # Scrobble upload (scrobble.c): demo's libcurl and libcrypto
    'fseek': ('int', 'void *, long, int'), 'ftell': ('long', 'void *'), 'atoi': ('int', 'const char *'),
    'strstr': ('char *', 'const char *, const char *'),
    'curl_easy_init': ('void *', 'void'), 'curl_easy_setopt': ('int', 'void *, int, ...'),
    'curl_easy_perform': ('int', 'void *'), 'curl_easy_getinfo': ('int', 'void *, int, ...'),
    'curl_easy_cleanup': ('void', 'void *'), 'curl_slist_append': ('void *', 'void *, const char *'),
    'curl_slist_free_all': ('void', 'void *'), 'MD5_Init': ('int', 'void *'),
    'MD5_Update': ('int', 'void *, const void *, unsigned'), 'MD5_Final': ('int', 'unsigned char *, void *'),
    # Videos (books.c): q2video started and waited for, and its key socket
    'fork': ('int', 'void'), 'execl': ('int', 'const char *, const char *, ...'), 'exit': ('void', 'int'),
    # Home's Rockbox row (navigation.c rockbox_open)
    'system': ('int', 'const char *'),
    'waitpid': ('int', 'int, int *, int'), 'socket': ('int', 'int, int, int'), 'close': ('int', 'int'),
    'sendto': ('int', 'int, const void *, unsigned, int, const void *, unsigned'),
    # The visualizer's PCM tap (peq_player.c writes, visualizer.c reads) and its analysis
    'open': ('int', 'const char *, int, ...'), 'ftruncate': ('int', 'int, long'),
    'mmap': ('void *', 'void *, unsigned, int, int, int, long'),
    'mmap64': ('void *', 'void *, unsigned, int, int, int, long long'),
    'clock_gettime': ('int', 'int, void *'),
    'sinf': ('float', 'float'), 'cosf': ('float', 'float'),
}

def compile_common(out, binary, player=False, ipod=False):
    got = {}
    for line in run('readelf', '-AW', binary).splitlines():
        words = line.split()
        if len(words) >= 6 and 'UND' in words and re.fullmatch('[0-9a-f]{8}', words[0]):
            got[words[-1].split('@')[0]] = int(words[0], 16)
    gp = 0xb16750 if player else GP
    header = ['struct dirent { unsigned ino, off; unsigned short reclen; unsigned char d_type; char d_name[256]; };']
    asm = ['.set noreorder', '.text']
    for name, (ret, args) in LIBC.items():
        # Unused I/O is removed by --gc-sections in the player payload.
        alias = {'fopen': 'fopen64', 'readdir': 'readdir64', 'pow': '__pow_finite'}.get(name, name) if player else name
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
        syms = symbols(binary) | PRIVATE_FUNCTIONS
        for name, (ret, args) in FUNCTIONS.items():
            if name in syms and syms[name]:
                header.append(f'#define {name} (({ret} (*)({args}))0x{syms[name]:x}u)')
        # build.py has already checked each is a one-byte global.
        header += [f'#define {name} (*(volatile unsigned char *)0x{syms[name]:x}u)' for name in GLOBALS]
    (out/'peq_platform.h').write_text('\n'.join(header)+'\n')
    (out/'peq_imports.S').write_text('\n'.join(asm)+'\n')
    flags = [*FLAGS, '-fno-math-errno', '-ffunction-sections', '-fdata-sections', f'-DIPOD={int(ipod)}']
    if player: flags += ['-mnan=2008']
    objects = []
    for name in ['peq.c', 'peq_player.c'] if player else ['peq.c', 'peq_ui.c', 'coverflow.c', 'scrobble.c', 'photos.c', 'books.c', 'visualizer.c', 'playback.c', 'spotify.c', 'radio.c', 'tidal.c']:
        obj = out/(name+'.o')
        run('clang', *flags, '-I', out, '-c', ROOT/'patch'/name, '-o', obj)
        objects.append(obj)
    obj = out/'peq_imports.o'
    run('clang', *flags, '-c', out/'peq_imports.S', '-o', obj)
    return [*objects, obj]

def patch_player(raw, out):
    check(sha(raw) == PLAYER_SHA, 'Unsupported hciplayer binary')
    out.mkdir(exist_ok=True)
    binary = out/'stock-hciplayer'
    binary.write_bytes(raw)
    check(raw[fileoff(raw, EQ_DESC):fileoff(raw, EQ_DESC)+24].hex() ==
          'ac3d8900cc6388003c3b890098c988000100000024014500', 'EQ descriptor mismatch')
    objects = compile_common(out, binary, True)
    script = out/'link.ld'
    script.write_text('SECTIONS { . = 0xe10000; .text : { *(.text*) } .rodata : { *(.rodata*) } '
                      '.data : { *(.data*) *(.sdata*) } .bss : { *(.bss*) *(.sbss*) } '
                      '__end = .; /DISCARD/ : { *(.comment) *(.note*) *(.pdr) *(.mdebug*) '
                      '*(.MIPS.abiflags) *(.reginfo) } }')
    run('ld.lld', '-m', 'elf32ltsmip', '--gc-sections', '-T', script, '-e', 'peq_open', '--undefined=mp3_seek',
        *objects, '-o', out/'peq.elf')
    run('llvm-objcopy', '-O', 'binary', out/'peq.elf', out/'peq.bin')
    ps = symbols(out/'peq.elf')
    payload = (out/'peq.bin').read_bytes()
    data = bytearray(raw)
    off = fileoff(raw, EQ_OPEN_SLOT)
    data[off:off+4] = struct.pack('<I', ps['peq_open'])
    off = fileoff(raw, VBR_SCAN)
    data[off:off+4] = bytes(4)  # nop; was bnez $v0, 0x491de0
    for address, stock, patched in EQ_RATE_GATES:
        off = fileoff(raw, address)
        check(struct.unpack_from('<I', raw, off)[0] == stock, 'Equalizer rate gate mismatch')
        data[off:off+4] = struct.pack('<I', patched)
    off = fileoff(raw, SEEK_SLOT)
    check(struct.unpack_from('<I', raw, off)[0] == STOCK_SEEK, 'Audio demuxer seek slot mismatch')
    data[off:off+4] = struct.pack('<I', ps['mp3_seek'])
    append_payload(data, payload, PLAYER_BASE, max(len(payload), ps['__end']-PLAYER_BASE), 'player')
    (out/'hciplayer').write_bytes(data)
    return dict(stock_sha256=PLAYER_SHA, sha256=sha(data), payload_sha256=sha(payload))
