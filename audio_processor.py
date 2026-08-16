import numpy as np

"""
Audio Preprocessing Module for Voice Flow.
Provides AGC (Automatic Gain Control), high-pass filtering, noise gating,
and pre-emphasis to improve speech recognition accuracy.

All processing operates on 16-bit signed PCM mono audio at 16kHz.
"""

# ─── Constants ──────────────────────────────────────────────────────────
SAMPLE_RATE = 16000
TARGET_RMS = 0.12          # Target RMS amplitude for AGC (0.0–1.0 normalized)
AGC_MAX_GAIN = 8.0         # Maximum gain multiplier to prevent amplifying pure noise
AGC_MIN_GAIN = 0.3         # Minimum gain multiplier to prevent clipping loud input
HIGH_PASS_CUTOFF = 80      # Hz — removes rumble from fans, HVAC, desk vibration
NOISE_GATE_THRESHOLD = 0.008  # RMS below this is considered silence/noise
PRE_EMPHASIS_COEFF = 0.97  # Standard pre-emphasis coefficient for speech


def bytes_to_float(pcm_bytes: bytes) -> np.ndarray:
    """Convert 16-bit signed PCM bytes to float64 array normalized to [-1.0, 1.0]."""
    samples = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float64)
    return samples / 32768.0


def float_to_bytes(samples: np.ndarray) -> bytes:
    """Convert float64 array [-1.0, 1.0] back to 16-bit signed PCM bytes."""
    # Clip to prevent overflow
    clipped = np.clip(samples, -1.0, 1.0)
    return (clipped * 32767.0).astype(np.int16).tobytes()


def compute_rms(samples: np.ndarray) -> float:
    """Compute RMS (Root Mean Square) amplitude of a signal."""
    if len(samples) == 0:
        return 0.0
    return float(np.sqrt(np.mean(samples ** 2)))


def apply_agc(samples: np.ndarray, target_rms: float = TARGET_RMS) -> np.ndarray:
    """
    Automatic Gain Control — normalizes audio to a consistent loudness level.
    Quiet microphones get boosted; loud input gets attenuated.
    """
    rms = compute_rms(samples)
    if rms < 1e-6:
        # Signal is essentially silence — don't amplify noise
        return samples

    desired_gain = target_rms / rms
    # Clamp gain to prevent extreme amplification or attenuation
    gain = max(AGC_MIN_GAIN, min(AGC_MAX_GAIN, desired_gain))
    return samples * gain


def apply_high_pass(samples: np.ndarray, cutoff_hz: float = HIGH_PASS_CUTOFF,
                    sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """
    Simple first-order IIR high-pass filter.
    Removes low-frequency rumble (fans, HVAC, desk vibrations) below cutoff_hz.
    """
    if len(samples) < 2:
        return samples

    # First-order high-pass: y[n] = alpha * (y[n-1] + x[n] - x[n-1])
    rc = 1.0 / (2.0 * np.pi * cutoff_hz)
    dt = 1.0 / sample_rate
    alpha = rc / (rc + dt)

    output = np.zeros_like(samples)
    output[0] = samples[0]
    for i in range(1, len(samples)):
        output[i] = alpha * (output[i - 1] + samples[i] - samples[i - 1])

    return output


def apply_noise_gate(samples: np.ndarray, threshold: float = NOISE_GATE_THRESHOLD,
                     frame_size: int = 800) -> np.ndarray:
    """
    Noise gate — suppresses audio segments where RMS is below threshold.
    Operates on frames of `frame_size` samples (~50ms at 16kHz).
    Silent frames are attenuated by 95% instead of hard-zeroed to avoid clicks.
    """
    output = samples.copy()
    num_frames = len(samples) // frame_size

    for i in range(num_frames):
        start = i * frame_size
        end = start + frame_size
        frame = samples[start:end]
        frame_rms = compute_rms(frame)

        if frame_rms < threshold:
            # Attenuate instead of zero to prevent audible clicks
            output[start:end] = frame * 0.05

    # Handle tail samples
    if len(samples) % frame_size > 0:
        tail_start = num_frames * frame_size
        tail = samples[tail_start:]
        if compute_rms(tail) < threshold:
            output[tail_start:] = tail * 0.05

    return output


def apply_pre_emphasis(samples: np.ndarray, coeff: float = PRE_EMPHASIS_COEFF) -> np.ndarray:
    """
    Pre-emphasis filter — boosts high-frequency consonant energy (s, t, k, f, th).
    These sounds are critical for speech recognition but often under-represented
    in raw microphone capture.
    
    y[n] = x[n] - coeff * x[n-1]
    """
    if len(samples) < 2:
        return samples
    
    emphasized = np.zeros_like(samples)
    emphasized[0] = samples[0]
    emphasized[1:] = samples[1:] - coeff * samples[:-1]
    return emphasized


def process_audio(pcm_bytes: bytes, enable_agc: bool = True,
                  enable_high_pass: bool = True, enable_noise_gate: bool = True,
                  enable_pre_emphasis: bool = True) -> bytes:
    """
    Full audio preprocessing pipeline. Takes raw 16-bit PCM bytes and returns
    cleaned PCM bytes ready for speech recognition.
    
    Pipeline order:
    1. High-pass filter (remove rumble)
    2. Noise gate (suppress silence/background noise)
    3. AGC (normalize volume)
    4. Pre-emphasis (boost consonants)
    """
    if not pcm_bytes or len(pcm_bytes) < 4:
        return pcm_bytes

    samples = bytes_to_float(pcm_bytes)

    if enable_high_pass:
        samples = apply_high_pass(samples)

    if enable_noise_gate:
        samples = apply_noise_gate(samples)

    if enable_agc:
        samples = apply_agc(samples)

    if enable_pre_emphasis:
        samples = apply_pre_emphasis(samples)

    return float_to_bytes(samples)
