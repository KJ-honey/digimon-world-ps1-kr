# PS1 R3000A / MIPS I, little endian. All delays explicit.
# Entry: existing renderer frame; u16 display code at sp+0x3e.
# Exit: sp+0x24 index, sp+0x30 decoded glyph, to 0x800a5870.
# Caller-saved registers and HI/LO only. No calls, no stack growth.
.set noreorder
.set noat
.text
.globl font_provider
font_provider:
    lhu $a0, 0x3e($sp)
    nop
    srl $t0, $a0, 8
    addiu $t0, $t0, -0xf0
    sltiu $t1, $t0, 8
    beq $t1, $zero, legacy
    nop
    andi $t1, $a0, 0xff
    addiu $t1, $t1, -0x40
    sltiu $t2, $t1, 0xbd
    beq $t2, $zero, missing
    nop
    addiu $t2, $zero, 0x3f
    beq $t1, $t2, missing
    nop
    sltiu $t2, $t1, 0x3f
    addiu $t2, $t2, -1
    addu $t1, $t1, $t2
    addiu $t2, $zero, 188
    multu $t0, $t2
    mflo $t0
    addu $t0, $t0, $t1
    sltiu $t1, $t0, EXTRA_COUNT
    beq $t1, $zero, missing
    nop
    addiu $v1, $t0, 992
    beq $zero, $zero, decode
    nop
legacy:
    lui $t0, 0x8012
    ori $t0, $t0, 0x8578
    addiu $v1, $zero, 0
    addiu $t2, $zero, 991
lookup:
    lhu $t1, 0($t0)
    nop
    beq $t1, $a0, decode
    nop
    addiu $v1, $v1, 1
    addiu $t0, $t0, 2
    bne $v1, $t2, lookup
    nop
missing:
    addiu $v1, $zero, 991
 decode:
    sw $v1, 0x24($sp)
    lui $t0, INDEX_HI
    ori $t0, $t0, INDEX_LO
    sll $v0, $v1, 2
    addu $t0, $t0, $v0
    lw $t7, 0($t0)
    lui $t1, SCRATCH_HI
    ori $t1, $t1, SCRATCH_LO
    sw $t1, 0x30($sp)
    lui $t9, DESCRIPTORS_HI
    ori $t9, $t9, DESCRIPTORS_LO
    addiu $t8, $zero, 3
segment:
    lw $t0, 0($t9)
    lw $t2, 4($t9)
    lw $a3, 8($t9)
    and $t2, $t7, $t2
    lw $t3, 16($t9)
    srlv $t7, $t7, $a3
    multu $t2, $t3
    mflo $t2
    lw $t4, 12($t9)
    addu $t0, $t0, $t2
    addiu $t2, $zero, 0
    addiu $t3, $zero, 0
row:
    sltiu $t5, $t3, 13
    beq $t5, $zero, emit
    nop
    lbu $t5, 0($t0)
    addiu $t0, $t0, 1
    sllv $t5, $t5, $t3
    or $t2, $t2, $t5
    addiu $t3, $t3, 8
    beq $zero, $zero, row
    nop
emit:
    andi $t6, $t2, 0xfff
    sll $t6, $t6, 4
    srl $t5, $t2, 12
    andi $t5, $t5, 1
    subu $t5, $zero, $t5
    andi $t5, $t5, 15
    or $t6, $t6, $t5
    sh $t6, 0($t1)
    addiu $t1, $t1, 2
    srl $t2, $t2, 13
    addiu $t3, $t3, -13
    addiu $t4, $t4, -1
    bne $t4, $zero, row
    nop
    addiu $t9, $t9, 20
    addiu $t8, $t8, -1
    bne $t8, $zero, segment
    nop
    lui $v0, 0x800a
    ori $v0, $v0, 0x5870
    jr $v0
    nop
