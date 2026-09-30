.set noreorder
.text
/* All audited stock PIC prologues resolve the same GOT base. */
.macro resume name, address
.globl stock_\name\()_trampoline
stock_\name\()_trampoline:
    lui $gp, 0xa2
    ori $gp, $gp, 0x6cc0
    j \address
    nop
.endm
resume keyup, 0x4e85d4
resume touch, 0x4e8bdc
resume paint, 0x6596ac
resume dispatch, 0x65e0f8
resume keylong, 0x4e8748
resume eq, 0x4f923c
resume home, 0x523c90
resume paint_bg, 0x65c788
resume playing, 0x52ca94
resume display, 0x4c1d10
resume color, 0x649f78
resume image, 0x6445e0
resume keydown, 0x4e8430
