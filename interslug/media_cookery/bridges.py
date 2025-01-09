import fractions
import time
import numpy as np
import pjsua2 as pj
import asyncio

from aiortc import MediaStreamTrack
from av.audio.frame import AudioFrame

from hgn_sip.sip_media import get_audio_format
from logging_config import get_logger
from .queuing import Q_LIST_TYPE_SIP_TO_BROWSER, get_from_queue, add_frame_to_queue, get_queue_by_id, get_queue_list_by_type
from .frames import ReturnFrame, create_zero_frame

get_queue_list_by_type(Q_LIST_TYPE_SIP_TO_BROWSER)
### NEED TO MANAGE QUEUES SOMEWHERE GLOBALLY
### "FRAMEQUEUES"

class SIPAudioBridge(pj.AudioMediaPort):
    """ 
        Audio Bridge to connect to SIP audio stream. This will receive frames from it and add them to the relevant queue for consumption
        INPUT: Frame from direct SIP Audio Stream
        OUTPUT: Frame to SIP->Browser Queue
    """
    def __init__(self, call_id: str):
        super().__init__()
        self.logger = get_logger("sip-audio-bridge")
        self.name: str
        self.call_id = call_id
        self.format: pj.MediaFormatAudio
        self.queue = get_queue_by_id(get_queue_list_by_type(Q_LIST_TYPE_SIP_TO_BROWSER),self.call_id)
        self.total_frames = 0
        self.dropped_frames = 0

    def createPort(self, port_name, audio_format: pj.MediaFormatAudio):
        self.logger.debug(f"Registering port name={port_name}")
        self.port_name = port_name
        self.format = audio_format
        super().createPort(port_name, audio_format)
    def kill(self):
        inf: pj.ConfPortInfo = self.getPortInfo()
        self.__disown__
    
    def onFrameReceived(self, frame: pj.MediaFrame):
        """Forward SIP audio to the browser."""
        audio_data = np.frombuffer(bytes(frame.buf), dtype=np.int16) # Convert PJSIP Buffer object to an NP array of signed 16b ints
        self.total_frames += 1
        try:
            add_frame_to_queue(audio_data, self.queue)
            # self.logger.debug(f"queued frame. total={self.total_frames}, dropped={self.dropped_frames}")
            # self.queue.put_nowait(audio_data) # add to the queue
        except asyncio.QueueFull:
            self.dropped_frames += 1
            pass

class SIPToBrowserAudioTrack(MediaStreamTrack): 
    """
        AudioStreamTrack for use with WebRTC. Takes frames from the queue and outputs them
        Timing must be maintained to maintain realtimeness.
        INPUT: Frames from SIP->Browser Queue
        OUTPUT: Frames to WebRTC
    """
    kind = "audio"
    def __init__(self, stream_queue_id: str):
        super().__init__()
        self.stream_queue_id = stream_queue_id
        self.logger = get_logger(f'dummy-AudioStreamTrack[{self.id}]')
        self.format = get_audio_format()
        self.frametime_sec = self.format.frameTimeUsec * 0.000001
        self.queue = get_queue_by_id(get_queue_list_by_type(Q_LIST_TYPE_SIP_TO_BROWSER),stream_queue_id)
        self.total_frames = 0
        self.zero_frames = 0
        self.malformed_frames = 0
        self.avg_frame_age = 0
        self.total_wait = 0

    def get_stats(self):
        return f"total_frames={self.total_frames}, zero_frames={self.zero_frames}, avg_frame_age={self.avg_frame_age}s, total_wait={self.total_wait}s"
    def update_stats(self, frame: ReturnFrame):
        self.total_frames += 1
        if frame.is_zero_frame:
            self.zero_frames += 1
        self.total_wait += frame.age_in_sec
        self.avg_frame_age = self.total_wait / self.total_frames

        if self.total_frames % 100 == 0:
            self.logger.debug(self.get_stats())

    async def recv(self):
        """
            Receive a frame from the Sip-> Browser Queue (and remove it)
            then return it back after timing and transformation.
        """
        # Expected number of samples in the Frame. This should be the frame length (in seconds) multiplied by the clockrate
        # e.g. 8000hz with 0.02s frametime --> expect 160 samples
        expected_samples = int(self.frametime_sec * self.format.clockRate)
        
        # Timing logic to make sure frame is emitted at correct interval (see frametime_sec)
        if hasattr(self, "_timestamp"):
            self._timestamp += expected_samples
            wait = self._start + (self._timestamp / self.format.clockRate) - time.time()
            await asyncio.sleep(wait)
        else:
            self._start = time.time()
            self._timestamp = 0
            
        # Audio data is retrieved from the queue up to a maximum age, older Frames are dropped.
        # a "zero" frame is returned if Queue ends up empty.
        audio_frame: ReturnFrame = await get_from_queue(self.queue, self.frametime_sec * 5, expected_samples)

        if len(audio_frame.audio_data) != expected_samples:
            self.logger.error({"e": "Length of frame not matching expected sample count", "audio_data": audio_frame.audio_data, "expected_samples": expected_samples})
            self.malformed_frames += 1
            audio_frame = create_zero_frame(expected_samples)
            
        self.update_stats(audio_frame)
        frame = AudioFrame(format="s16", layout="mono", samples=expected_samples)
        for p in frame.planes:
            p.update(audio_frame.audio_data)
        frame.pts = self._timestamp # Presentation Timestamp in time_base units
        frame.sample_rate = self.format.clockRate 
        frame.time_base = fractions.Fraction(1, self.format.clockRate) # Time base is 1/samplerathed of a second. e.g. 1/8000 = 0.000125s
        # self.logger.debug(f"received frame. total={self.total_frames}, zero_frames={self.zero_frames}")
        return frame
