#!/usr/bin/env python3
"""MCS-48 (8050) emulator for the Mettler ME-47455 firmware, with just enough hardware to run it.

  - CPU core: full 8048/8049/8050 instruction set, 256-byte RAM, 4 KB ROM with MB0/MB1, stack in RAM, INT interrupt.
  - EAROM (MCM2801): the ROM's read/write routines (0x85D / 0x83A) are intercepted and served from a 32-byte image.
  - Counter LSI (IC6): MOVX reads return a 12-bit count per integration cycle (value supplied by the caller).
  - Display: read back from RAM 0xCD-0xD4 (what the interrupt routine scans out), decoded as 7-segment.

Timing assumptions: one interrupt every 333 machine cycles and 2.5 us per cycle. The board's crystal is 4.915 MHz
(3.05 us per cycle), so millisecond figures are nominal; use them to compare variants, not as absolute times.

Usage: from emu48 import Scale     (python3 emu48.py ROM.bin EEPROM.bin runs a short smoke test)
"""
import sys

SEG = {0x3F: '0', 0x06: '1', 0x5B: '2', 0x4F: '3', 0x66: '4', 0x6D: '5', 0x7D: '6', 0x07: '7', 0x7F: '8', 0x6F: '9',
       0x00: ' ', 0x40: '-', 0x79: 'E', 0x50: 'r', 0x5C: 'o', 0x54: 'n', 0x39: 'C', 0x77: 'A', 0x38: 'L',
       0x3E: 'U', 0x10: 'i', 0x78: 't', 0x71: 'F', 0x76: 'H', 0x73: 'P'}

CYC2 = set()  # opcodes that take two machine cycles
for _o in range(256):
    pass


def two_cycle(op):
    if op in (0x03, 0x13, 0x23, 0x43, 0x53, 0xD3, 0x83, 0x93, 0x02, 0x08, 0x09, 0x0A, 0x39, 0x3A, 0x88, 0x89, 0x8A,
              0x98, 0x99, 0x9A, 0xA3, 0xB3, 0xE3, 0xB0, 0xB1, 0x80, 0x81, 0x90, 0x91):
        return True
    if op & 0x0F in (0x0C, 0x0D, 0x0E, 0x0F) and op in range(0x0C, 0xA0) and (op & 0xF0) in (0x00, 0x30, 0x80, 0x90):
        return True
    if op & 0xF8 == 0xB8 or op & 0xF8 == 0xE8:
        return True
    if op & 0x1F in (0x04, 0x14, 0x12) or op in (0x16, 0x26, 0x36, 0x46, 0x56, 0x76, 0x86, 0x96, 0xB6, 0xC6, 0xE6, 0xF6):
        return True
    return False


class Halt(Exception):
    pass


