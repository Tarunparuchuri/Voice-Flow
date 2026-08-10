import speech_recognition as sr
import os
import time
import difflib
import re
from PySide6.QtCore import QThread, Signal, QObject
from PySide6.QtWidgets import QApplication
import keyboard
import database

def process_voice_commands(text):
    if not text:
        return text
    
    # Split text into tokens (words)
    words = text.split()
    i = 0
    while i < len(words):
        # Check for "sorry sorry" voice command (two occurrences)
        if i >= 2 and i + 1 < len(words) and words[i].lower() == "sorry" and words[i+1].lower() == "sorry":
            # Delete "sorry sorry" and the 3 words before it if available
            del_count = min(3, i)
            del words[i - del_count : i + 2]
            i = max(0, i - del_count)
        # Check for "scratch that" voice command
        elif i >= 2 and i + 1 < len(words) and words[i].lower() == "scratch" and words[i+1].lower() == "that":
            # Delete "scratch that" and the 3 words before it if available
            del_count = min(3, i)
            del words[i - del_count : i + 2]
            i = max(0, i - del_count)
        else:
            i += 1
            
    return " ".join(words)

def format_text(text):
    if not text:
        return text
        
    text = text.strip()
    if not text:
        return text
        
    # 1. Process Voice Commands (like "sorry sorry" and "scratch that")
    text = process_voice_commands(text)
    if not text:
        return text
        
    # 2. Capitalize first letter
    text = text[0].upper() + text[1:]
    
    # 3. Capitalize standalone 'i'
    text = re.sub(r'\bi\b', 'I', text)
    
    # 4. Add punctuation if not present at the end
    if text[-1] not in ('.', '?', '!'):
        # Check if the first word is a question word
        first_word = text.split()[0].lower()
        # strip punctuation from the first word
        first_word = re.sub(r'[^\w]', '', first_word)
        
        question_words = {
            "what", "why", "how", "who", "where", "when", "which",
            "is", "are", "do", "does", "did", "can", "could", "will", "would",
            "should", "was", "were", "am", "has", "have", "had", "shall", "isnt",
            "arent", "dont", "doesnt", "didnt", "cant", "couldnt", "wont", "wouldnt"
        }
        
        if first_word in question_words:
            text += "?"
        else:
            text += "."
            
    return text

class ChunkTranscriberWorker(QThread):
    chunk_finished = Signal(int, str)  # Emits (chunk_index, text)
    chunk_error = Signal(int, str)     # Emits (chunk_index, error_msg)

    def __init__(self, chunk_index, wav_path):
        super().__init__()
        self.chunk_index = chunk_index
        self.wav_path = wav_path

    def run(self):
        if not self.wav_path or not os.path.exists(self.wav_path):
            self.chunk_finished.emit(self.chunk_index, "")
            return

        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(self.wav_path) as source:
                audio_data = recognizer.record(source)

            # Transcribe using Google's Web Speech API
            text = recognizer.recognize_google(audio_data)
            self.chunk_finished.emit(self.chunk_index, text.strip())
        except sr.UnknownValueError:
            self.chunk_finished.emit(self.chunk_index, "")
        except Exception as e:
            self.chunk_error.emit(self.chunk_index, str(e))
        finally:
            try:
                if os.path.exists(self.wav_path):
                    os.remove(self.wav_path)
            except Exception:
                pass


class StreamingTranscriberManager(QObject):
    finished = Signal(str, str)  # Emits (formatted_raw, corrected_text)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.reset()

    def reset(self):
        self.partial_results = {}
        self.expected_final_index = None
        self.workers = []
        self.is_flushing = False

    def add_chunk(self, chunk_index, wav_path):
        worker = ChunkTranscriberWorker(chunk_index, wav_path)
        worker.chunk_finished.connect(self._on_chunk_finished)
        worker.chunk_error.connect(self._on_chunk_error)
        self.workers.append(worker)
        worker.start()

    def set_final_chunk(self, final_index, wav_path):
        self.is_flushing = True
        if wav_path and os.path.exists(wav_path):
            self.expected_final_index = final_index
            self.add_chunk(final_index, wav_path)
        else:
            self.expected_final_index = max(0, final_index - 1) if final_index > 0 else 0
            self._check_completion()

    def _on_chunk_finished(self, chunk_index, text):
        self.partial_results[chunk_index] = text
        self._check_completion()

    def _on_chunk_error(self, chunk_index, error_msg):
        self.partial_results[chunk_index] = ""
        self._check_completion()

    def _check_completion(self):
        if not self.is_flushing or self.expected_final_index is None:
            return

        # Check if all chunks from 0 to expected_final_index are completed
        all_ready = all(i in self.partial_results for i in range(self.expected_final_index + 1))
        if all_ready:
            parts = [self.partial_results[i] for i in range(self.expected_final_index + 1) if self.partial_results.get(i)]
            combined_text = " ".join(parts).strip()
            
            if not combined_text:
                self.error.emit("Speech could not be understood.")
                return

            # Format raw text (voice commands, capitalization, punctuation)
            formatted_raw = format_text(combined_text)
            
            # Apply RL dictionary corrections
            corrected_text = database.apply_dictionary(formatted_raw)
            
            self.finished.emit(formatted_raw, corrected_text)
            self.reset()


