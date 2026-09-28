/* PS1 R3000A, freestanding MIPS I. All addresses are RAM addresses.
 * Only complete supported syllables are written to the original 13-byte name.
 * Transient composition and texture cache belong to the SHOP overlay.
 */
typedef unsigned char u8;
typedef unsigned short u16;
typedef unsigned int u32;
#include "name_data.h"
#define NAME ((volatile u8*)0x80167bcc)
#define GP 0x80144e0c
#define CUR (*(volatile u8*)(GP-0x6c3a))
#define PHASE (*(volatile u16*)(GP-0x6caa))
#define CALL(addr, type) ((type)(addr))
#define SOUND(n) CALL(0x800cf96c,void(*)(int,int))(0,n)
#define KEY(n) CALL(0x800fa6ec,int(*)(int))(n)
struct Edit {u8 initial, medial, final, cursor, length, error, shifted;};
__attribute__((section(".state"))) struct Edit edit;
/* KS membership, legacy membership, then packed 10-bit legacy indices. */
static u8 packed(unsigned n) {
    return n<DATA_SPLIT ? ((const u8*)DATA_A)[n] : ((const u8*)DATA_B)[n-DATA_SPLIT];
}
static unsigned pop(unsigned x) {
    x=x-((x>>1)&0x55); x=(x&0x33)+((x>>2)&0x33); return (x+(x>>4))&15;
}
u16 name_lookup(unsigned l,unsigned v,unsigned t) {
    if(l>=19 || v>=21 || t>=28) return 0;
    unsigned n=(l*21+v)*28+t, b=n>>3, mask=1u<<(n&7), rank=0;
    unsigned value=packed(b);
    if(!(value&mask)) return 0;
    for(unsigned i=0;i<b;i++) rank+=pop(packed(i));
    rank+=pop(value&(mask-1));
    unsigned old=0;
    for(unsigned i=0;i<(rank>>3);i++) old+=pop(packed(1397+i));
    unsigned flags=packed(1397+(rank>>3));
    old+=pop(flags&((1u<<(rank&7))-1));
    unsigned idx;
    if(flags&(1u<<(rank&7))) {
        unsigned bit=old*10,at=1691+(bit>>3);
        idx=(packed(at)|(packed(at+1)<<8))>>(bit&7);idx&=1023;
        return ((const u16*)0x80128578)[idx];
    }
    idx=rank-old;
    unsigned lead=0xf0, trail=idx;
    while(trail>=188) {trail-=188; lead++;}
    trail+=0x40; if(trail>=0x7f) trail++;
    return (lead<<8)|trail;
}
static void glyph(u16 c,int x,int y) {
    CALL(0x800a575c,void(*)(int,int,int))((c>>8)|(c<<8),x,y);
    CALL(0x80094774,int(*)(int))(0);
}
static void text(const u16* p,int x,int y) {
    while(*p) {glyph(*p++,x,y);x+=12;}
}
static unsigned key(unsigned i) {return edit.shifted && i<10?shiftkeys[i]:keys[i];}
static void position(unsigned i,int* x,int* y) {
    unsigned row=i<10?0:i<19?1:2, col=i-(row==0?0:row==1?10:19);
    *x=col*24+(row==2?24:0);*y=48+row*20;
}
static void refresh(void) {
    short rect[4]={0,0,252,132};
    CALL(0x800a5698,void(*)(short*))(rect);
    CALL(0x80094774,int(*)(int))(0);
    CALL(0x800a5728,void(*)(int))(1);
    text(labels[(*(volatile u8*)(GP-0x6c2e)&1)?1:0],0,0);
    for(unsigned i=0;i<edit.length;i++) glyph((NAME[i*2]<<8)|NAME[i*2+1],108+i*12,0);
    text(labels[edit.error?3:2],0,24);
    if(!edit.error) {
        u16 c=name_lookup(edit.initial,edit.medial,edit.final);
        if(c) glyph(c,96,24);
        else {
            if(edit.initial<19) glyph(initials[edit.initial],96,24);
            if(edit.medial<21) glyph(medials[edit.medial],120,24);
            if(edit.final) glyph(finals[edit.final],144,24);
        }
    }
    for(unsigned i=0;i<26;i++) {int x,y;position(i,&x,&y);glyph(jamo_glyphs[key(i)],x,y);}
    text(labels[4],0,108);text(labels[5],0,120);
}
void name_init(void) {
    edit.initial=edit.medial=255;edit.final=edit.cursor=edit.error=edit.shifted=0;
    edit.length=0;
    while(edit.length<6 && NAME[edit.length*2]) edit.length++;
    CUR=edit.length<6?edit.length:5;
    refresh();
}
void name_field(void) {}
void name_draw(void) {
    int x=*(volatile short*)0x80145e74, y=*(volatile short*)0x80145e76;
    CALL(0x80103c84,void(*)(int,int,int,int,int,int,int,int,int))(0,x+12,y+4,252,132,0,0,5,1);
    int cx,cy;position(edit.cursor,&cx,&cy);
    CALL(0x80086504,void(*)(int,int,int,int))(1,12+cx,16+cy,12);
}
/* Compound tables use Unicode L/V/T indices, independent of game encoding. */
static const u8 vpair[][3]={{8,0,9},{8,1,10},{8,20,11},{13,4,14},{13,5,15},{13,20,16},{18,20,19},{9,20,10},{14,20,15}};
static const u8 tpair[][3]={{1,19,3},{4,22,5},{4,27,6},{8,1,9},{8,16,10},{8,17,11},{8,19,12},{8,25,13},{8,26,14},{8,27,15},{17,19,18}};
static unsigned combine(const u8 (*table)[3],unsigned n,unsigned a,unsigned b) {
    for(unsigned i=0;i<n;i++) if(table[i][0]==a && table[i][1]==b) return table[i][2];
    return 255;
}
static unsigned first(const u8 (*table)[3],unsigned n,unsigned c) {
    for(unsigned i=0;i<n;i++) if(table[i][2]==c)return table[i][0];
    return 255;
}
static int commit(unsigned t) {
    u16 c=name_lookup(edit.initial,edit.medial,t);
    if(!c || edit.length>=6)return 0;
    NAME[edit.length*2]=c>>8;NAME[edit.length*2+1]=c;
    edit.length++;NAME[edit.length*2]=0;
    CUR=edit.length<6?edit.length:5;
    return 1;
}
/* Actions: compatibility jamo U+3131+0..50; delete=51, finish=52.
 * Rejection is atomic with respect to the name and composition. */
