# Loaded by the original DG directory read into its own 2 KiB sector.
# No persistent state: the original continuation is kept on this call's stack.
.set noreorder
.set noat
.text
entry:
    addiu $sp,$sp,-48
    sw $ra,44($sp)
    sw $a0,32($sp)
    sw $a1,36($sp)
    lw $t0,-0x6cc8($gp)
    sw $zero,40($sp)
    andi $t1,$t0,1
    bnez $t1,invoke
    nop
    lui $t1,0x8015
    ori $t1,$t1,0x9784
    sltu $t2,$t0,$t1
    bnez $t2,invoke
    nop
    lui $t1,0x8016
    ori $t1,$t1,0x3784
    sltu $t2,$t0,$t1
    beqz $t2,invoke
    nop
    lhu $t1,0($t0)
    ori $t2,$zero,0xd715
    bne $t1,$t2,invoke
    nop
    lhu $a2,2($t0)
    sw $t0,40($sp)
    sll $a2,$a2,11
    lui $t1,BANK_HI
    ori $t1,$t1,BANK_LO
    addu $a2,$a2,$t1
    lui $a0,0x8013
    addiu $a0,$a0,0x6bac
    lui $a1,SCRATCH_HI
    ori $a1,$a1,SCRATCH_LO
    addiu $a3,$zero,2048
    lui $t9,0x800e
    ori $t9,$t9,0xc21c
    jalr $t9
    nop
    lui $t0,SCRATCH_HI
    ori $t0,$t0,SCRATCH_LO
    lw $t1,40($sp)
    lhu $t2,0($t0)
    lhu $t3,2($t0)
    addu $t1,$t1,$t2
    sw $t1,40($sp)
    # Preserve the consumer's next-opcode peek (consecutive 1A paging).
    lbu $t2,0($t1)
    addu $t3,$t0,$t3
    sb $t2,8($t3)
    addiu $t0,$t0,8
    sw $t0,-0x6cc8($gp)
invoke:
    lw $a0,32($sp)
    lw $a1,36($sp)
    lui $t9,TRAMPOLINE_HI
    ori $t9,$t9,TRAMPOLINE_LO
    jalr $t9
    nop
    lw $t0,40($sp)
    lw $ra,44($sp)
    beqz $t0,return
    nop
    sw $t0,-0x6cc8($gp)
return:
    jr $ra
    addiu $sp,$sp,48
trampoline:
    addiu $sp,$sp,-0x30
    sw $ra,0x1c($sp)
    lui $t9,0x800f
    ori $t9,$t9,0x4208
    jr $t9
    nop
