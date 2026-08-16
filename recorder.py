import os
import wave
import array
import math
import numpy as np
import time
import sounddevice as sd
from PySide6.QtCore import QThread, Signal
from config import TEMP_WAV_PATH
import database

class RecorderThread(QThread):
    audio_update = Signal(object)         # Emits full np.ndarray live during recording
    audio_finished = Signal(object)       # Emits final np.ndarray on key release
    recording_finished = Signal(str)      # Emits full recording WAV path for backward compatibility
    recording_error = Signal(str)
    audio_level = Signal(float)           # Emits current audio amplitude for visualizer animations

    SAMPLERATE = 16000
    BYTES_PER_SAMPLE = 2
    UPDATE_INTERVAL_SEC = 0.5             # Emit transcription update every 0.5s

    def __init__(self, samplerate=16000, device_index=None):
        super().__init__()
        self.samplerate = samplerate
        self.device_index = device_index  # None = OS default
        self.filename = TEMP_WAV_PATH
        self.is_recording = False
        self.all_audio_bytes = bytearray()
        self.last_update_time = 0

    def run(self):
        self.all_audio_bytes = bytearray()
        self.is_recording = True
        self.last_update_time = time.time()
        
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
            def callback(indata, frames, time_info, status):
                if self.is_recording:
                    data_bytes = bytes(indata)
                    self.all_audio_bytes.extend(data_bytes)
                    
                    # Convert byte buffer to array of 16-bit signed shorts for visualizer
                    shorts = array.array('h', data_bytes)
                    if shorts:
                        sum_squares = sum((x / 32768.0) ** 2 for x in shorts)
                        rms = math.sqrt(sum_squares / len(shorts))
                        self.audio_level.emit(rms)

                    # Emit streaming update every UPDATE_INTERVAL_SEC
                    current_time = time.time()
                    if current_time - self.last_update_time >= self.UPDATE_INTERVAL_SEC:
                        if len(self.all_audio_bytes) > 0:
                            # Convert to float32 [-1.0, 1.0] for whisper
                            audio_np = np.frombuffer(bytes(self.all_audio_bytes), dtype=np.int16).astype(np.float32) / 32768.0
                            self.audio_update.emit(audio_np)
                        self.last_update_time = current_time

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

            # Process final tail on stop
            if self.all_audio_bytes:
                audio_np = np.frombuffer(bytes(self.all_audio_bytes), dtype=np.int16).astype(np.float32) / 32768.0
                self.audio_finished.emit(audio_np)
                
                # Save full concatenated WAV file for backward compatibility & history
                with wave.open(self.filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(self.BYTES_PER_SAMPLE)
                    wf.setframerate(self.samplerate)
                    wf.writeframes(bytes(self.all_audio_bytes))
                self.recording_finished.emit(self.filename)
            else:
                self.recording_error.emit("No audio was recorded.")
                return
                
        except Exception as e:
            self.recording_error.emit(f"Recording error: {str(e)}")

    def stop(self):
        self.is_recording = False
        self.wait()
