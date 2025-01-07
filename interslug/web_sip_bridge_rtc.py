import asyncio
from dataclasses import asdict, dataclass
import fractions
import json
import os
import ssl
import time
import numpy as np
import pjsua2 as pj
from av.audio.frame import AudioFrame

from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosedOK
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack, AudioStreamTrack, RTCConfiguration
from logging_config import get_logger
from config import HGN_SSL_CONTEXT
from .rtc_handler import RTCHandler, create_message_str


from typing import TYPE_CHECKING
from hgn_sip.sip_media import get_audio_format
if TYPE_CHECKING:
    from hgn_sip.sip_call import SIPCall
    from hgn_sip.sip_account import SIPAccount

# PJSIP Call State
active_call = None  # Tracks the current active call
AUDIO_TRACK_CONFIRMED = False
websocket_clients = set()  # Tracks connected WebSocket clients
rtcpc_clients = []

# Queues for audio frame passing
class Q():
    id_str: 'str'
    queue: 'asyncio.Queue'

q_list_sip_to_browser: list[Q] = []
rtc_connections: list[RTCHandler] = []

def get_or_create_queue_by_id(id_str: str, q_list: list[Q]):
    for q in q_list:
        if q.id_str == id_str:
            return q
    new_q = Q()
    new_q.id_str = id_str
    new_q.queue = asyncio.Queue(maxsize=5)

    q_list.append(new_q)
    return new_q

def get_pc_for_wsid(wsid):
    """ Return RPC for websocket UUID
    """
    for pc in rtcpc_clients:
        if pc["uuid"] == wsid:
            return pc["pc"]


"""
    Changes:
    - Update the Frame Storage (via SIPAUDIOBRIDGE) to store QueuedFrame
    - Update the frame Getter to store ReturnFrame
    - Start storing dropped frame info
    - Start storing avg frame age
"""

@dataclass 
class QueuedFrame:
    audio_data: np.ndarray[np.int16]
    samples: int
    timestamp_added: float = time.time()

@dataclass
class ReturnFrame(QueuedFrame):
    age_in_sec: float = 0.0
    is_zero_frame: bool = False

def add_frame_to_queue(audio_data, queue: asyncio.Queue):
    """
        Add a Frame to a given queue with a timestamp to track age
    """
    obj = QueuedFrame(audio_data, len(audio_data), time.time())
    
    queue.put_nowait(obj)

def create_zero_frame(samples:int):
    zero_audio_data = np.zeros(samples, dtype=np.int16)
    return ReturnFrame(zero_audio_data, samples, is_zero_frame=True)

async def get_from_queue(queue: asyncio.Queue, max_age: float, expected_sample_size: int):
    """
        Retrieve the first Frame from a given Queue, which is younger than the max_age (in seconds). 
        If no frame is found, a "Zero" frame is returned in the length provided (expected_sample_size)
    """
    logger = get_logger("get_from_queue")
    now = time.time()
    while not queue.empty():
        frame: QueuedFrame = await queue.get()
        return_frame = ReturnFrame(frame.audio_data, frame.samples, frame.timestamp_added)
        return_frame.age_in_sec = now - return_frame.timestamp_added
        if return_frame.age_in_sec <= max_age:
            # Frame is within the cutoff, so it is output
            return return_frame
        else: 
            logger.debug(f"Dropping frame due to excessive age. cutoff={max_age}s, actual={return_frame.age_in_sec}s")
    
    # logger.debug(f"Returning zero frame due to empty queue")
    return create_zero_frame(expected_sample_size)


class SIPToBrowserAudioTrack(AudioStreamTrack): 
    """
        AudioStreamTrack for use with WebRTC. Takes frames from the queue and outputs them
        Timing must be maintained to maintain realtimeness.
        INPUT: Frames from SIP->Browser Queue
        OUTPUT: Frames to WebRTC
    """
    def __init__(self, call_id: str):
        super().__init__()
        self.call_id = call_id
        self.logger = get_logger(f'dummy-AudioStreamTrack[{self.id}]')
        self.format = get_audio_format()
        self.frametime_sec = self.format.frameTimeUsec * 0.000001
        self.queue = get_or_create_queue_by_id(self.call_id, q_list_sip_to_browser).queue
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
        return frame

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
        self.queue = get_or_create_queue_by_id(self.call_id, q_list_sip_to_browser).queue
        self.total_frames = 0
        self.dropped_frames = 0

    def createPort(self, port_name, audio_format: pj.MediaFormatAudio):
        self.logger.debug(f"Registering port name={port_name}")
        self.port_name = port_name
        self.format = audio_format
        super().createPort(port_name, audio_format)

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

def attach_bridge_to_sip_call(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'pj.CallInfo'):
    """ 
        Attach the SIPAudioBridge as a listening port to the SIP Call, this will then receive the frames of audio to share downstream.
    """ 
    logger = get_logger("attach_bridge_to_sip_call")
    # Get call audio media
    # Attach this SIPAudioBridge to it 
    logger.debug("Creating SIPAudioBridge")
    audio_port = SIPAudioBridge(call_id=call_info.callIdString) # This gets audio FROM sip and adds to queue for RTC
    logger.debug("Registering port with pre-defined PCM format")
    audio_port.createPort("WebsocketAudioPort", get_audio_format()) # Audio Format is set once
    call_audio_media = call.get_call_audio_media() # This is the incoming SIP audio stream
    logger.debug("Triggering Transmit on existing call's audiomedia")
    call_audio_media.startTransmit(audio_port)

    call.ports.append(audio_port) # Store the AudioPort for future use
@dataclass
class NotificationOnCallStatus():
    call_status: str
    call_id: str
    acc_id: str
    local_uri: str
    remote_uri: str
    type: str = "on_call_status"

