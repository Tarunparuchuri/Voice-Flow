import os
import re
import time
import wave
import difflib
import threading
from PySide6.QtCore import QThread, Signal, QObject
from PySide6.QtWidgets import QApplication
import keyboard
import database
import config

# ─── Whisper Engine (Singleton) ──────────────────────────────────────────
_whisper_model = None
_whisper_lock = threading.Lock()
_whisper_available = False


def _load_whisper_model():
    """Lazily load the faster-whisper model. Thread-safe singleton."""
    global _whisper_model, _whisper_available
    with _whisper_lock:
        if _whisper_model is not None:
            return _whisper_model
        try:
            from faster_whisper import WhisperModel
            model_size = database.get_setting("whisper_model", config.WHISPER_MODEL)
            print(f"[Whisper] Loading model '{model_size}' on {config.WHISPER_DEVICE} ({config.WHISPER_COMPUTE_TYPE})...")
            _whisper_model = WhisperModel(
                model_size,
                device=config.WHISPER_DEVICE,
                compute_type=config.WHISPER_COMPUTE_TYPE
            )
            _whisper_available = True
            print(f"[Whisper] Model '{model_size}' loaded successfully.")
            return _whisper_model
        except Exception as e:
            print(f"[Whisper] Failed to load model: {e}. Falling back to Google Web Speech API.")
            _whisper_available = False
            return None


def reload_whisper_model():
    """Force-reload the Whisper model (e.g., after user changes model size in Settings)."""
    global _whisper_model, _whisper_available
    with _whisper_lock:
        _whisper_model = None
        _whisper_available = False
    return _load_whisper_model()


def transcribe_with_whisper(wav_path, initial_prompt=None):
    """
    Transcribe a WAV file using faster-whisper.
    Returns transcribed text string, or None if Whisper is unavailable.
    """
    model = _load_whisper_model()
    if model is None:
        return None

    try:
        segments, info = model.transcribe(
            wav_path,
            beam_size=config.WHISPER_BEAM_SIZE,
            language=config.WHISPER_LANGUAGE,
            vad_filter=config.WHISPER_VAD_FILTER,
            initial_prompt=initial_prompt,
            word_timestamps=False,
            condition_on_previous_text=True
        )
        text = " ".join(segment.text.strip() for segment in segments).strip()
        return text if text else None
    except Exception as e:
        print(f"[Whisper] Transcription error: {e}")
        return None


def transcribe_with_google(wav_path):
    """
    Fallback transcription using Google Web Speech API.
    Returns transcribed text string, or raises on error.
    """
    import speech_recognition as sr
    recognizer = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio_data = recognizer.record(source)
    return recognizer.recognize_google(audio_data)


# ─── Voice Commands ─────────────────────────────────────────────────────

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
    """
    Post-process transcribed text. When Whisper is active, it already provides
    proper punctuation and capitalization, so this is a lightweight pass-through
    that only handles voice commands and the standalone 'I' rule.
    For Google fallback, applies full formatting.
    """
    if not text:
        return text
        
    text = text.strip()
    if not text:
        return text
        
    # 1. Process Voice Commands (like "sorry sorry" and "scratch that")
    text = process_voice_commands(text)
    if not text:
        return text

    # 2. Capitalize standalone 'i' -> 'I'
    text = re.sub(r'\bi\b', 'I', text)

    if _whisper_available:
        # Whisper provides native punctuation and capitalization.
        # Just ensure first letter is capitalized (Whisper occasionally lowercases it).
        text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()
        return text

    # ── Google fallback: full formatting ──
    # Capitalize first letter
    text = text[0].upper() + text[1:] if len(text) > 1 else text.upper()
    
    # Add punctuation if not present at the end
    if text[-1] not in ('.', '?', '!'):
        first_word = text.split()[0].lower()
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


# ─── Chunk Transcriber Worker ────────────────────────────────────────────

