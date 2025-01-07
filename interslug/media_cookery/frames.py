from dataclasses import dataclass
import time

import numpy as np

@dataclass 
class QueuedFrame:
    """ 
        A frame that's been added from a Bridge to a Queue
    """
    audio_data: np.ndarray[np.int16]
    samples: int
    timestamp_added: float = time.time()

@dataclass
class ReturnFrame(QueuedFrame):
    age_in_sec: float = 0.0
    is_zero_frame: bool = False

def create_zero_frame(samples:int):
    zero_audio_data = np.zeros(samples, dtype=np.int16)
    return ReturnFrame(zero_audio_data, samples, is_zero_frame=True)