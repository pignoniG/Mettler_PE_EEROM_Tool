#!/usr/bin/env python3
"""Recursive-descent MCS-48 (8048/8049/8050) disassembler with MB0/MB1 tracking."""
import sys
from collections import defaultdict

ROM = open(sys.argv[1], 'rb').read()
OUT = sys.argv[2] if len(sys.argv) > 2 else None
N = len(ROM)

# opcode -> (text, length, flow)   text uses {d} for data byte, {a} for address operand
T = {}
def op(code, text, ln=1, flow=None):
    assert code not in T, hex(code)
    T[code] = (text, ln, flow)

op(0x00, "NOP"); op(0x02, "OUTL BUS,A"); op(0x03, "ADD A,#{d}", 2); op(0x05, "EN I")
op(0x07, "DEC A"); op(0x08, "INS A,BUS"); op(0x09, "IN A,P1"); op(0x0A, "IN A,P2")
for i, p in enumerate((4, 5, 6, 7)):
    op(0x0C + i, f"MOVD A,P{p}"); op(0x3C + i, f"MOVD P{p},A")
    op(0x8C + i, f"ORLD P{p},A"); op(0x9C + i, f"ANLD P{p},A")
op(0x10, "INC @R0"); op(0x11, "INC @R1"); op(0x13, "ADDC A,#{d}", 2); op(0x15, "DIS I")
op(0x16, "JTF {a}", 2, 'cjmp'); op(0x17, "INC A")
for r in range(8):
    op(0x18 + r, f"INC R{r}"); op(0x28 + r, f"XCH A,R{r}"); op(0x48 + r, f"ORL A,R{r}")
    op(0x58 + r, f"ANL A,R{r}"); op(0x68 + r, f"ADD A,R{r}"); op(0x78 + r, f"ADDC A,R{r}")
    op(0xA8 + r, f"MOV R{r},A"); op(0xB8 + r, f"MOV R{r},#{{d}}", 2); op(0xC8 + r, f"DEC R{r}")
    op(0xD8 + r, f"XRL A,R{r}"); op(0xE8 + r, f"DJNZ R{r},{{a}}", 2, 'cjmp'); op(0xF8 + r, f"MOV A,R{r}")
op(0x20, "XCH A,@R0"); op(0x21, "XCH A,@R1"); op(0x23, "MOV A,#{d}", 2); op(0x25, "EN TCNTI")
op(0x26, "JNT0 {a}", 2, 'cjmp'); op(0x27, "CLR A"); op(0x30, "XCHD A,@R0"); op(0x31, "XCHD A,@R1")
op(0x35, "DIS TCNTI"); op(0x36, "JT0 {a}", 2, 'cjmp'); op(0x37, "CPL A"); op(0x39, "OUTL P1,A")
op(0x3A, "OUTL P2,A"); op(0x40, "ORL A,@R0"); op(0x41, "ORL A,@R1"); op(0x42, "MOV A,T")
op(0x43, "ORL A,#{d}", 2); op(0x45, "STRT CNT"); op(0x46, "JNT1 {a}", 2, 'cjmp'); op(0x47, "SWAP A")
op(0x50, "ANL A,@R0"); op(0x51, "ANL A,@R1"); op(0x53, "ANL A,#{d}", 2); op(0x55, "STRT T")
op(0x56, "JT1 {a}", 2, 'cjmp'); op(0x57, "DA A"); op(0x60, "ADD A,@R0"); op(0x61, "ADD A,@R1")
op(0x62, "MOV T,A"); op(0x65, "STOP TCNT"); op(0x67, "RRC A"); op(0x70, "ADDC A,@R0")
op(0x71, "ADDC A,@R1"); op(0x75, "ENT0 CLK"); op(0x76, "JF1 {a}", 2, 'cjmp'); op(0x77, "RR A")
op(0x80, "MOVX A,@R0"); op(0x81, "MOVX A,@R1"); op(0x83, "RET", 1, 'ret'); op(0x85, "CLR F0")
op(0x86, "JNI {a}", 2, 'cjmp'); op(0x88, "ORL BUS,#{d}", 2); op(0x89, "ORL P1,#{d}", 2)
op(0x8A, "ORL P2,#{d}", 2); op(0x90, "MOVX @R0,A"); op(0x91, "MOVX @R1,A"); op(0x93, "RETR", 1, 'ret')
op(0x95, "CPL F0"); op(0x96, "JNZ {a}", 2, 'cjmp'); op(0x97, "CLR C"); op(0x98, "ANL BUS,#{d}", 2)
op(0x99, "ANL P1,#{d}", 2); op(0x9A, "ANL P2,#{d}", 2); op(0xA0, "MOV @R0,A"); op(0xA1, "MOV @R1,A")
op(0xA3, "MOVP A,@A"); op(0xA5, "CLR F1"); op(0xA7, "CPL C"); op(0xB0, "MOV @R0,#{d}", 2)
op(0xB1, "MOV @R1,#{d}", 2); op(0xB3, "JMPP @A", 1, 'jmpp'); op(0xB5, "CPL F1"); op(0xB6, "JF0 {a}", 2, 'cjmp')
op(0xC5, "SEL RB0"); op(0xC6, "JZ {a}", 2, 'cjmp'); op(0xC7, "MOV A,PSW"); op(0xD0, "XRL A,@R0")
op(0xD1, "XRL A,@R1"); op(0xD3, "XRL A,#{d}", 2); op(0xD5, "SEL RB1"); op(0xD7, "MOV PSW,A")
op(0xE3, "MOVP3 A,@A"); op(0xE5, "SEL MB0"); op(0xE6, "JNC {a}", 2, 'cjmp'); op(0xE7, "RL A")
op(0xF0, "MOV A,@R0"); op(0xF1, "MOV A,@R1"); op(0xF5, "SEL MB1"); op(0xF6, "JC {a}", 2, 'cjmp'); op(0xF7, "RLC A")
for p in range(8):
    op(0x04 | (p << 5), f"JMP {{a}}", 2, 'jmp')
    op(0x14 | (p << 5), f"CALL {{a}}", 2, 'call')
    op(0x12 | (p << 5), f"JB{p} {{a}}", 2, 'cjmp')

