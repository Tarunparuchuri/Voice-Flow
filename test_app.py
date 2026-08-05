import os
import unittest
import database
import config
from recorder import RecorderThread

class TestVoiceFlow(unittest.TestCase):
    def setUp(self):
        # Use a separate test database
        self.original_db_path = config.DB_PATH
        config.DB_PATH = os.path.join(config.APP_DIR, "test_voice_flow.db")
        database.DB_PATH = config.DB_PATH
        
        # Clean up database if it exists
        if os.path.exists(config.DB_PATH):
            try:
                os.remove(config.DB_PATH)
            except Exception:
                pass
                
        database.init_db()

    def tearDown(self):
        # Clean up database
        if os.path.exists(config.DB_PATH):
            try:
                os.remove(config.DB_PATH)
            except Exception:
                pass
        # Restore db path
        config.DB_PATH = self.original_db_path
        database.DB_PATH = self.original_db_path

    def test_database_settings(self):
        database.save_setting("test_key", "test_val")
        self.assertEqual(database.get_setting("test_key"), "test_val")
        
        database.save_setting("bool_true", "True")
        self.assertTrue(database.get_setting("bool_true"))
        
        database.save_setting("num", "42")
        self.assertEqual(database.get_setting("num"), 42)

    def test_history_crud(self):
        entry_id = database.add_history_entry("hello wisper", "hello wisper")
        self.assertIsNotNone(entry_id)
        
        history = database.get_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["raw_text"], "hello wisper")
        self.assertEqual(history[0]["corrected_text"], "hello wisper")
        
        # Update entry with correction
        success = database.update_history_entry(entry_id, "hello whisper")
        self.assertTrue(success)
        
        # Check that correction was saved
        history = database.get_history()
        self.assertEqual(history[0]["corrected_text"], "hello whisper")
        
        # Check that correction and all words were saved in the dictionary!
        dictionary = database.get_dictionary()
        self.assertEqual(len(dictionary), 3)
        phrases = [d["phrase"] for d in dictionary]
        self.assertIn("wisper", phrases)
        self.assertIn("hello", phrases)
        self.assertIn("whisper", phrases)
        
        # Test delete single history entry
        del_success = database.delete_history_entry(entry_id)
        self.assertTrue(del_success)
        history = database.get_history()
        self.assertEqual(len(history), 0)

    def test_reinforcement_learning_diff(self):
        # Learn from direct input
        raw = "this is a voice flow app clone and it uses wisper"
        corrected = "this is a Voice Flow app clone and it uses Whisper"
        
        learned = database.learn_corrections(raw, corrected)
        # Expected mappings extracted:
        # "voice flow" -> "Voice Flow"
        # "wisper" -> "Whisper"
        
        learned_phrases = [m[0] for m in learned]
        self.assertIn("wisper", learned_phrases)
        self.assertIn("voice flow", learned_phrases)
        
        # Verify dictionary applies rules to new text
        test_text = "I love wisper and voice flow"
        result = database.apply_dictionary(test_text)
        self.assertEqual(result, "I love Whisper and Voice Flow")

    def test_recording_module(self):
        # Simple test to verify RecorderThread class structure and basic variables
        recorder = RecorderThread()
        self.assertEqual(recorder.samplerate, 16000)
        self.assertFalse(recorder.is_recording)

    def test_voice_commands_and_formatting(self):
        from transcriber import format_text
        
        # Test sorry sorry command
        self.assertEqual(format_text("what is 1 + 1 sorry sorry 2 + 2"), "What is 2 + 2?")
        
        # Test scratch that command
        self.assertEqual(format_text("hello world scratch that how are you"), "How are you?")
        
        # Test capitalization of i and standard periods
        self.assertEqual(format_text("today i am going to voice flow"), "Today I am going to voice flow.")

if __name__ == "__main__":
    unittest.main()
