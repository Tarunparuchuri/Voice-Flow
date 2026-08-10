import os
import wave
import array
import math
import sounddevice as sd
from PySide6.QtCore import QThread, Signal
from config import TEMP_WAV_PATH

class RecorderThread(QThread):
    chunk_recorded = Signal(int, str)         # Emits (chunk_index, chunk_wav_path) live during recording
    final_chunk_recorded = Signal(int, str)   # Emits (final_chunk_index, final_chunk_wav_path) on key release
    recording_finished = Signal(str)          # Emits full recording WAV path for backward compatibility
    recording_error = Signal(str)
    audio_level = Signal(float)               # Emits current audio amplitude for visualizer animations

    CHUNK_DURATION_SEC = 2.5
    SAMPLERATE = 16000
    BYTES_PER_SAMPLE = 2
    CHUNK_BYTE_SIZE = int(SAMPLERATE * BYTES_PER_SAMPLE * CHUNK_DURATION_SEC)  # 80,000 bytes per chunk

    def __init__(self, samplerate=16000):
        super().__init__()
        self.samplerate = samplerate
        self.filename = TEMP_WAV_PATH
        self.is_recording = False
        self.all_audio_chunks = []
        self.current_chunk_bytes = bytearray()
        self.chunk_index = 0

    def run(self):
        self.all_audio_chunks = []
        self.current_chunk_bytes = bytearray()
        self.chunk_index = 0
        self.is_recording = True
        
        # Ensure temp directory exists
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)
        
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

                    # Check if accumulated chunk reached target duration
                    if len(self.current_chunk_bytes) >= self.CHUNK_BYTE_SIZE:
                        chunk_data = bytes(self.current_chunk_bytes[:self.CHUNK_BYTE_SIZE])
                        self.current_chunk_bytes = self.current_chunk_bytes[self.CHUNK_BYTE_SIZE:]
                        
                        chunk_path = self._save_chunk_wav(self.chunk_index, chunk_data)
                        self.chunk_recorded.emit(self.chunk_index, chunk_path)
                        self.chunk_index += 1

            # Start raw input stream using default recording device, 16-bit mono PCM
            with sd.RawInputStream(samplerate=self.samplerate, channels=1, dtype='int16', callback=callback):
                while self.is_recording:
                    self.msleep(50)  # Check quickly to respond to stops

            # Process final tail chunk on stop
            if self.current_chunk_bytes:
                final_data = bytes(self.current_chunk_bytes)
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
