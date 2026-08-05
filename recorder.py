import os
import wave
import array
import math
import sounddevice as sd
from PySide6.QtCore import QThread, Signal
from config import TEMP_WAV_PATH

class RecorderThread(QThread):
    recording_finished = Signal(str)
    recording_error = Signal(str)
    audio_level = Signal(float)  # Emits current audio amplitude for visualizer animations

    def __init__(self, samplerate=16000):
        super().__init__()
        self.samplerate = samplerate
        self.filename = TEMP_WAV_PATH
        self.is_recording = False
        self.audio_data = []

    def run(self):
        self.audio_data = []
        self.is_recording = True
        
        # Ensure temp directory exists
        os.makedirs(os.path.dirname(self.filename), exist_ok=True)
        
        try:
            def callback(indata, frames, time, status):
                if self.is_recording:
                    # indata is a bytes buffer when using RawInputStream
                    data_bytes = bytes(indata)
                    self.audio_data.append(data_bytes)
                    
                    # Convert byte buffer to array of 16-bit signed shorts
                    shorts = array.array('h', data_bytes)
                    if shorts:
                        # Calculate volume level (RMS)
                        # Normalize inputs to float in range [-1.0, 1.0] (32768 max amplitude)
                        sum_squares = sum((x / 32768.0) ** 2 for x in shorts)
                        rms = math.sqrt(sum_squares / len(shorts))
                        self.audio_level.emit(rms)

            # Start raw input stream using default recording device, 16-bit mono PCM
            with sd.RawInputStream(samplerate=self.samplerate, channels=1, dtype='int16', callback=callback):
                while self.is_recording:
                    self.msleep(50)  # Check quickly to respond to stops

            if self.audio_data:
                # Concatenate all recorded byte chunks
                all_bytes = b"".join(self.audio_data)
                
                # Save to WAV file using the built-in wave module
                with wave.open(self.filename, 'wb') as wf:
                    wf.setnchannels(1)
                    wf.setsampwidth(2)  # 2 bytes per sample for int16 PCM
                    wf.setframerate(self.samplerate)
                    wf.writeframes(all_bytes)
                    
                self.recording_finished.emit(self.filename)
            else:
                self.recording_error.emit("No audio was recorded.")
        except Exception as e:
            self.recording_error.emit(f"Recording error: {str(e)}")

    def stop(self):
        self.is_recording = False
        # Wait for thread to finish writing file
        self.wait()
