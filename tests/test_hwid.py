import unittest

from engine.hwid import generate_hwid, is_private_hwid


class PrivateClientIdTests(unittest.TestCase):
    def test_generated_id_is_opaque_and_has_no_machine_data(self):
        first = generate_hwid()
        second = generate_hwid()

        self.assertTrue(is_private_hwid(first))
        self.assertTrue(is_private_hwid(second))
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 37)
        self.assertRegex(first, r"^[a-zA-Z0-9=-]{10,64}$")

    def test_hardware_style_values_are_not_new_private_ids(self):
        self.assertFalse(is_private_hwid("9b47e984-5327-458b-a14a-8ce0b7c89aa7"))
        self.assertFalse(is_private_hwid("00:11:22:33:44:55"))


if __name__ == "__main__":
    unittest.main()