async def send_sip_notification(body: NotificationOnCallStatus):
    dict_obj = asdict(body)
    logger = get_logger("send_sip_notification")
    message = create_message_str(dict_obj, "sip")
    logger.debug(f"Sending notification to clients. count={len(websocket_clients)}")
    for client in websocket_clients:
        logger.debug(f"Sending notification to client remote_addr={client.remote_address}")
        try:
            await client.send(message)
            logger.debug(f"sent")
        except Exception as e:
            logger.error(f"Error notifying client: {e}")

def sip_call_cb_notify_ws(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'pj.CallInfo'):
    """ 
        Callback triggered on call statuses from hgnsip.sip_call
        Notifies the WS clients of the state
    """
    global active_call
    logger = get_logger("sip_call_cb_notify_ws")
    call_id = call_info.callIdString
    data = NotificationOnCallStatus(call_info.stateText, call_info.callIdString, call_info.accId, call_info.localUri, call_info.remoteUri)
    logger.debug(f"call_id={call_id}, state={call_info.stateText}")
    if (call_info.stateText == "CONFIRMED" and call.connected):
        active_call = call
    if call_info.stateText == "DISCONNECTED":
        active_call = None
        queue = get_or_create_queue_by_id(call_info.callIdString, q_list_sip_to_browser)
        q_list_sip_to_browser.remove(queue)
        # Get RTCConn using CallID
        conns_using_call = [rp for rp in rtc_connections if rp.active_call_id == call_id]
        for conn in conns_using_call:
            logger.debug("killing audio sender for RTConn")
            asyncio.run(conn.kill_audio_sender())

    asyncio.run(send_sip_notification(data))

def get_rtc_connection_by_ws_id(ws_id):
    for conn in rtc_connections:
        if conn.ws_id == ws_id:
            return conn

async def process_rtc_msg(websocket: ServerConnection, message): 
    logger = get_logger(f"process-rtc-message[{websocket.id}]")
    rtc_conn = get_rtc_connection_by_ws_id(websocket.id)
    if rtc_conn is None:
        logger.debug("No connection found, creating...")
        rtc_conn = RTCHandler(websocket)
        rtc_connections.append(rtc_conn)

    msg_type = message["type"]
    # logger.debug(f"type={msg_type}")

    if msg_type == "offer":
        answer = await rtc_conn.process_offer_and_form_answer(message)
        logger.debug("Responding with answer")
        await websocket.send(create_message_str(answer, "rtc"))
    if msg_type == "answer":
        logger.debug("Processing new Answer")
        await rtc_conn.update_remote_description(message)

    if msg_type == "icecandidate":
        await rtc_conn.add_ice_candidate(message)

async def process_sip_msg(websocket: ServerConnection, message):
    logger = get_logger(f"process-sip-message[{websocket.id}]")

    msg_type = message["type"]
    logger.debug(f"type={msg_type}")
    
    if msg_type == "answer_call":
        # Browser wants to join the current call. Should advertise the audio track to it.
        target_call_id: str = message["call_id"]
        logger.debug(f"Wants to answer call. callid={target_call_id}")
        rtc_conn = get_rtc_connection_by_ws_id(websocket.id)
        if rtc_conn is None:
            logger.error("rtc_conn is missing for client")
            return
        
        # Create AudioPort to attach to SIP Call
        # Get call by ID?

        # Add audio track to the rtc_conn
        audio_track = SIPToBrowserAudioTrack(target_call_id)
        rtc_conn.active_call_id = target_call_id
        await rtc_conn.add_track(audio_track)
    elif msg_type == "end_call":
        target_call_id = message["call_id"]
        logger.debug(f"Wants to disconnect from call. callid={target_call_id}")
        rtc_conn = get_rtc_connection_by_ws_id(websocket.id)
        if rtc_conn is None:
            logger.error("rtc_conn is missing for client")
            return
        success = await rtc_conn.kill_audio_sender()
        
        


async def handle_signaling(websocket: ServerConnection):
    global websocket_clients
    websocket_clients.add(websocket)
    logger = get_logger(f"ws-handle-signalling[{websocket.id}]")
    logger.debug(f"New websocket client remote_address={websocket.remote_address}")

    try:
        should_run = True
        while should_run:
            try:
                # Wait for messages from the browser
                message = await asyncio.wait_for(websocket.recv(), timeout=10)
                data = json.loads(message)
                msg_channel = data["channel"]

                if msg_channel == "rtc":
                    logger.debug(f"Received message for RTC Channel, triggering process_rtc_msg")
                    await process_rtc_msg(websocket, data["message"])
                elif msg_channel == "sip":
                    logger.debug(f"Received message for SIP Channel, triggering process_sip_msg")
                    await process_sip_msg(websocket, data["message"])
            except asyncio.TimeoutError:
                # Send a ping to the browser to keep the connection alive
                await websocket.send(json.dumps({"type": "ping"}))
            except ConnectionClosedOK as e:
                should_run = False
                logger.debug("Connection closed (ok)")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        raise
    finally:
        if websocket is not None:
            logger.debug(f"Connection from {websocket.remote_address} closed")
            pc = get_pc_for_wsid(websocket.id)
            if pc is not None:
                await pc.close()
            websocket_clients.remove(websocket)

async def run_main():
    logger = get_logger("ws_server_main")
    # Start WebSocket server with WSS
    async with serve(
        handle_signaling, "192.168.1.185", 8765, ssl=HGN_SSL_CONTEXT
    ):
        logger.info("WebRTC signaling server running on wss://192.168.1.185:8765")
        await asyncio.Future()  # Run forever
