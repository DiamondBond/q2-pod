"""Map a MIPS ELF into Unicorn for desktop emulation."""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1] / "tools"))

from build import segments


def load_elf(u, *images, load=0):
    """Map the images' LOAD pages once, shifted by load, then copy each segment's exact file bytes.

    A linker script may place text, rodata and data in separate LOAD segments sharing their boundary
    page. Mapping every segment independently rejects that valid ELF; skipping its mem_write would
    silently lose content.
    """
    pages, loads = set(), []
    for image in images:
        for _, (kind, off, base, _, filesz, memsz, _, _) in segments(image):
            if kind != 1 or not memsz:
                continue
            base += load
            assert filesz <= memsz and off + filesz <= len(image)
            assert all(base + memsz <= a or a + n <= base for a, n, _ in loads), 'overlapping LOAD data'
            pages.update(range(base & ~4095, (base + memsz + 4095) & ~4095, 4096))
            loads.append((base, memsz, image[off:off + filesz]))
    ordered = sorted(pages)
    start = end = ordered[0]
    for page in ordered[1:] + [ordered[-1] + 8192]:
        if page != end + 4096:
            u.mem_map(start, end + 4096 - start)
            start = page
        end = page
    for base, _, data in loads:
        u.mem_write(base, data)  # Fresh mappings already zero each segment's BSS.
