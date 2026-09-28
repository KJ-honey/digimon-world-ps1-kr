# Replacement for generic NUL text, at RAM 800A5B48 (132-byte extent).
# Ordinary glyphs retain their original upload path. A non-NUL control lead
# dispatches the suffix to the catalog helper, loaded with the DG directory.
# 0F01 is the sole authored control. 0F02 is a pointer-table descriptor.
.set noreorder
.set noat
.text
    addiu $sp,$sp,-32
    sw $ra,28($sp)
    sw $s0,16($sp)
    sw $s1,20($sp)
    move $s0,$a0
    move $s1,$a1
    sw $a2,40($sp)
next:
    lbu $t0,0($s0)
    nop
    beqz $t0,done
    addiu $t1,$zero,15
    beq $t0,$t1,special
    lbu $t1,1($s0)
    move $a1,$s1
    sll $t1,$t1,8
    or $a0,$t0,$t1
    lw $a2,40($sp)
    jal 0x800a575c
    addiu $s0,$s0,2
    addiu $s1,$s1,12
    b next
    andi $s1,$s1,65535
special:
    move $a0,$s0
    move $a1,$s1
    lw $a2,40($sp)
    jal CATALOG_HELPER
    nop
done:
    lw $ra,28($sp)
    lw $s0,16($sp)
    lw $s1,20($sp)
    move $v0,$zero
    jr $ra
    addiu $sp,$sp,32
