import unittest

from app.email_signatures import sender_name, sign_email


class EmailSignatureTests(unittest.TestCase):
    def test_defaults_to_username_not_recipient(self):
        self.assertEqual(sender_name('Draft an email to Junaid about tomorrow.', 'admin'), 'admin')

    def test_explicit_signature(self):
        self.assertEqual(sender_name('Draft an email. Sign off as Sarah Ali.', 'admin'), 'Sarah Ali')
        self.assertEqual(sender_name('My name is Junaid Jahaly, write to Sarah.', 'admin'), 'Junaid Jahaly')
        self.assertEqual(sender_name('Use Sarah Ali as my signature', 'admin'), 'Sarah Ali')

    def test_replaces_placeholder(self):
        self.assertEqual(sign_email('Dear Junaid,\n\nMeeting tomorrow.\n\nBest regards,\n[Your Name]', 'employee'), 'Dear Junaid,\n\nMeeting tomorrow.\n\nBest regards,\nemployee')

    def test_replaces_inline_placeholder(self):
        result = sign_email('Dear Junaid,  Meeting tomorrow.  Best regards,  [Your Name]', 'admin')
        self.assertTrue(result.endswith('Best regards,\nadmin'))

    def test_explicit_name_replaces_invented_signature(self):
        self.assertEqual(sign_email('Hello,\nPlease attend.\n\nRegards,\nInvented Sender', 'Sarah'), 'Hello,\nPlease attend.\n\nRegards,\nSarah')

    def test_adds_missing_signature_without_changing_body(self):
        self.assertEqual(sign_email('Please attend tomorrow.', 'junaid'), 'Please attend tomorrow.\n\nBest regards,\njunaid')

    def test_signature_is_not_duplicated(self):
        body = 'Hello,\n\nBest regards,\nSarah'
        self.assertEqual(sign_email(sign_email(body, 'Sarah'), 'Sarah'), body)