class MCS48:
    def __init__(self, rom):
        self.rom = bytearray(rom) + bytearray(0x1000 - len(rom))
        self.ram = bytearray(256)
        self.pc = 0
        self.a = 0
        self.c = self.ac = self.f0 = self.f1 = 0
        self.bs = 0
        self.sp = 0
        self.mb = 0
        self.t = 0
        self.ie = 0
        self.tcnti = 0
        self.p1 = 0xFF
        self.p2 = 0xFF
        self.bus = 0xFF
        self.ext_p1 = 0xFF
        self.ext_p2 = 0xFF
        self.t0 = 1
        self.t1 = 0
        self.cycles = 0
        self.in_isr = 0
        self.saved_mb = []
        self.int_pending = 0
        self.hooks = {}
        self.icount = 0
        self.movx_read = lambda cpu, addr: 0xFF
        self.movx_write = lambda cpu, addr, val: None

    # ---- helpers
    def R(self, n):
        return self.ram[(24 if self.bs else 0) + n]

    def setR(self, n, v):
        self.ram[(24 if self.bs else 0) + n] = v & 0xFF

    def psw(self):
        return (self.c << 7) | (self.ac << 6) | (self.f0 << 5) | (self.bs << 4) | 0x08 | self.sp

    def set_psw(self, v):
        self.c, self.ac, self.f0, self.bs, self.sp = (v >> 7) & 1, (v >> 6) & 1, (v >> 5) & 1, (v >> 4) & 1, v & 7

    def push(self, pc):
        sp = self.sp
        self.ram[8 + 2 * sp] = pc & 0xFF
        self.ram[9 + 2 * sp] = ((pc >> 8) & 0x0F) | (self.psw() & 0xF0)
        self.sp = (sp + 1) & 7

    def pop(self, restore_psw=False):
        self.sp = (self.sp - 1) & 7
        lo = self.ram[8 + 2 * self.sp]
        hi = self.ram[9 + 2 * self.sp]
        pc = lo | ((hi & 0x0F) << 8)
        if restore_psw:
            self.c, self.ac, self.f0, self.bs = (hi >> 7) & 1, (hi >> 6) & 1, (hi >> 5) & 1, (hi >> 4) & 1
        return pc

    def add(self, x, cin=0):
        r = self.a + x + cin
        self.ac = 1 if ((self.a & 0xF) + (x & 0xF) + cin) > 0xF else 0
        self.c = 1 if r > 0xFF else 0
        self.a = r & 0xFF

    def ind(self, i):
        return self.ram[self.R(i)]

    def setind(self, i, v):
        self.ram[self.R(i)] = v & 0xFF

    # ---- execution
    def step(self):
        if self.int_pending and self.ie and not self.in_isr:
            self.int_pending = 0
            self.push(self.pc)
            self.saved_mb.append(self.mb)
            self.mb = 0
            self.in_isr = 1
            self.pc = 3
            self.cycles += 2
            return
        pc = self.pc
        if pc in self.hooks:
            if self.hooks[pc](self):
                return
        rom = self.rom
        op = rom[pc]
        n = op & 7
        d = rom[(pc + 1) & 0xFFF]
        ln = 1
        self.icount += 1
        cyc = 2 if two_cycle(op) else 1

        def cj(cond):
            nonlocal ln
            ln = 2
            if cond:
                self.pc = ((pc + 1) & 0xF00) | d
                return True
            return False

        npc = None
        hi = op >> 4
        # --- jumps/calls (xxx00100, xxx10100)
        if op & 0x1F == 0x04:
            npc = (self.mb << 11) | ((op & 0xE0) << 3) | d
            self.pc = npc; self.cycles += 2; return
        if op & 0x1F == 0x14:
            self.push(pc + 2)
            self.pc = (self.mb << 11) | ((op & 0xE0) << 3) | d
            self.cycles += 2; return
        if op & 0x1F == 0x12:                              # JBb
            if cj((self.a >> (op >> 5)) & 1): self.cycles += 2; return
            self.pc = pc + 2; self.cycles += 2; return
        if op & 0xF8 == 0xE8:                               # DJNZ Rn
            v = (self.R(n) - 1) & 0xFF
            self.setR(n, v)
            if cj(v != 0): self.cycles += 2; return
            self.pc = pc + 2; self.cycles += 2; return
        jc = {0x16: lambda: self.tf, 0x26: lambda: not self.t0, 0x36: lambda: self.t0, 0x46: lambda: not self.t1,
              0x56: lambda: self.t1, 0x76: lambda: self.f1, 0x86: lambda: self.int_pending or self.int_low,
              0x96: lambda: self.a != 0, 0xB6: lambda: self.f0, 0xC6: lambda: self.a == 0,
              0xE6: lambda: not self.c, 0xF6: lambda: self.c} if hasattr(self, 'int_low') else None
        if jc is None:
            self.int_low = 0
            jc = {0x16: lambda: 0, 0x26: lambda: not self.t0, 0x36: lambda: self.t0, 0x46: lambda: not self.t1,
                  0x56: lambda: self.t1, 0x76: lambda: self.f1, 0x86: lambda: self.int_pending,
                  0x96: lambda: self.a != 0, 0xB6: lambda: self.f0, 0xC6: lambda: self.a == 0,
                  0xE6: lambda: not self.c, 0xF6: lambda: self.c}
            self._jc = jc
        jc = self._jc
        if op in jc:
            if cj(jc[op]()): self.cycles += 2; return
            self.pc = pc + 2; self.cycles += 2; return

        a = self.a
        if op == 0x00: pass
        elif op == 0x02: self.bus = a
        elif op == 0x03: ln = 2; self.add(d)
        elif op == 0x05: self.ie = 1
        elif op == 0x07: self.a = (a - 1) & 0xFF
        elif op == 0x08: self.a = self.bus
        elif op == 0x09: self.a = self.p1 & self.ext_p1
        elif op == 0x0A: self.a = self.p2 & self.ext_p2
        elif 0x0C <= op <= 0x0F: self.a = 0x0F
        elif op in (0x10, 0x11): self.setind(op & 1, self.ind(op & 1) + 1)
        elif op == 0x13: ln = 2; self.add(d, self.c)
        elif op == 0x15: self.ie = 0
        elif op == 0x17: self.a = (a + 1) & 0xFF
        elif 0x18 <= op <= 0x1F: self.setR(n, self.R(n) + 1)
        elif op in (0x20, 0x21):
            i = op & 1; t = self.ind(i); self.setind(i, a); self.a = t
        elif op == 0x23: ln = 2; self.a = d
        elif op == 0x25: self.tcnti = 1
        elif op == 0x27: self.a = 0
        elif 0x28 <= op <= 0x2F:
            t = self.R(n); self.setR(n, a); self.a = t
        elif op in (0x30, 0x31):
            i = op & 1; t = self.ind(i); self.setind(i, (t & 0xF0) | (a & 0x0F)); self.a = (a & 0xF0) | (t & 0x0F)
        elif op == 0x35: self.tcnti = 0
        elif op == 0x37: self.a = (~a) & 0xFF
        elif op == 0x39: self.p1 = a
        elif op == 0x3A: self.p2 = a
        elif 0x3C <= op <= 0x3F: pass
        elif op in (0x40, 0x41): self.a = a | self.ind(op & 1)
        elif op == 0x42: self.a = self.t
        elif op == 0x43: ln = 2; self.a = a | d
        elif op == 0x45: pass
        elif op == 0x47: self.a = ((a << 4) | (a >> 4)) & 0xFF
        elif 0x48 <= op <= 0x4F: self.a = a | self.R(n)
        elif op in (0x50, 0x51): self.a = a & self.ind(op & 1)
        elif op == 0x53: ln = 2; self.a = a & d
        elif op == 0x55: pass
        elif op == 0x57:
            if (a & 0xF) > 9 or self.ac: a += 6
            if a > 0xFF: self.c = 1; a &= 0xFF
            if (a >> 4) > 9 or self.c: a += 0x60; self.c = 1 if a > 0xFF else self.c; a &= 0xFF
            self.a = a
        elif 0x58 <= op <= 0x5F: self.a = a & self.R(n)
        elif op in (0x60, 0x61): self.add(self.ind(op & 1))
        elif op == 0x62: self.t = a
        elif op == 0x65: pass
        elif op == 0x67: c = a & 1; self.a = (a >> 1) | (self.c << 7); self.c = c
        elif 0x68 <= op <= 0x6F: self.add(self.R(n))
        elif op in (0x70, 0x71): self.add(self.ind(op & 1), self.c)
        elif op == 0x75: pass
        elif op == 0x77: self.a = ((a >> 1) | (a << 7)) & 0xFF
        elif 0x78 <= op <= 0x7F: self.add(self.R(n), self.c)
        elif op in (0x80, 0x81): self.a = self.movx_read(self, self.R(op & 1)) & 0xFF
        elif op == 0x83: self.pc = self.pop(); self.cycles += 2; return
        elif op == 0x85: self.f0 = 0
        elif op == 0x88: ln = 2; self.bus &= 0xFF; self.bus |= d
        elif op == 0x89: ln = 2; self.p1 |= d
        elif op == 0x8A: ln = 2; self.p2 |= d
        elif 0x8C <= op <= 0x8F: pass
        elif op in (0x90, 0x91): self.movx_write(self, self.R(op & 1), a)
        elif op == 0x93:
            self.pc = self.pop(True); self.in_isr = 0
            if self.saved_mb: self.mb = self.saved_mb.pop()
            self.cycles += 2; return
        elif op == 0x95: self.f0 ^= 1
        elif op == 0x97: self.c = 0
        elif op == 0x98: ln = 2; self.bus &= d
        elif op == 0x99: ln = 2; self.p1 &= d
        elif op == 0x9A: ln = 2; self.p2 &= d
        elif 0x9C <= op <= 0x9F: pass
        elif op in (0xA0, 0xA1): self.setind(op & 1, a)
        elif op == 0xA3: self.a = rom[((pc + 1) & 0xF00) | a]
        elif op == 0xA5: self.f1 = 0
        elif op == 0xA7: self.c ^= 1
        elif 0xA8 <= op <= 0xAF: self.setR(n, a)
        elif op in (0xB0, 0xB1): ln = 2; self.setind(op & 1, d)
        elif op == 0xB3:
            self.pc = (pc & 0xF00) | rom[((pc + 1) & 0xF00) | a]; self.cycles += 2; return
        elif op == 0xB5: self.f1 ^= 1
        elif 0xB8 <= op <= 0xBF: ln = 2; self.setR(n, d)
        elif op == 0xC5: self.bs = 0
        elif op == 0xC7: self.a = self.psw()
        elif 0xC8 <= op <= 0xCF: self.setR(n, self.R(n) - 1)
        elif op in (0xD0, 0xD1): self.a = a ^ self.ind(op & 1)
        elif op == 0xD3: ln = 2; self.a = a ^ d
        elif op == 0xD5: self.bs = 1
        elif op == 0xD7: self.set_psw(a)
        elif 0xD8 <= op <= 0xDF: self.a = a ^ self.R(n)
        elif op == 0xE3: self.a = rom[0x300 | a]
        elif op == 0xE5: self.mb = 0
        elif op == 0xE7: self.a = ((a << 1) | (a >> 7)) & 0xFF
        elif op in (0xF0, 0xF1): self.a = self.ind(op & 1)
        elif op == 0xF5: self.mb = 1
        elif op == 0xF7: c = a >> 7; self.a = ((a << 1) | self.c) & 0xFF; self.c = c
        elif 0xF8 <= op <= 0xFF: self.a = self.R(n)
        else:
            raise Halt(f"illegal opcode {op:02X} at {pc:03X}")
        self.pc = pc + ln
        self.cycles += 2 if ln == 2 else cyc


