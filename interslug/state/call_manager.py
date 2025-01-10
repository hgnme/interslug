import asyncio
from dataclasses import asdict
from threading import Lock, Thread, current_thread
from typing import TYPE_CHECKING

from hgn_sip.sip_media import get_audio_format
from interslug.media_cookery.bridges import SIPAudioBridge, SIPToBrowserAudioTrack
from interslug.messages.message_builder import message_to_str
from interslug.rtc_handler import RTCHandler
from interslug.state.browser_state import BrowserState
from interslug.state.call_state import CallState
from logging_config import get_logger


if TYPE_CHECKING:
    from hgn_sip.sip_call import SIPCall
    from hgn_sip.sip_account import SIPAccount
    from websockets.asyncio.server import ServerConnection
    from pjsua2 import CallInfo, Endpoint

class CallManager:
    def __init__(self):
        self.calls: dict[str, CallState]       = {}  # Maps Call ID -> CallState objects
        self.browsers: dict[str, BrowserState] = {}  # Maps WebSocket ID -> BrowserState objects
        self.lock = Lock()  # To ensure thread-safe operations
        self.logger = get_logger("CallManager")
        self.sip_endpoint: Endpoint = None
        """
            a CallState has:
             - The SIPCall (sip_call)
             - The AudioPort (audio_port), which is the PJSUA2 AudioMediaPort
             - A list of Listeners (listeners), which is a list of aiortc.AudioStreamTrack keyed by Websocket ID
        """

    def set_endpoint(self,sip_call: 'SIPCall'): 
        if self.sip_endpoint is None:
            self.sip_endpoint = sip_call.acc.ep
    
    def check_or_register_thread(self):
        if self.sip_endpoint is None:
            raise Exception
        thread = current_thread()
        thread_name = thread.getName()
        if not self.sip_endpoint.libIsThreadRegistered():
            self.logger.debug(f"Registering thread in SIPEndpoint. thread_name={thread_name}")
            self.sip_endpoint.libRegisterThread(thread_name)

    # Add a new SIP call
    def add_call(self, call_id: str, sip_call: 'SIPCall') -> CallState:
        self.logger.debug(f"Adding call. call_id={call_id}")
        self.set_endpoint(sip_call)
        with self.lock:
            if call_id in self.calls:
                raise ValueError(f"Call with ID {call_id} already exists.")
            self.calls[call_id] = CallState(sip_call)
            return self.calls[call_id]
    
    # Remove a SIP call
    def remove_call(self, call_id: str) -> None:
        self.logger.debug(f"Removing call. call_id={call_id}")
        with self.lock:
            if call_id in self.calls:
                call_state = self.calls.pop(call_id)
                self.logger.debug(f"active listeners={len(call_state.listeners)}")
                for id in call_state.listeners:
                    self.logger.debug(f"Removing call from browser. websocket_id={id}")
                    self.browser_leave_call(id)
                call_state.terminate()  # Terminate audio port and tracks

    # Get a CallState by ID
    def get_call(self, call_id: str) -> CallState:
        if call_id in self.calls:
            return self.calls[call_id]
    
    # Add a new browser
    def add_browser(self, websocket_id: str, websocket: 'ServerConnection') -> BrowserState:
        self.logger.debug(f"Adding Browser. websocket_id={websocket_id}")
        with self.lock:
            if websocket_id in self.browsers:
                raise ValueError(f"Browser with WebSocket ID {websocket_id} already exists.")
            self.browsers[websocket_id] = BrowserState(websocket)
            return self.browsers[websocket_id]
    
    # Remove a browser
    def remove_browser(self, websocket_id: str) -> None:
        self.logger.debug(f"Removing Browser. websocket_id={websocket_id}")
        with self.lock:
            if websocket_id in self.browsers:
                browser_state = self.browsers.pop(websocket_id)
                self._handle_browser_leaving_call(browser_state)
    # Get a BrowserState by ID
    def get_browser(self, websocket_id: str) -> BrowserState:
        if websocket_id in self.browsers:
            return self.browsers[websocket_id]
        raise KeyError(websocket_id)
    

    # Send a websocket message as either broadcast or specific target browser
    async def send_ws_message(self, message_dict: dict, target_browser_id: str = None):
        message_str = message_to_str(message_dict, "sip")
        targets = self.browsers if target_browser_id is None else {target_browser_id: self.get_browser(target_browser_id)}

        for browser_id in targets:
            client = targets[browser_id].websocket
            self.logger.debug(f"Sending notification to client remote_addr={client.remote_address}")
            try:
                await client.send(message_str)
                self.logger.debug(f"sent")
            except Exception as e:
                self.logger.error(f"Error notifying client: {e}")

    # Add an RTCHandler to browser object
    def browser_add_rtc_handler(self, websocket_id:str, rtc_handler: RTCHandler):
        self.logger.debug(f"Adding RTC Handler to browser. websocket_id={websocket_id}")
        browser = self.get_browser(websocket_id)
        browser.rtc_handler = rtc_handler
    
    # Handle a browser joining a call
    async def browser_join_call(self, websocket_id: str, call_id: str) -> None:
        self.logger.debug(f"Joining browser to call. websocket_id={websocket_id}, call_id={call_id}")
        with self.lock:
            if websocket_id not in self.browsers or call_id not in self.calls:
                raise ValueError(f"Invalid WebSocket ID {websocket_id} or Call ID {call_id}.")
            
            # Get Browser and Call
            browser_state = self.browsers[websocket_id]
            call_state = self.calls[call_id]

            self.check_or_register_thread() # Make sure thread registed
            # Avoid duplicating browser
            if websocket_id in call_state.listeners:
                return

            # Add browser to call listeners
            stream_queue_id = f"c-{call_id}_ws-{websocket_id}"

            # temporary till sort IDs
            stream_queue_id = call_id

            audio_stream_track = SIPToBrowserAudioTrack(stream_queue_id)  # Emit audio FROM queue TO browser
            call_state.listeners[websocket_id] = audio_stream_track

            # Set the CurrentCall object to browserstate
            browser_state.current_call = call_state

            await self._register_audio_track_to_rtc(websocket_id, audio_stream_track) 

            if not call_state.audio_port:
                self._attach_audio_bridge_to_call(call_id) # Create track that will emit FROM SIP to Queue
            
            msg = {
                "type": "call_answered",
                "call": asdict(self.get_call(call_id).get_call_info())
            }
            await self.send_ws_message(msg, websocket_id)


    # Handle a browser leaving a call
    async def browser_leave_call(self, websocket_id: str) -> None:
        self.logger.debug(f"Browser leaving call. websocket_id={websocket_id}")
        # Check Browser is in BrowserList
        if websocket_id not in self.browsers:
            self.logger.error("browser not found in BrowserList")
            return

        # Get BrowserState
        browser_state = self.browsers[websocket_id]
        # Call to remove browser from call
        self._handle_browser_leaving_call(browser_state)
    
        msg = {
            "type": "call_disconnected"
        }
        await self.send_ws_message(msg, websocket_id)

    async def send_browser_call_list(self, websocket_id: str) -> None:
        self.logger.debug("Sharing CallStates with browser")
        calls_obj = {}
        if self.sip_endpoint is not None:
            self.check_or_register_thread()
            for call_id in self.calls:
                call = self.calls[call_id]
                calls_obj[call_id] = asdict(call.get_call_info())
        
        msg = {
            "calls": calls_obj,
            "type": "call_list"
        }
        await self.send_ws_message(msg, websocket_id)


        
    def _attach_audio_bridge_to_call(self, call_id):

        call = self.get_call(call_id)
        
        # Create the port 
        audio_port = SIPAudioBridge(call_id=call_id)
        audio_port.createPort("WebsocketAudioPort", get_audio_format()) # Audio Format is set once
        # Attach it to call's media
        call_audio_media = call.sip_call.get_call_audio_media() # This is the incoming SIP audio stream
        call_audio_media.startTransmit(audio_port)

        # Attach it to CallState
        call.audio_port = audio_port

    # Private method to add an AudioTrack to an existing RTC connection
    # This will trigger renegotiation
    async def _register_audio_track_to_rtc(self, websocket_id, audio_track: SIPToBrowserAudioTrack):
        rtc_handler = self.get_browser(websocket_id).rtc_handler
        await rtc_handler.add_track(audio_track)

    # Private method to clean up if a browser is removed
    def _handle_browser_leaving_call(self, browser_state: 'BrowserState') -> None:
        cid = browser_state.get_current_call_id()
        
        self.logger.debug(f"leaving call internal. current_call_id={cid}")
        if cid:
            browser_state.rtc_handler.kill_audio_sender()
            # Hang up call
            call = self.get_call(cid)
            if call and call.sip_call:
                call.sip_call.end_call()
        
        browser_state.deregister_current_call()

global_call_manager = CallManager()