class TranscriberThread(QThread):
    finished = Signal(str, str)  # Emits (raw_text, corrected_text)
    error = Signal(str)

    def __init__(self, wav_path):
        super().__init__()
        self.wav_path = wav_path

    def run(self):
        if not os.path.exists(self.wav_path):
            self.error.emit("Audio file not found")
            return

        recognizer = sr.Recognizer()
        try:
            with sr.AudioFile(self.wav_path) as source:
                audio_data = recognizer.record(source)

            # Transcribe using Google's Web Speech API (free, no API key needed)
            raw_text = recognizer.recognize_google(audio_data)
            
            # Format raw text (apply voice commands, capitalize, and punctuate)
            formatted_raw = format_text(raw_text)
            
            # Apply learned corrections from dictionary
            corrected_text = database.apply_dictionary(formatted_raw)
            
            self.finished.emit(formatted_raw, corrected_text)
        except sr.UnknownValueError:
            self.error.emit("Speech could not be understood.")
        except sr.RequestError as e:
            self.error.emit(f"Transcription service error: {e}")
        except Exception as e:
            self.error.emit(f"Transcription error: {str(e)}")
        finally:
            # Clean up temporary audio file
            try:
                if os.path.exists(self.wav_path):
                    os.remove(self.wav_path)
            except Exception:
                pass


class ClipboardCorrectionLearner(QObject):
    correction_learned = Signal(str, str)  # Emits (old_word, new_word)

    def __init__(self):
        super().__init__()
        self.last_pasted_text = None
        self.last_pasted_time = 0
        self.last_history_id = None
        self.is_monitoring = False

    def start_monitoring(self):
        if not self.is_monitoring:
            clipboard = QApplication.clipboard()
            clipboard.dataChanged.connect(self.on_clipboard_changed)
            self.is_monitoring = True

    def register_paste(self, history_id, text):
        self.last_pasted_text = text
        self.last_pasted_time = time.time()
        self.last_history_id = history_id

    def on_clipboard_changed(self):
        if not self.last_pasted_text or not self.last_history_id:
            return

        # Check if correction occurred within 15 seconds
        if time.time() - self.last_pasted_time > 15:
            self.last_pasted_text = None
            self.last_history_id = None
            return

        clipboard = QApplication.clipboard()
        text = clipboard.text().strip()

        if not text or text == self.last_pasted_text:
            return

        # Check similarity to ensure it's a correction of the same text
        # (Must be similar but not identical)
        ratio = difflib.SequenceMatcher(None, self.last_pasted_text.lower(), text.lower()).ratio()
        if 0.6 <= ratio < 1.0:
            # Update history entry with corrected text
            success = database.update_history_entry(self.last_history_id, text)
            if success:
                from rl_engine import RLEngine
                # Find the mappings that were learned / corrected
                mappings = database.learn_corrections(self.last_pasted_text, text)
                if mappings:
                    for raw_phrase, corrected_phrase in mappings:
                        # Process negative penalty for old phrase override and positive reward for new rule
                        RLEngine.process_reward(raw_phrase, 'override')
                        RLEngine.process_reward(corrected_phrase, 'accept')
                        self.correction_learned.emit(raw_phrase, corrected_phrase)
                
                # Reset monitoring state for this paste so we don't repeat-learn
                self.last_pasted_text = None
                self.last_history_id = None
        elif ratio >= 0.98:
            # User accepted past dictation without edits -> reward active terms
            from rl_engine import RLEngine
            words = text.split()
            for w in words:
                clean_w = database.strip_punctuation(w).lower()
                if clean_w:
                    RLEngine.process_reward(clean_w, 'accept')


def paste_text(text):
    """
    Pastes text by copying it to the clipboard (supporting clipboard-based learning)
    and directly typing it into the focused window using keyboard simulation.
    """
    clipboard = QApplication.clipboard()
    
    # Copy text to clipboard so it's ready for clipboard-based correction learning
    clipboard.setText(text)
    
    # Release modifier keys virtually to prevent OS keyboard state conflicts
    for m in ['ctrl', 'win', 'alt', 'shift', 'left ctrl', 'left windows', 'right ctrl', 'right windows']:
        try:
            keyboard.release(m)
        except Exception:
            pass

    # Allow logical keys to release in the OS
    time.sleep(0.15)
    
    # Directly simulate typing the text into the active cursor position
    keyboard.write(text)
