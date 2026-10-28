import os
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import pe_editor as ed                              # noqa: E402
import pe_eeprom as pe                              # noqa: E402

EX = os.path.join(ROOT, 'examples')


def rd(name):
    with open(os.path.join(EX, name), 'rb') as f:
        return f.read()


def opened(name='pe3000_B_french_original.bin'):
    e = ed.Editor()
    e.open(os.path.join(EX, name))
    return e


class AutoRepair(unittest.TestCase):
    def test_editing_the_template_keeps_the_image_valid(self):
        e = opened()
        e.set_byte(22, 0x38)
        self.assertTrue(e.is_valid())
        e.set_byte(25, 0x01)
        e.set_byte(1, 0x00)
        # the three edits made on the real PE3000 end at the image that worked, with byte 30 = 9F
        self.assertEqual((e.data[1], e.data[22], e.data[25], e.data[30]), (0x00, 0x38, 0x01, 0x9F))
        self.assertTrue(e.is_valid())

    def test_record_edit_fixes_only_its_checksum_byte(self):
        e = opened()
        before = e.data
        e.set_record(1, 0x123456)
        self.assertTrue(e.is_valid())
        self.assertEqual(e.data[8:], before[8:])                   # nothing outside record 1 moved

    def test_deliberate_checksum_edit_is_not_undone(self):
        e = opened()
        e.set_byte(6, 0x00)
        self.assertEqual(e.data[6], 0x00)
        self.assertFalse(e.is_valid())

    def test_auto_repair_can_be_switched_off(self):
        e = opened()
        e.auto_repair = False
        e.set_byte(22, 0x38)
        self.assertFalse(e.is_valid())
        self.assertTrue(e.repair())
        self.assertTrue(e.is_valid())


class Fields(unittest.TestCase):
    def test_test_mode_and_deltadisplay(self):
        e = opened('pe6000_own.bin')
        o = e.data
        self.assertFalse(e.deltadisplay_option_off())
        e.deltadisplay_off()
        self.assertTrue(e.deltadisplay_option_off())
        self.assertEqual((e.data[29], e.data[31]), (0xF0, 0x7F))
        self.assertEqual(e.data[20], o[20])                        # decimal-point code untouched
        e.deltadisplay_on()
        self.assertFalse(e.deltadisplay_option_off())
        e.set_test_mode(True)
        self.assertEqual(e.data[21] & 0x40, 0x40)
        e.set_test_mode(False)
        self.assertEqual(e.data[21] & 0x40, 0)
        self.assertTrue(e.is_valid())

    def test_threshold_band_row_fields_do_not_disturb_each_other(self):
        e = opened()
        e.set_threshold_idx(3)
        e.set_band_idx(2)
        e.set_filter_row(1)
        e.set_test_mode(True)
        self.assertEqual(e.data[21], 3 | (2 << 2) | (1 << 4) | 0x40)
        self.assertTrue(e.is_valid())

    def test_code(self):
        e = opened()
        e.set_code(4)
        self.assertEqual(e.data[20] & 7, 4)
        self.assertTrue(e.is_valid())

    def test_x_limit_window(self):
        e = opened()
        e.set_x(0x123456)
        self.assertEqual(e.fields()['x'], 0x123456)
        e.set_limit(0x2345)
        self.assertEqual(e.fields()['limit'], 0x2345)
        e.set_window_half(False)
        self.assertEqual(e.data[26] & 0x80, 0)
        e.set_window_half(True)
        self.assertEqual(e.data[26] & 0x80, 0x80)
        self.assertTrue(e.is_valid())

    def test_value_range(self):
        e = opened()
        with self.assertRaises(ValueError):
            e.set_byte(3, 256)
        with self.assertRaises(ValueError):
            e.set_record(1, 0x1000000)


class History(unittest.TestCase):
    def test_undo_returns_to_the_start(self):
        e = opened()
        e.set_byte(22, 1)
        e.set_record(2, 5)
        e.set_test_mode(True)
        while e.undo():
            pass
        self.assertEqual(e.data, e.orig)

    def test_revert(self):
        e = opened()
        e.set_byte(22, 1)
        e.revert()
        self.assertEqual(e.data, e.orig)
        self.assertTrue(e.undo())                                  # revert itself can be undone
        self.assertEqual(e.data[22], 1)


class Templates(unittest.TestCase):
    def test_apply_template_keeps_the_records(self):
        e = opened()
        rec = e.data[4:12]
        e.apply_template('PE6000')
        self.assertEqual(e.data[4:12], rec)
        self.assertEqual(e.data[20:30], pe.template_bytes(next(t for t in pe.load_templates() if t['name'] == 'PE6000'))[1][:10])
        self.assertTrue(e.is_valid())

    def test_build_new(self):
        e = ed.Editor()
        donor = rd('pe6000_own.bin')
        e.build_new('PE6000', donor)
        self.assertTrue(e.is_valid())
        self.assertEqual(e.data[2:], donor[2:])
        e.build_new('PE16')
        self.assertTrue(e.is_valid())
        self.assertEqual(e.fields()['record1'], 0)


class Files(unittest.TestCase):
    def test_save_keeps_the_word_order_it_was_opened_in(self):
        d = rd('pe6000_own.bin')
        with tempfile.TemporaryDirectory() as td:
            src, dst = os.path.join(td, 's.bin'), os.path.join(td, 'o.bin')
            with open(src, 'wb') as f:
                f.write(pe.swap_pairs(d))
            pe.SWAP_MODE = 'auto'
            e = ed.Editor()
            e.open(src)
            self.assertTrue(e.swapped)
            e.set_byte(1, 0x55)
            e.save(dst)
            with open(dst, 'rb') as f:
                out = f.read()
            self.assertEqual(pe.swap_pairs(out)[1], 0x55)
            self.assertEqual(out[0], 0x55)                         # byte 1 sits where a swapped file keeps it

    def test_words_roundtrip_and_validation(self):
        e = opened('pe16_forum.bin')
        w = e.to_words()
        e.from_words(w)
        self.assertEqual(e.to_words(), w)
        with self.assertRaises(ValueError):
            e.from_words('0001 0080')

    def test_compare(self):
        e = opened()
        e.set_other(os.path.join(EX, 'pe3000_A_faulty-chip.bin'))
        a, b = rd('pe3000_B_french_original.bin'), rd('pe3000_A_faulty-chip.bin')
        self.assertEqual(e.differing_from_other(), [i for i in range(32) if a[i] != b[i]])
        self.assertTrue({22, 25, 30} <= set(e.differing_from_other()))
        e.set_other(None)
        self.assertEqual(e.differing_from_other(), [])


if __name__ == '__main__':
    unittest.main()
