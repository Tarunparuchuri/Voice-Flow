import os
import wave
import numpy as np
from transcriber import transcribe_with_whisper, _load_whisper_model

def test_whisper_engine():
    print("Testing whisper engine...")
    
    # Pre-load the model to verify it loads
    print("Loading model...")
    model = _load_whisper_model()
    if model is None:
        print("ERROR: Whisper model failed to load!")
        return
        
    print("Model loaded successfully.")
    
    # Create a 1-second silence WAV file
    test_wav = "test_silence.wav"
    sr = 16000
    audio_pcm = np.zeros(sr, dtype=np.int16).tobytes()
    with wave.open(test_wav, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(audio_pcm)
        
    print("Transcribing silence...")
    text = transcribe_with_whisper(test_wav)
    print(f"Transcription result: '{text}'")
    
    if os.path.exists(test_wav):
        os.remove(test_wav)
        
    print("Whisper engine test finished.")

if __name__ == '__main__':
    test_whisper_engine()
