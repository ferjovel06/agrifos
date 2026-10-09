import unittest

import bcrypt
from pwdlib.exceptions import UnknownHashError

from app.core.passwords import password_hash


class PasswordCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = "test-password-for-migration"
        cls.legacy_hash = bcrypt.hashpw(
            cls.password.encode(), bcrypt.gensalt(rounds=4, prefix=b"2a")
        ).decode()
        cls.current_hash = password_hash.hash(cls.password)

    def test_new_passwords_use_argon2id_with_distinct_salts(self):
        other_hash = password_hash.hash(self.password)
        self.assertTrue(other_hash.startswith("$argon2id$"))
        self.assertNotEqual(other_hash, self.current_hash)
        self.assertTrue(password_hash.verify(self.password, other_hash))

    def test_valid_supabase_bcrypt_password_can_upgrade_to_argon2(self):
        valid, updated_hash = password_hash.verify_and_update(
            self.password, self.legacy_hash
        )
        self.assertTrue(valid)
        self.assertTrue(updated_hash.startswith("$argon2id$"))
        self.assertTrue(password_hash.verify(self.password, updated_hash))

    def test_wrong_password_is_rejected_without_upgrading_either_format(self):
        for stored_hash in (self.legacy_hash, self.current_hash):
            with self.subTest(format=stored_hash.split("$")[1]):
                self.assertEqual(
                    password_hash.verify_and_update("incorrect", stored_hash),
                    (False, None),
                )

    def test_current_argon2_password_does_not_need_an_upgrade(self):
        self.assertEqual(
            password_hash.verify_and_update(self.password, self.current_hash),
            (True, None),
        )

    def test_unknown_hash_is_not_treated_as_a_valid_password(self):
        with self.assertRaises(UnknownHashError):
            password_hash.verify(self.password, "not-a-password-hash")
