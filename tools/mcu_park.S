/*
 * Q2 pinned MCU idle-loop extension. Linked at 0xf4006c00.
 *
 * Host protocol (all addresses MCU view):
 *   0xf4007f00 REQ: host writes 1 to request park, 0 only after clocks are on.
 *   0xf4007f04 ACK: MCU writes 1 only while sticky-parked, 0 after IRQ restore.
 * Host serializes firmware writes/reset/boot/mailbox writes. Before reset release
 * it initializes REQ/ACK while reset is asserted. REQ publication follows all
 * command/ring/doorbell writes and a full memory barrier. An ACK timeout must
 * retain clocks; elapsed time never grants permission to gate.
 *
 * This replaces the original wait at 0xf4000f98. Only that existing idle boundary
 * can park: the synchronous buzzer/DMA stop/release has already returned. A queued
 * mailbox flag takes priority over a park request. After masking MCU PWM IRQ9
 * (controller bit6), recheck the pending flag and ring indices with IRQs locally
 * disabled. No PWM register accesses occur here or while parked.
 *
 * The mailbox IRQ remains operational while parked, but cannot release park.
 * The host must acquire all required clocks before writing REQ=0. Pending PWM
 * IRQs are preserved, then serviced only after that clock-on grant.
 */
.set noreorder
.set noat
.set mips32r2
.text
.align 2
.globl q2_pwm_idle
.type q2_pwm_idle, @function
q2_pwm_idle:
    addiu $sp, $sp, -32
    sw $t0, 0($sp)
    sw $t1, 4($sp)
    sw $t2, 8($sp)
    sw $t3, 12($sp)
    sw $t4, 16($sp)
    sw $t5, 20($sp)
    sw $t6, 24($sp)
    sw $t7, 28($sp)
    lui $t0, 0xf400
    ori $t1, $t0, 0x7f00
    lui $t2, 0x1000

.globl q2_pwm_idle_wait
q2_pwm_idle_wait:
    lw $t3, 0x3f8c($t0)
    bne $t3, $zero, q2_pwm_command_ready
    nop
    lw $t3, 0($t1)
    addiu $t6, $zero, 1
    bne $t3, $t6, q2_pwm_idle_wait
    nop
    /*
     * REQ=1 is published only after the complete command. Service a committed
     * nonempty ring even if its mailbox IRQ was delayed/coalesced. Never peek
     * for dispatch under REQ=0: the host may still be publishing the command.
     */
    sync
    lw $t6, 0x3ce8($t0)
    lw $t7, 0x3cec($t0)
    bne $t6, $t7, q2_pwm_command_ready
    nop

    /* Same CP0 Status IE bit used by exact stock init0x14e0..14e8. */
    mfc0 $t4, $12
    addiu $t6, $zero, -2
    and $t6, $t4, $t6
    mtc0 $t6, $12
    ehb
    lw $t6, 0x1038($t2)
    andi $t5, $t6, 0x40
    ori $t6, $t6, 0x40
    sw $t6, 0x1038($t2)
    lw $t6, 0x1038($t2)
    sync

    /* No current ISR survives into this main-loop critical section. */
    lw $t3, 0($t1)
    addiu $t6, $zero, 1
    bne $t3, $t6, q2_pwm_restore
    nop
    lw $t3, 0x3f8c($t0)
    bne $t3, $zero, q2_pwm_restore
    nop
    lw $t6, 0x3ce8($t0)
    lw $t7, 0x3cec($t0)
    bne $t6, $t7, q2_pwm_restore
    nop

    /* Publish only after IRQ mask write/readback and empty-queue checks. */
    sync
    addiu $t3, $zero, 1
.globl q2_pwm_ack_park
q2_pwm_ack_park:
    sw $t3, 4($t1)
    sync
    mtc0 $t4, $12
    ehb

.globl q2_pwm_parked
q2_pwm_parked:
    lw $t3, 0($t1)
    bne $t3, $zero, q2_pwm_parked
    nop
    sync
    mfc0 $t4, $12
    addiu $t6, $zero, -2
    and $t6, $t4, $t6
    mtc0 $t6, $12
    ehb

.globl q2_pwm_restore
q2_pwm_restore:
    /* Restore just the owned mask bit, preserving every other IRQ mask. */
    lw $t6, 0x1038($t2)
    addiu $t7, $zero, -65
    and $t6, $t6, $t7
    or $t6, $t6, $t5
    sw $t6, 0x1038($t2)
    lw $t6, 0x1038($t2)
    sync
    mtc0 $t4, $12
    ehb
.globl q2_pwm_ack_run
q2_pwm_ack_run:
    sw $zero, 4($t1)
    sync
    b q2_pwm_idle_wait
    nop

.globl q2_pwm_command_ready
q2_pwm_command_ready:
    lw $t0, 0($sp)
    lw $t1, 4($sp)
    lw $t2, 8($sp)
    lw $t3, 12($sp)
    lw $t4, 16($sp)
    lw $t5, 20($sp)
    lw $t6, 24($sp)
    lw $t7, 28($sp)
    j 0xf4000fa0
    addiu $sp, $sp, 32
.size q2_pwm_idle, .-q2_pwm_idle
