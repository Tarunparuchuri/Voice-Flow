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


def transcribe_with_whisper(audio_data, initial_prompt=None):
    """
    Transcribe audio using faster-whisper.
    audio_data can be a wav file path OR a 1D np.ndarray float32.
    Returns transcribed text string, or None if Whisper is unavailable.
    """
    model = _load_whisper_model()
    if model is None:
        return None

    try:
        segments, info = model.transcribe(
            audio_data,
            beam_size=config.WHISPER_BEAM_SIZE,
            language=config.WHISPER_LANGUAGE,
            vad_filter=config.WHISPER_VAD_FILTER,
            vad_parameters=dict(min_silence_duration_ms=500) if config.WHISPER_VAD_FILTER else None,
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


# ─── Live Streaming Transcriber Worker ────────────────────────────────────

class LiveTranscriptionWorker(QThread):
    partial_result = Signal(str)         # Emits raw text as it updates live
    final_result = Signal(str, str)      # Emits (formatted_raw, corrected_text)
    error = Signal(str)

    def __init__(self):
        super().__init__()
        self.audio_buffer = None
        self.is_running = False
        self.is_final = False
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)
        
    def update_audio(self, audio_np, is_final=False):
        """Called from the main thread when recorder emits new audio numpy array."""
        with self.condition:
            self.audio_buffer = audio_np
            if is_final:
                self.is_final = True
            self.condition.notify()

    def run(self):
        self.is_running = True
        self.is_final = False
        self.audio_buffer = None
        
        while self.is_running:
            with self.condition:
                # Wait for audio to be available or to be stopped
                while self.audio_buffer is None and self.is_running and not self.is_final:
                    self.condition.wait()
                
                if not self.is_running:
                    break
                    
                current_audio = self.audio_buffer
                is_final_run = self.is_final
                self.audio_buffer = None # Clear so we wait for next update

            if current_audio is not None and len(current_audio) > 0:
                try:
                    # Run inference on the full context accumulated so far
                    text = transcribe_with_whisper(current_audio)
                    
                    if text:
                        if is_final_run:
                            formatted_raw = format_text(text)
                            corrected_text = database.apply_dictionary(formatted_raw)
                            self.final_result.emit(formatted_raw, corrected_text)
                            break
                        else:
                            self.partial_result.emit(text)
                    elif is_final_run:
                        # Fallback to Google API if whisper failed to output anything on final
                        try:
                            # We can't pass np.ndarray directly to Google fallback. 
                            # If needed, we could encode back to wav, but Google fallback is obsolete.
                            # Just emit error if Whisper is totally blank.
                            self.error.emit("Speech could not be understood.")
                        except Exception:
                            self.error.emit("Speech could not be understood.")
                        break
                except Exception as e:
                    if is_final_run:
                        self.error.emit(str(e))
                        break
            elif is_final_run:
                self.error.emit("Speech could not be understood.")
                break

    def stop(self):
        with self.condition:
            self.is_running = False
            self.condition.notify()
        self.wait()


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
    Leaves the transcribed text in the clipboard so the user can paste it again.
    """
    clipboard = QApplication.clipboard()
    
    # Set transcribed text to clipboard
    clipboard.setText(text)
    
    # Process events to ensure Qt flushes the clipboard to the OS
    QApplication.processEvents()
    
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
