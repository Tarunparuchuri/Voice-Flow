import os
import wave
import array
import math
import sounddevice as sd
from PySide6.QtCore import QThread, Signal
from config import TEMP_WAV_PATH
import database
from audio_processor import process_audio

class RecorderThread(QThread):
    chunk_recorded = Signal(int, str)         # Emits (chunk_index, chunk_wav_path) live during recording
    final_chunk_recorded = Signal(int, str)   # Emits (final_chunk_index, final_chunk_wav_path) on key release
    recording_finished = Signal(str)          # Emits full recording WAV path for backward compatibility
    recording_error = Signal(str)
    audio_level = Signal(float)               # Emits current audio amplitude for visualizer animations

    # ─── Audio Capture Constants ────────────────────────────────────────
    SAMPLERATE = 16000
    BYTES_PER_SAMPLE = 2

    # ─── VAD-Aware Smart Chunking Constants ─────────────────────────────
    TARGET_CHUNK_SEC = 2.5      # Target chunk duration in seconds
    MIN_CHUNK_SEC = 0.8         # Minimum chunk size (prevent micro-chunks from short pauses)
    MAX_CHUNK_SEC = 3.0         # Maximum chunk size (never exceed this even without silence)
    SILENCE_WINDOW_SEC = 0.5    # ±window around target to search for silence boundary
    SILENCE_THRESHOLD = 0.015   # RMS amplitude below which audio is considered silence
    SILENCE_MIN_FRAMES = 5      # Minimum consecutive silent frames to confirm a silence gap (~50ms each)

    # Derived byte sizes
    TARGET_CHUNK_BYTES = int(SAMPLERATE * BYTES_PER_SAMPLE * TARGET_CHUNK_SEC)
    MIN_CHUNK_BYTES = int(SAMPLERATE * BYTES_PER_SAMPLE * MIN_CHUNK_SEC)
    MAX_CHUNK_BYTES = int(SAMPLERATE * BYTES_PER_SAMPLE * MAX_CHUNK_SEC)
    SEARCH_WINDOW_BYTES = int(SAMPLERATE * BYTES_PER_SAMPLE * SILENCE_WINDOW_SEC)
    FRAME_BYTES = int(SAMPLERATE * BYTES_PER_SAMPLE * 0.01)  # 10ms frame for VAD analysis

    def __init__(self, samplerate=16000, device_index=None):
        super().__init__()
        self.samplerate = samplerate
        self.device_index = device_index  # None = OS default
        self.filename = TEMP_WAV_PATH
        self.is_recording = False
        self.all_audio_chunks = []
        self.current_chunk_bytes = bytearray()
        self.chunk_index = 0

    def _find_silence_boundary(self, data: bytearray) -> int:
        """
        VAD-aware boundary finder.
        Searches within ±SILENCE_WINDOW around TARGET_CHUNK_BYTES for a natural
        silence gap. Returns the byte offset of the best silence boundary,
        or TARGET_CHUNK_BYTES if no silence is found.
        """
        target = self.TARGET_CHUNK_BYTES
        search_start = max(self.MIN_CHUNK_BYTES, target - self.SEARCH_WINDOW_BYTES)
        search_end = min(len(data), target + self.SEARCH_WINDOW_BYTES)

        if search_end <= search_start:
            return min(target, len(data))

        # Scan 10ms frames in the search window for silence
        best_pos = target  # Default: use exact target if no silence found
        best_score = float('inf')
        consecutive_silent = 0

        frame_size = self.FRAME_BYTES
        pos = search_start

        while pos + frame_size <= search_end:
            frame = data[pos:pos + frame_size]
            shorts = array.array('h', bytes(frame))
            if shorts:
                rms = math.sqrt(sum((x / 32768.0) ** 2 for x in shorts) / len(shorts))
            else:
                rms = 0.0

            if rms < self.SILENCE_THRESHOLD:
                consecutive_silent += 1
                if consecutive_silent >= self.SILENCE_MIN_FRAMES:
                    # Found a silence gap — prefer boundaries closer to target
                    distance_from_target = abs(pos - target)
                    if distance_from_target < best_score:
                        best_score = distance_from_target
                        best_pos = pos
            else:
                consecutive_silent = 0

            pos += frame_size

        # Align to sample boundary (2 bytes per sample)
        best_pos = (best_pos // self.BYTES_PER_SAMPLE) * self.BYTES_PER_SAMPLE
        return best_pos

    def run(self):
        self.all_audio_chunks = []
        self.current_chunk_bytes = bytearray()
        self.chunk_index = 0
        self.is_recording = True
        
        # Ensure temp directory exists
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)

        # Resolve device index from settings if not explicitly set
        if self.device_index is None:
            saved_device = database.get_setting("audio_device", "default")
            if saved_device != "default":
                try:
                    self.device_index = int(saved_device)
                except (ValueError, TypeError):
                    self.device_index = None
        
        try:
            def callback(indata, frames, time, status):
                if self.is_recording:
                    data_bytes = bytes(indata)
                    self.all_audio_chunks.append(data_bytes)
                    self.current_chunk_bytes.extend(data_bytes)
                    
                    # Convert byte buffer to array of 16-bit signed shorts for visualizer
                    shorts = array.array('h', data_bytes)
                    if shorts:
                        sum_squares = sum((x / 32768.0) ** 2 for x in shorts)
                        rms = math.sqrt(sum_squares / len(shorts))
                        self.audio_level.emit(rms)

                    # VAD-Aware Smart Chunking:
                    # Once we've accumulated enough audio, find a natural silence boundary
                    if len(self.current_chunk_bytes) >= self.TARGET_CHUNK_BYTES:
                        boundary = self._find_silence_boundary(self.current_chunk_bytes)
                        
                        # Only split if we have enough data and don't exceed max
                        if boundary >= self.MIN_CHUNK_BYTES:
                            chunk_data = bytes(self.current_chunk_bytes[:boundary])
                            self.current_chunk_bytes = self.current_chunk_bytes[boundary:]
                            
                            # Preprocess audio before saving chunk
                            processed_data = process_audio(chunk_data)
                            
                            chunk_path = self._save_chunk_wav(self.chunk_index, processed_data)
                            self.chunk_recorded.emit(self.chunk_index, chunk_path)
                            self.chunk_index += 1

                    # Hard limit: never let buffer exceed MAX_CHUNK_BYTES
                    elif len(self.current_chunk_bytes) >= self.MAX_CHUNK_BYTES:
                        chunk_data = bytes(self.current_chunk_bytes[:self.MAX_CHUNK_BYTES])
                        self.current_chunk_bytes = self.current_chunk_bytes[self.MAX_CHUNK_BYTES:]
                        
                        processed_data = process_audio(chunk_data)
                        
                        chunk_path = self._save_chunk_wav(self.chunk_index, processed_data)
                        self.chunk_recorded.emit(self.chunk_index, chunk_path)
                        self.chunk_index += 1

            # Start raw input stream using selected recording device, 16-bit mono PCM
            stream_kwargs = {
                'samplerate': self.samplerate,
                'channels': 1,
                'dtype': 'int16',
                'callback': callback
            }
            if self.device_index is not None:
                stream_kwargs['device'] = self.device_index

            with sd.RawInputStream(**stream_kwargs):
                while self.is_recording:
                    self.msleep(50)  # Check quickly to respond to stops

            # Process final tail chunk on stop
            if self.current_chunk_bytes:
                final_data = bytes(self.current_chunk_bytes)
                # Only preprocess if we have meaningful audio (>= 100ms)
                if len(final_data) >= self.SAMPLERATE * self.BYTES_PER_SAMPLE // 10:
                    final_data = process_audio(final_data)
                final_path = self._save_chunk_wav(self.chunk_index, final_data)
                self.final_chunk_recorded.emit(self.chunk_index, final_path)
            elif self.chunk_index == 0 and not self.all_audio_chunks:
                self.recording_error.emit("No audio was recorded.")
                return
            else:
                # If chunk flushed exactly on boundary, notify final index
                self.final_chunk_recorded.emit(self.chunk_index, "")

            # Save full concatenated WAV file for backward compatibility & history
            if self.all_audio_chunks:
                all_bytes = b"".join(self.all_audio_chunks)
                with wave.open(self.filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(self.BYTES_PER_SAMPLE)
                    wf.setframerate(self.samplerate)
                    wf.writeframes(all_bytes)
                self.recording_finished.emit(self.filename)
                
        except Exception as e:
            self.recording_error.emit(f"Recording error: {str(e)}")

    def _save_chunk_wav(self, index, byte_data):
        chunk_dir = os.path.join(os.path.dirname(self.filename), "chunks")
        os.makedirs(chunk_dir, exist_ok=True)
        chunk_path = os.path.join(chunk_dir, f"chunk_{index}.wav")
        
        with wave.open(chunk_path, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.BYTES_PER_SAMPLE)
            wf.setframerate(self.samplerate)
            wf.writeframes(byte_data)
            
        return chunk_path

    def stop(self):
        self.is_recording = False
        self.wait()