def target(opc, pc, operand, mb, flow):
    if flow in ('jmp', 'call'):
        return (mb << 11) | (((opc >> 5) & 7) << 8) | operand
    return ((pc + 1) & 0xF00) | operand        # conditional: page of the operand byte

code = {}                 # addr -> (mnemonic text, length, flow, target, mb)
labels = defaultdict(set)  # addr -> set of kinds
seen = set()
work = [(0, 0), (3, 0), (7, 0)]
for a, k in ((0, 'RESET'), (3, 'EXT_INT'), (7, 'TIMER_INT')):
    labels[a].add(k)
anomalies = []

while work:
    pc, mb = work.pop()
    while True:
        if pc >= N or (pc, mb) in seen:
            break
        seen.add((pc, mb))
        opc = ROM[pc]
        if opc not in T:
            anomalies.append((pc, f"illegal opcode {opc:02X}"))
            break
        text, ln, flow = T[opc]
        d = ROM[pc + 1] if ln == 2 and pc + 1 < N else 0
        tgt = None
        if flow in ('jmp', 'call', 'cjmp'):
            tgt = target(opc, pc, d, mb, flow)
        if opc == 0xE5: mb = 0
        if opc == 0xF5: mb = 1
        shown = text.replace("{d}", f"{d:02X}h").replace("{a}", f"L{tgt:03X}" if tgt is not None else "")
        if pc not in code or True:
            code[pc] = (shown, ln, flow, tgt, mb, bytes(ROM[pc:pc + ln]))
        if tgt is not None:
            labels[tgt].add('SUB' if flow == 'call' else 'L')
            work.append((tgt, mb))
        if flow in ('jmp', 'ret', 'jmpp'):
            break
        pc += ln

# coverage
covered = bytearray(N)
for a, (_, ln, *_rest) in code.items():
    for i in range(ln):
        covered[a + i] = 1
# detect jump targets that land inside another instruction
starts = set(code)
for a, (s, ln, flow, tgt, mb, raw) in code.items():
    if tgt is not None and tgt not in starts and tgt < N and covered[tgt]:
        anomalies.append((a, f"target {tgt:03X} lands inside an instruction"))

lines = []
addr = 0
while addr < N:
    if addr in code:
        s, ln, flow, tgt, mb, raw = code[addr]
        lab = ''
        if addr in labels:
            kinds = labels[addr]
            nm = ("SUB_%03X" % addr) if 'SUB' in kinds else ("L%03X" % addr)
            extra = [k for k in kinds if k not in ('SUB', 'L')]
            lines.append(f"{nm}:" + (f"    ; {', '.join(extra)}" if extra else ''))
        # rewrite label operand name for call targets
        if tgt is not None and 'SUB' in labels.get(tgt, ()):
            s = s.replace(f"L{tgt:03X}", f"SUB_{tgt:03X}")
        lines.append(f"  {addr:03X}  {raw.hex(' '):<6}  {s}")
        addr += ln
    else:
        start = addr
        while addr < N and addr not in code and not (addr < N and covered[addr]):
            addr += 1
        chunk = ROM[start:addr]
        if all(b == 0xFF for b in chunk):
            lines.append(f"  {start:03X}  ; {len(chunk)} bytes of FF padding up to {addr-1:03X}")
        else:
            lines.append(f"; ---- unreached bytes {start:03X}-{addr-1:03X} ({len(chunk)} bytes): data or code not reached from vectors ----")
            for o in range(0, len(chunk), 16):
                row = chunk[o:o + 16]
                asc = ''.join(chr(b) if 32 <= b < 127 else '.' for b in row)
                lines.append(f"  {start+o:03X}  db {' '.join(f'{b:02X}' for b in row)}   ; {asc}")

total_cov = sum(covered)
hdr = [f"; MCS-48 disassembly of {sys.argv[1]}  ({N} bytes)",
       f"; reached by recursive descent: {total_cov} bytes ({100*total_cov//N}%), {len(code)} instructions",
       f"; anomalies: {len(anomalies)}", ";"]
text = "\n".join(hdr + lines) + "\n"
if OUT:
    open(OUT, 'w').write(text)
print("\n".join(hdr))
for a, m in anomalies[:25]:
    print(f";   {a:03X}: {m}")
