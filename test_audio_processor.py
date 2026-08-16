import numpy as np
import array
from audio_processor import process_audio

def test_audio_processor():
    print("Testing audio_processor...")
    
    # Create some dummy audio data (1 second of 440Hz sine wave + noise)
    sr = 16000
    t = np.linspace(0, 1, sr, False)
    sine = np.sin(2 * np.pi * 440 * t) * 10000  # amplitude 10000
    noise = np.random.normal(0, 500, sr)  # noise amplitude ~500
    
    audio = sine + noise
    # Convert to 16-bit PCM bytes
    audio_pcm = np.int16(audio).tobytes()
    
    print(f"Original audio bytes length: {len(audio_pcm)}")
    
    # Process audio
    processed_pcm = process_audio(audio_pcm)
    
    print(f"Processed audio bytes length: {len(processed_pcm)}")
    
    if len(processed_pcm) == len(audio_pcm):
        print("SUCCESS: Lengths match.")
    else:
        print("ERROR: Lengths do not match!")
        
    print("Finished audio_processor test.")

if __name__ == '__main__':
    test_audio_processor()
