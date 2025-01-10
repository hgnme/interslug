from dataclasses import dataclass
from typing import TYPE_CHECKING
from logging_config import get_logger

if TYPE_CHECKING:
    from hgn_sip.sip_call import SIPCall
    from interslug.media_cookery.bridges import SIPAudioBridge, SIPToBrowserAudioTrack
    import pjsua2 as pj

@dataclass
class SIPCallInfo():
    accIdInt: int = None
    callIdString: str = None
    callIdInt: int = None
    callStateInt: int = None
    callStateString: str = None
    localUri: str = None
    localContact: str = None
    remoteUri: str = None
    remoteContact: str = None
    remAudioCount: int = None
    remVideoCount: int = None
    connectedDuration: float = None
    totalDuration: float = None

def get_sip_call_info(sip_call: 'SIPCall'):
    call_info: pj.CallInfo = sip_call.getInfo()
    connected_duration_obj: pj.TimeVal = call_info.connectDuration
    connected_duration = float(connected_duration_obj.sec + (connected_duration_obj.msec / 1000))

    total_duration_obj: pj.TimeVal = call_info.totalDuration
    total_duration = float(total_duration_obj.sec + (total_duration_obj.msec / 1000))

    info = SIPCallInfo(
        accIdInt = call_info.accId,
        callIdString = call_info.callIdString,
        callIdInt = call_info.id,
        callStateInt = call_info.state,
        callStateString = call_info.stateText,
        localUri = call_info.localUri,
        localContact = call_info.localContact,
        remoteUri = call_info.remoteUri,
        remoteContact = call_info.remoteContact,
        remAudioCount = call_info.remAudioCount,
        remVideoCount = call_info.remVideoCount,
        connectedDuration = connected_duration,
        totalDuration = total_duration
    )
    return info

class CallState:
    """
        Represents a current SIPCall.
        Contains:
        - The SIPCall
        - The AudioPort which is receiving its incoming audio frames
        - A list of listeners
    """
    def __init__(self, sip_call: 'SIPCall'):
        self.sip_call = sip_call  # SIPCall object
        self.sip_call_info: pj.CallInfo
        try:
            # Set initial call info
            self.sip_call_info = sip_call.get_info()
        except:
            self.sip_call_info = None
            pass
        self.call_id: str = self.sip_call_info.callIdString if self.sip_call_info is not None else None
        self.audio_port: SIPAudioBridge = None  # PJSUA2.AudioMediaPort
        self.listeners: dict[str, SIPToBrowserAudioTrack] = {}  # Maps WebSocket ID -> AudioStreamTrack

        self.logger = get_logger(f"CallState[{sip_call.getInfo().callIdString}]")
        self.logger.debug("init new CallState")
    
    def update_call_info(self, sip_call_info: 'pj.CallInfo'):
        self.logger.debug(f"update_call_info. state={sip_call_info.stateText}")
        self.sip_call_info = sip_call_info
        if self.call_id is None:
            self.call_id = self.sip_call_info.callIdString
    def get_call_info(self):
        return get_sip_call_info(self.sip_call)

    # Terminate the call state (clean up audio port and listeners)
    def terminate(self) -> None:
        if self.audio_port:
            # TODO: Stop Audio Port
            self.logger.debug("Deleting audio_port")
            self.audio_port = None
        
        # TODO: Terminate all listeners to the AudioPort (self.listeners)
        # for listener_websocket_id, track in self.listeners.items():
        #     self.logger.debug(f"Stopping audio track {track.id}")
        #     track.stop()  # Terminate the track
        # self.listeners.clear()
