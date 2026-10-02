# Initial DG directory supplies code/dictionary and overflow pool. No CD I/O.
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
    lui $t6,0x8015
    ori $t6,$t6,0x9784
    sltu $t2,$t0,$t6
    bnez $t2,invoke
    nop
    lui $t1,0x8016
    ori $t1,$t1,0x3784
    sltu $t2,$t0,$t1
    beqz $t2,invoke
    nop
    # MAPHEAD ends before the DG directory; ordinary script starts after it.
    lui $t1,0x8015
    ori $t1,$t1,0xf784
    sltu $t2,$t0,$t1
    bnez $t2,marker
    nop
    lui $t6,0x8016
    ori $t6,$t6,0x1784
    sltu $t2,$t0,$t6
    bnez $t2,invoke
    nop
marker:
    lhu $t1,0($t0)
    ori $t2,$zero,0xd715
    bne $t1,$t2,invoke
    nop
    sw $t0,40($sp)
    lhu $t1,2($t0)
    lui $t7,SCRATCH_HI
    ori $t7,$t7,SCRATCH_LO
    lui $t8,DICTIONARY_HI
    ori $t8,$t8,DICTIONARY_LO
    move $t4,$t7
resolve:
    andi $t2,$t1,0x8000
    andi $t1,$t1,0x7fff
    beqz $t2,local
    addu $t3,$t6,$t1
    addu $t3,$t7,$t1
local:
next:
    lbu $t1,0($t3)
    addiu $t3,$t3,1
    sltiu $t2,$t1,253
    bnez $t2,pair
    sll $t2,$t1,1
    addiu $t5,$zero,255
    beq $t1,$t5,decoded
    addiu $t5,$zero,254
    lbu $t2,0($t3)
    lbu $t9,1($t3)
    addiu $t3,$t3,2
    beq $t1,$t5,jump
    nop
    sb $t2,0($t4)
    sb $t9,1($t4)
    b next
    addiu $t4,$t4,2
jump:
    sll $t9,$t9,8
    or $t1,$t2,$t9
    b resolve
    nop
pair:
    addu $t2,$t8,$t2
    lhu $t2,0($t2)
    nop
    sh $t2,0($t4)
    b next
    addiu $t4,$t4,2
decoded:
    lw $t0,40($sp)
    lhu $t1,0($t7)
    nop
    addu $t0,$t0,$t1
    sw $t0,40($sp)
    lbu $t1,0($t0)
    addiu $t7,$t7,2
    sb $t1,0($t4)
    sw $t7,-0x6cc8($gp)
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
