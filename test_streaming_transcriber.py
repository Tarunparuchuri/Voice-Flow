import sys
import os
import time
import wave
import array
from PySide6.QtCore import QCoreApplication
from transcriber import StreamingTranscriberManager, format_text

def test_streaming_manager():
    print("--- Running Voice Flow Real-Time Streaming Unit Tests ---")
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    manager = StreamingTranscriberManager()
    
    finished_results = []
    error_results = []

    def on_finished(raw, corrected):
        finished_results.append((raw, corrected))

    def on_error(msg):
        error_results.append(msg)

    manager.finished.connect(on_finished)
    manager.error.connect(on_error)

    # 1. Test Text Formatting & Combining
    raw_chunk1 = "hello world"
    raw_chunk2 = "how are you today"
    
    # Mock whisper available to test the google fallback formatting
    import transcriber
    transcriber._whisper_available = False
    
    combined = format_text(f"{raw_chunk1} {raw_chunk2}")
    print(f"[Streaming Test] Joined formatted text: '{combined}'")
    assert combined == "Hello world how are you today.", f"Unexpected formatting result: {combined}"

    # 2. Test Streaming Transcriber Manager Reset & State
    manager.reset()
    assert manager.expected_final_index is None, "Reset should clear expected final index!"
    assert manager.partial_results == {}, "Reset should clear partial results!"

    print("--- ALL REAL-TIME STREAMING UNIT TESTS PASSED SUCCESSFULLY! ---")

if __name__ == "__main__":
    test_streaming_manager()