class ChunkTranscriberWorker(QThread):
    chunk_finished = Signal(int, str)  # Emits (chunk_index, text)
    chunk_error = Signal(int, str)     # Emits (chunk_index, error_msg)

    def __init__(self, chunk_index, wav_path, initial_prompt=None):
        super().__init__()
        self.chunk_index = chunk_index
        self.wav_path = wav_path
        self.initial_prompt = initial_prompt

    def run(self):
        if not self.wav_path or not os.path.exists(self.wav_path):
            self.chunk_finished.emit(self.chunk_index, "")
            return

        try:
            # Try Whisper first (primary engine)
            text = transcribe_with_whisper(self.wav_path, initial_prompt=self.initial_prompt)
            
            if text is None:
                # Fallback to Google Web Speech API
                try:
                    text = transcribe_with_google(self.wav_path)
                except Exception:
                    text = ""

            self.chunk_finished.emit(self.chunk_index, text.strip() if text else "")
        except Exception as e:
            self.chunk_error.emit(self.chunk_index, str(e))
        finally:
            try:
                if os.path.exists(self.wav_path):
                    os.remove(self.wav_path)
            except Exception:
                pass


# ─── Streaming Transcriber Manager ──────────────────────────────────────

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
        self._last_prompt = None  # Context passing: text from previous chunk

    def add_chunk(self, chunk_index, wav_path):
        """Dispatch a background transcription worker for this audio chunk."""
        # Pass the last completed chunk's text as initial_prompt for context
        worker = ChunkTranscriberWorker(chunk_index, wav_path, initial_prompt=self._last_prompt)
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
        # Update context for next chunk (streaming context passing)
        if text:
            self._last_prompt = text
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


# ─── Legacy Single-File Transcriber (backward compatibility) ─────────────

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

        try:
            # Try Whisper first
            raw_text = transcribe_with_whisper(self.wav_path)
            
            if raw_text is None:
                # Fallback to Google Web Speech API
                raw_text = transcribe_with_google(self.wav_path)
            
            # Format raw text
            formatted_raw = format_text(raw_text)
            
            # Apply learned corrections from dictionary
            corrected_text = database.apply_dictionary(formatted_raw)
            
            self.finished.emit(formatted_raw, corrected_text)
        except Exception as e:
            error_msg = str(e)
            if "UnknownValueError" in error_msg or "could not understand" in error_msg.lower():
                self.error.emit("Speech could not be understood.")
            elif "RequestError" in error_msg:
                self.error.emit(f"Transcription service error: {e}")
            else:
                self.error.emit(f"Transcription error: {error_msg}")
        finally:
            try:
                if os.path.exists(self.wav_path):
                    os.remove(self.wav_path)
            except Exception:
                pass


# ─── Clipboard Correction Learner ────────────────────────────────────────

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


# ─── Text Injection — Atomic Clipboard Paste ─────────────────────────────

def paste_text(text):
    """
    Pastes text into the active window using atomic clipboard paste (Ctrl+V).
    
    Instead of slow character-by-character keyboard.write(), this:
    1. Saves the user's current clipboard content
    2. Sets clipboard to the transcribed text
    3. Simulates Ctrl+V for instant paste
    4. Restores the original clipboard content after a delay
    """
    clipboard = QApplication.clipboard()
    
    # Save original clipboard content for restoration
    original_clipboard = clipboard.text()
    
    # Set transcribed text to clipboard
    clipboard.setText(text)
    
    # Release modifier keys virtually to prevent OS keyboard state conflicts
    for m in ['ctrl', 'win', 'alt', 'shift', 'left ctrl', 'left windows', 'right ctrl', 'right windows']:
        try:
            keyboard.release(m)
        except Exception:
            pass

    # Allow logical keys to release in the OS
    time.sleep(0.15)
    
    # Simulate Ctrl+V for instant atomic paste
    keyboard.send('ctrl+v')
    
    # Wait for paste to complete, then restore original clipboard
    time.sleep(0.25)
    try:
        clipboard.setText(original_clipboard)
    except Exception:
        pass
