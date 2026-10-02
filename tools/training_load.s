# Called only by the resident copy of opcode 64/27's training command.
# Same overlay, destination, status, callback, and queue; resolve the file in
# the game's RAM table before enqueueing, avoiding CdSearchFile in the tick.
.set noreorder
.set noat
.text
    addiu $sp,$sp,-64
    sw $ra,60($sp)
    sw $a0,28($sp)
    sw $a1,48($sp)
    sw $a3,52($sp)
    lw $t0,80($sp)
    addiu $t1,$a0,-1
    sw $t0,16($sp)
    sll $t1,$t1,2
    lui $t0,0x8014
    addiu $t0,$t0,-0x7670
    addu $t0,$t0,$t1
    lw $a1,0($t0)
    lw $t2,-0x120($t0)
    sw $a1,40($sp)
    sw $t2,44($sp)
    sw $zero,32($sp)
    addiu $a0,$sp,32
    jal 0x800a4444
    nop
    beqz $v0,fallback
    nop
    lw $a0,40($sp)
    lw $a1,44($sp)
    lw $a2,48($sp)
    lw $a3,52($sp)
    lw $t0,36($sp)
    addiu $t1,$sp,32
    sw $t0,24($sp)
    sw $t1,20($sp)
    jal 0x80100bb8
    nop
    b finish
    nop
fallback:
    lw $a0,28($sp)
    lw $a1,48($sp)
    addiu $a2,$zero,1
    lw $a3,52($sp)
    jal 0x801044ac
    nop
finish:
    lw $ra,60($sp)
    nop
    jr $ra
    addiu $sp,$sp,64