int name_action(unsigned action) {
    edit.error=0;
    if(action==51) {
        if(edit.final) {unsigned v=first(tpair,11,edit.final);edit.final=v==255?0:v;}
        else if(edit.medial<21) edit.medial=first(vpair,9,edit.medial);
        else if(edit.initial<19) {
            unsigned i=edit.initial;
            edit.initial=(i==1||i==4||i==8||i==10||i==13)?i-1:255;
        } else if(edit.length) {edit.length--;NAME[edit.length*2]=0;NAME[edit.length*2+1]=0;}
        CUR=edit.length<6?edit.length:5;return 1;
    }
    if(action==52) {
        if(edit.initial<19 || edit.medial<21) {
            if(!commit(edit.final)) goto reject;
            edit.initial=edit.medial=255;edit.final=0;
        }
        if(!edit.length)goto reject;
        PHASE=0x15;return 1;
    }
    if(action>=51 || edit.length>=6)goto reject;
    unsigned l=to_l[action],t=to_t[action];
    if(action>=30) { /* U+314F is first medial. */
        unsigned v=action-30;
        if(edit.medial==255) {edit.medial=v;return 1;}
        if(edit.final) {
            unsigned f=edit.final,remain=first(tpair,11,f), next=t_to_l[f];
            if(remain!=255) {
                for(unsigned i=0;i<11;i++) if(tpair[i][2]==f) {next=t_to_l[tpair[i][1]];break;}
            } else remain=0;
            if(edit.length>=5 || !commit(remain))goto reject;
            edit.initial=next;edit.medial=v;edit.final=0;return 1;
        }
        unsigned c=combine(vpair,9,edit.medial,v);
        if(c!=255) {edit.medial=c;return 1;}
        /* A new vowel alone is kept as unfinished input, never implicit ㅇ. */
        if(edit.length>=5 || !commit(0))goto reject;
        edit.initial=255;edit.medial=v;return 1;
    }
    if(l==255)goto reject; /* Compound finals are composed through real keys. */
    if(edit.initial==255 && edit.medial==255) {edit.initial=l;return 1;}
    if(edit.medial==255) {
        if(edit.initial==l && (l==0||l==3||l==7||l==9||l==12)) {edit.initial=l+1;return 1;}
        goto reject;
    }
    if(edit.initial==255)goto reject;
    if(!edit.final && t) {edit.final=t;return 1;}
    unsigned c=combine(tpair,11,edit.final,t);
    if(c!=255) {edit.final=c;return 1;}
    if(edit.length>=5 || !commit(edit.final))goto reject;
    edit.initial=l;edit.medial=255;edit.final=0;return 1;
reject:
    edit.error=1;return 0;
}
void name_input(void) {
    if(CALL(0x800fd8a0,int(*)(int))(1))return;
    if(*(volatile short*)0x80145e7e!=1 || *(volatile short*)0x80145ea2!=1)return;
    if(!CALL(0x800fa750,int(*)(void))())return;
    unsigned a=53,c=edit.cursor;
    if(KEY(0x20)) a=key(c);
    else if(KEY(0x40)) a=51;
    else if(KEY(0x800)) a=52;
    else if(KEY(4)) {edit.shifted^=1;refresh();SOUND(2);return;}
    else {
        if(KEY(0x8000)) c=c?c-1:25;
        else if(KEY(0x2000)) c=c<25?c+1:0;
        else if(KEY(0x1000)) c=c>=19?c-9:c>=10?c-10:c;
        else if(KEY(0x4000)) c=c<10?(c+10<19?c+10:18):c<19?(c+9<26?c+9:25):c;
        else return;
        edit.cursor=c;SOUND(2);return;
    }
    int ok=name_action(a);SOUND(ok?3:11);refresh();
}
