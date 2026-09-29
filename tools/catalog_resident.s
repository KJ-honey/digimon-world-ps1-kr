# Always resident with the expanded font, including before DG initialization.
.set noreorder
.set noat
.text
catalog_dispatch:
    lbu $t0,1($a0)
    addiu $t1,$zero,1
    beq $t0,$t1,plain
    nop
    j 0x80160384
    nop
plain:
    j 0x800f34e4
    nop
.org 0x40
# Return actual pixel width of a byte-NUL string, including resident locations.
catalog_width:
    move $v0,$zero
width_next:
    lbu $t0,0($a0)
    addiu $t1,$zero,15
    beqz $t0,width_done
    addiu $a0,$a0,2
    beq $t0,$t1,width_half
    nop
    b width_next
    addiu $v0,$v0,12
width_half:
    b width_next
    addiu $v0,$v0,6
width_done:
    jr $ra
    nop
