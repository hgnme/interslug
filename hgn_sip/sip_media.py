import pjsua2 as pj
from logging_config import get_logger

port_logger = get_logger("dummy-audio-media-port")

def get_audio_format() -> pj.MediaFormatAudio:
    af = pj.MediaFormatAudio()
    af.type = pj.PJMEDIA_TYPE_AUDIO
    af.clockRate = 8000
    af.channelCount = 1
    af.bitsPerSample = 16
    af.frameTimeUsec = 20000
    return af