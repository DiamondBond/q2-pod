.set noreorder
.text
/* All four audited stock PIC prologues resolve the same GOT base. */
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
#ifdef RINGNAV_IPOD
resume rowh, 0x5c9dec
resume loaddata, 0x5ca990
resume prepare, 0x682ef4
resume scrollto, 0x5f0184
resume layout, 0x6461bc
resume btvol, 0x5accf8
resume stylecolor, 0x649f78
resume imgadd, 0x6445e0
#endif
