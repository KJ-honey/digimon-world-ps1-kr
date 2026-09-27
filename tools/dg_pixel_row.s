# DG row staging: 256 x 12 x 4bpp on the stack, synchronous upload.
# All existing VM/color/tab/glyph selection remains in the original routines.
.set noreorder
.set noat
.text
row_start:
    addiu $sp, $sp, -0x650
    sw $ra, 0x1c($sp)
    sw $a0, 0x10($sp)
    sw $a1, 0x14($sp)
    sw $a2, 0x18($sp)
    addiu $t0, $sp, 0x40
    addiu $t1, $sp, 0x640
zero_row:
    sw $zero, 0($t0)
    addiu $t0, $t0, 4
    bne $t0, $t1, zero_row
    nop
    lui $t9, BASE_HI
    ori $t9, $t9, TRAMP_LO
    jalr $t9
    nop
    sw $v0, 0x24($sp)
    lw $t0, 0x14($sp)
    lw $t1, 0x20($sp)
    nop
    addu $t1, $t1, $t0
    sltiu $t2, $t1, 257
    bne $t2, $zero, end_bounded
    nop
    addiu $t1, $zero, 256
end_bounded:
    srl $t0, $t0, 2
    addiu $t1, $t1, 3
    srl $t1, $t1, 2
    subu $t2, $t1, $t0
    slt $t8, $zero, $t2
    beq $t8, $zero, finish
    nop
    addiu $t1, $t0, 0x2c0
    sh $t1, 0x30($sp)
    lw $t1, 0x18($sp)
    nop
    addiu $t1, $t1, 0x100
    sh $t1, 0x32($sp)
    sh $t2, 0x34($sp)
    addiu $t1, $zero, 12
    sh $t1, 0x36($sp)
    sll $t2, $t2, 1
    sll $t0, $t0, 1
    addiu $t3, $sp, 0x40
    addu $t4, $t3, $t0
    addiu $t5, $zero, 12
compact_row:
    move $t6, $t4
    move $t7, $t2
compact_byte:
    lbu $t8, 0($t6)
    addiu $t6, $t6, 1
    sb $t8, 0($t3)
    addiu $t3, $t3, 1
    addiu $t7, $t7, -1
    bne $t7, $zero, compact_byte
    nop
    addiu $t4, $t4, 128
    addiu $t5, $t5, -1
    bne $t5, $zero, compact_row
    nop
    addiu $a0, $sp, 0x30
    addiu $a1, $sp, 0x40
    jal 0x8009486c
    nop
    move $a0, $zero
    jal 0x80094774
    nop
finish:
    lw $v0, 0x24($sp)
    lw $ra, 0x1c($sp)
    addiu $sp, $sp, 0x650
    jr $ra
    nop
.org 0x200
# Displaced row prologue. The existing epilogue returns to row_start.
trampoline:
    addiu $sp, $sp, -0x30
    sw $ra, 0x1c($sp)
    j 0x800f34ec
    nop
.org 0x220
row_end:
    sw $s0, 0x50($sp)
    lw $ra, 0x1c($sp)
    lw $s2, 0x18($sp)
    j 0x800f3854
    nop
.org 0x240
# Cleared pixels are already zero in this row's fresh staging buffer.
clear_row:
    jr $ra
    nop
.org 0x260
upload_dispatch:
    lw $t0, 0x1c($sp)
    lui $t1, 0x800f
    ori $t1, $t1, 0x3838
    bne $t0, $t1, normal_upload
    nop
    lhu $t0, 0x44($sp)
    addiu $t1, $sp, 0xb0
    srl $t0, $t0, 1
    addu $t1, $t1, $t0
    addiu $t2, $zero, 11
copy_row:
    move $t3, $t1
    addiu $t4, $zero, 6
copy_byte:
    lbu $t5, 0($a1)
    addiu $a1, $a1, 1
    sb $t5, 0($t3)
    addiu $t3, $t3, 1
    addiu $t4, $t4, -1
    bne $t4, $zero, copy_byte
    nop
    addiu $t1, $t1, 128
    addiu $t2, $t2, -1
    bne $t2, $zero, copy_row
    nop
    jr $ra
    nop
normal_upload:
    j 0x8009486c
    nop
