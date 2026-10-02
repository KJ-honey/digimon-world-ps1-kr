# Appended at offset 0x400 of the already loaded DG helper sector.
# Descriptor: 0F 02 + little-endian u16 bank record. Payload: byte-NUL text.
# A private stack sector avoids aliasing the active DG expansion scratch.
.set noreorder
.set noat
.text
    lbu $t0,1($a0)
    addiu $t1,$zero,1
    beq $t0,$t1,catalog_plain
    nop
    addiu $sp,$sp,-2080
    sw $ra,28($sp)
    sw $a1,20($sp)
    sw $a2,24($sp)
    lhu $a2,2($a0)
    nop
    .if PACKED_CATALOG
    andi $t0,$a2,2047
    sw $t0,16($sp)
    srl $a2,$a2,11
    .endif
    sll $a2,$a2,11
    lui $t0,CATALOG_BANK_HI
    ori $t0,$t0,CATALOG_BANK_LO
    addu $a2,$a2,$t0
    lui $a0,0x8013
    addiu $a0,$a0,0x6bac
    addiu $a1,$sp,32
    addiu $a3,$zero,2048
    jal 0x800ec21c
    nop
    addiu $a0,$sp,32
    .if PACKED_CATALOG
    lw $t0,16($sp)
    nop
    addu $a0,$a0,$t0
    .endif
    lw $a1,20($sp)
    lw $a2,24($sp)
    jal 0x800f34e4
    nop
    lw $ra,28($sp)
    addiu $sp,$sp,2080
    jr $ra
    nop
catalog_plain:
    j 0x800f34e4
    nop