def swap_pairs(d):
    d = bytearray(d)
    for i in range(0, len(d) - 1, 2):
        d[i], d[i + 1] = d[i + 1], d[i]
    return bytes(d)


class Scale:
    """ME-47455 firmware + simulated counter LSI / EAROM / display.

    The EEPROM image is taken in DUMP (file) order. The firmware reads each 16-bit word low byte first, so RAM byte
    0x20+i holds file byte i^1; the swap is done here (file_order=False takes an image already in RAM order)."""
    INT_PERIOD = 333     # machine cycles between integration-cycle interrupts (~833 us at 2.5 us/cycle)

    def __init__(self, rom_path, earom_image, count_fn=None, file_order=True):
        with open(rom_path, 'rb') as f:
            self.cpu = MCS48(f.read())
        self.earom = bytearray(swap_pairs(earom_image) if file_order else earom_image)
        self.writes = []
        self.count_fn = count_fn or (lambda cycle: 2048)
        self.latched = 2048
        self.next_int = self.INT_PERIOD
        self.log = []
        c = self.cpu
        c.hooks[0x85D] = self.h_earom_read
        c.hooks[0x83A] = self.h_earom_write
        c.movx_read = self.lsi_read
        c.movx_write = lambda cpu, addr, v: None
        c.t0 = 1
        c.t1 = 0

    # EAROM: R0 = RAM pointer, R1 = word address, R2 = word count
    def h_earom_read(self, cpu):
        r0, r1, r2 = cpu.R(0), cpu.R(1), cpu.R(2)
        for w in range(r2):
            for b in range(2):
                cpu.ram[(r0 + 2 * w + b) & 0xFF] = self.earom[((r1 + w) * 2 + b) % 32]
        cpu.setR(0, r0 + 2 * r2); cpu.setR(1, r1 + r2); cpu.setR(2, 0)
        cpu.pc = cpu.pop(); return True

    def h_earom_write(self, cpu):
        r0, r1, r2 = cpu.R(0), cpu.R(1), cpu.R(2)
        for w in range(r2):
            for b in range(2):
                self.earom[((r1 + w) * 2 + b) % 32] = cpu.ram[(r0 + 2 * w + b) & 0xFF]
        self.writes.append((cpu.cycles, r1, r2))
        cpu.setR(0, r0 + 2 * r2); cpu.setR(1, r1 + r2); cpu.setR(2, 0)
        cpu.ie = 1
        cpu.pc = cpu.pop(); return True

    # counter LSI: P1 bits 5,4 select the register
    def lsi_read(self, cpu, addr):
        sel = (cpu.p1 >> 4) & 3
        if sel == 3:
            self.latched = int(self.count_fn(cpu.cycles)) & 0xFFF
            return 0xFF
        if sel == 0:
            return self.latched & 0xFF
        if sel == 2:
            return (self.latched >> 8) & 0x0F
        return 0xFF

    def image(self):
        """The EEPROM as it would be dumped (file order)."""
        return swap_pairs(self.earom)

    def power_on(self, standby_cycles=3_000_000, run_cycles=8_000_000):
        """Normal power-on without a key held: the balance goes to standby (display OFF); the ON event (bit 7 of RAM 0x81,
        which ends the standby loop at 0xEAB) then starts weighing."""
        self.cpu.ext_p1 = 0xFF
        self.run_cycles(standby_cycles)
        self.cpu.ram[0x81] |= 0x80
        self.run_cycles(run_cycles)

    def run_cycles(self, n, trace=None):
        c = self.cpu
        end = c.cycles + n
        while c.cycles < end:
            if c.cycles >= self.next_int:
                c.int_pending = 1
                self.next_int += self.INT_PERIOD
            c.step()
            if trace: trace(self)

    def display_raw(self):
        return bytes(self.cpu.ram[0xCD:0xD5])

    def display(self):
        out = ''
        for b in self.display_raw():
            ch = SEG.get(b & 0x7F, '?')
            out += ch + ('.' if b & 0x80 else '')
        return out


if __name__ == '__main__':
    rom = sys.argv[1]
    with open(sys.argv[2], 'rb') as f:
        img = f.read()
    s = Scale(rom, img)
    s.cpu.ext_p1 = 0xFE
    for i in range(20):
        s.run_cycles(20000)
        print(f"cycle {s.cpu.cycles:8d} pc={s.cpu.pc:03X} icount={s.cpu.icount:8d} display=[{s.display()}] raw={s.display_raw().hex()} ram8E={s.cpu.ram[0x8E]:02X}")
