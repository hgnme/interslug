from typing import TYPE_CHECKING

from interslug.rtc_handler import RTCHandler
from interslug.state.call_state import CallState

if TYPE_CHECKING:
    from websockets.asyncio.server import ServerConnection

class BrowserState:
    """
        Represents a current Browser State.
        Contains:
        - The websocket
        - The Current CallState
        - The RTC Handler
    """
    def __init__(self, websocket: 'ServerConnection'):
        self.websocket = websocket  # WebSocket connection object
        self.current_call_id: str = None  # Call ID if browser is in a call
        self.current_call: CallState = None
        self.rtc_handler: RTCHandler = None
    def get_current_call_id(self) -> str:
        if self.current_call is not None and self.current_call.call_id:
            return self.current_call.call_id
    def deregister_current_call(self): 
        self.current_call = None
        self.current_call_id = None