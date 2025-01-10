from typing import TYPE_CHECKING

from interslug.media_cookery.bridges import BrowserToSIPAudioBridge
from logging_config import get_logger


if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection
    from interslug.rtc_handler import RTCHandler
    from aiortc import MediaStreamTrack
    from interslug.state.call_state import CallState

class BrowserState:
    """
        Represents a current Browser State.
        Contains:
        - The websocket
        - The Current CallState
        - The RTC Handler
    """
    def __init__(self, websocket: 'ServerConnection'):
        self.logger = get_logger("BrowserState")
        self.websocket = websocket  # WebSocket connection object
        self.current_call_id: str = None  # Call ID if browser is in a call
        self.current_call: 'CallState' = None
        self.rtc_handler: 'RTCHandler' = None
        self.listeners = {}
    def get_current_call_id(self) -> str:
        if self.current_call is not None and self.current_call.call_id:
            return self.current_call.call_id
    def deregister_current_call(self): 
        for id in self.listeners:
            listener = self.listeners[id]
            listener.kill()
            listener = None
        self.current_call = None
        self.current_call_id = None
    def assign_new_rtc_handler(self, rtc_handler: 'RTCHandler'):
        self.rtc_handler = rtc_handler
        
        # assign listeners
        ee = self.rtc_handler.emitter
        ee.on("incoming_track", self.onAudioStreamReceived)
    def onAudioStreamReceived(self, track: 'MediaStreamTrack'):
        # Browser's RTC has shared the track with RTC
        # Now I have it, in browser state.
        # I need to attach it to a media bridge, then link it to the Call
        queue_id = f"audio_{self.current_call.call_id}"
        self.logger.debug("Attaching audio track to new bridge")
        track_listener = BrowserToSIPAudioBridge(queue_id, track)
        self.listeners[queue_id] = track_listener