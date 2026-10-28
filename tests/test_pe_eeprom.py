import glob
import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import pe_eeprom as pe                                  # noqa: E402

EX = os.path.join(ROOT, 'examples')


def ex(name):
    with open(os.path.join(EX, name), 'rb') as f:
        return f.read()


def rd(path):
    with open(path, 'rb') as f:
        return f.read()


class Rules(unittest.TestCase):
    def test_all_examples_are_valid(self):
        files = glob.glob(os.path.join(EX, '*.bin'))
        self.assertGreaterEqual(len(files), 9)
        for f in files:
            with self.subTest(f=os.path.basename(f)):
                self.assertTrue(pe.valid(rd(f)))

    def test_word_swap_cannot_be_seen_in_the_checksums(self):
        for fn in glob.glob(os.path.join(EX, '*.bin')):
            self.assertTrue(pe.valid(pe.swap_pairs(rd(fn))))

    def test_word_swapped_file_is_detected_by_its_header(self):
        d = ex('pe6000_own.bin')
        with tempfile.NamedTemporaryFile(suffix='.bin', delete=False) as t:
            t.write(pe.swap_pairs(d))
        try:
            pe.SWAP_MODE = 'auto'
            data, swapped = pe.load(t.name)
            self.assertTrue(swapped)
            self.assertEqual(data, d)
        finally:
            os.unlink(t.name)


class HardwareCase(unittest.TestCase):
    """The edit that was made on a real PE3000 (French chip -> PE3000 template values)."""

    def test_partial_edit_is_invalid_and_repair_matches_the_working_image(self):
        d = bytearray(ex('pe3000_B_french_original.bin'))
        d[1], d[22], d[25] = 0x00, 0x38, 0x01
        self.assertFalse(pe.valid(bytes(d)))                       # this is the image the balance rejected
        self.assertEqual(sum(d[20:32]) & 255, 0x38)                # template sum, must be 0xAB
        fixed = pe.repair(bytes(d))
        self.assertTrue(pe.valid(fixed))
        self.assertEqual(fixed[30], 0x9F)                          # = byte 30 of the real PE3000 template
        working = bytearray(ex('pe3000_B_french_original.bin'))
        working[1], working[22], working[25], working[30] = 0x00, 0x38, 0x01, 0x9F
        self.assertEqual(fixed, bytes(working))                    # byte-for-byte the image that worked


class Editing(unittest.TestCase):
    def test_set_record_roundtrip(self):
        d = bytearray(ex('pe6000_own.bin'))
        pe.set_record(d, 1, 0x123456)
        self.assertEqual(pe.get24(d, 4), 0x123456)
        self.assertEqual(sum(d[4:8]) & 255, pe.GOOD)

    def test_repair_adjust_31(self):
        d = bytearray(ex('pe6000_own.bin'))
        d[22] ^= 0x10
        fixed = pe.repair(bytes(d), adjust=31)
        self.assertTrue(pe.valid(fixed))
        self.assertEqual(fixed[30], d[30])
        self.assertNotEqual(fixed[31], d[31])

    def test_cli_set_deltadisplay_and_test_mode(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, 'o.bin')
            pe.main(['set', os.path.join(EX, 'pe16_forum.bin'), out, '--deltadisplay', 'off', '--test-mode', 'on'])
            n = rd(out)
            self.assertTrue(pe.valid(n))
            self.assertEqual(n[21] & 7, 5)
            self.assertTrue(n[20] & 0x40)
            with self.assertRaises(SystemExit):                    # 'on' needs an explicit resolution code
                pe.main(['set', out, out, '--deltadisplay', 'on'])
            pe.main(['set', out, out, '--deltadisplay', 'on', '--code', '1', '--test-mode', 'off'])
            n = rd(out)
            self.assertEqual((n[21] & 7, n[20] & 0x40), (1, 0))
            self.assertTrue(pe.valid(n))


class Build(unittest.TestCase):
    def test_build_from_template_with_donor_reproduces_the_dump(self):
        cases = {'PE3000-A': 'pe3000_A_faulty-chip.bin', 'PE3000-B': 'pe3000_B_french_original.bin',
                 'PE6000': 'pe6000_own.bin', 'PE16': 'pe16_forum.bin', 'PE360': 'pe360_forum.bin',
                 'PE3600': 'pe3600_forum.bin', 'PE1600': 'pe1600_own.bin'}
        for name, fn in cases.items():
            with self.subTest(template=name), tempfile.TemporaryDirectory() as td:
                out = os.path.join(td, 'b.bin')
                pe.main(['build', '--template', name, '--out', out, '--donor', os.path.join(EX, fn)])
                built, orig = rd(out), ex(fn)
                self.assertTrue(pe.valid(built))
                self.assertEqual(built[2:], orig[2:])              # everything but the scratch bytes 0-1

    def test_build_with_zero_records_is_valid(self):
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, 'z.bin')
            pe.main(['build', '--template', 'PE6000', '--out', out])
            self.assertTrue(pe.valid(rd(out)))


class Words(unittest.TestCase):
    def test_forum_words_match_the_example(self):
        words = '0001 0080 30DF 8517 543D 0317 0000 0000 0000 0000 0421 E200 D004 138A FFF8 BD7F'
        with tempfile.TemporaryDirectory() as td:
            out = os.path.join(td, 'w.bin')
            pe.main(['from-words', words, '--out', out])
            self.assertEqual(rd(out), ex('pe16_forum.bin'))


if __name__ == '__main__':
    unittest.main()
