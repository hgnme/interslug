import asyncio
from dataclasses import asdict, dataclass
import json
import pjsua2 as pj

from websockets.asyncio.server import serve, ServerConnection
from websockets.exceptions import ConnectionClosedOK

from interslug.misc_garbage.run_async_as_sync import run_async_as_sync
from interslug.state.call_state import get_sip_call_info

from .rtc_handler import RTCHandler
from interslug.media_cookery.bridges import SIPAudioBridge, SIPToBrowserAudioTrack
from interslug.media_cookery.queuing import Q_LIST_TYPE_SIP_TO_BROWSER, Q_LIST_TYPE_BROWSER_TO_SIP, get_queue_list_by_type, get_queue_by_id
from interslug.messages.message_builder import message_to_str
from interslug.messages.notification_types import NotificationOnCallStatus
from logging_config import get_logger
from config import HGN_SSL_CONTEXT

from typing import TYPE_CHECKING
from hgn_sip.sip_media import get_audio_format

from interslug.state.call_manager import global_call_manager

if TYPE_CHECKING:
    from hgn_sip.sip_call import SIPCall
    from hgn_sip.sip_account import SIPAccount

# PJSIP Call State
websocket_clients = set()  # Tracks connected WebSocket clients
rtcpc_clients = []

rtc_connections: list[RTCHandler] = []

get_queue_list_by_type(Q_LIST_TYPE_SIP_TO_BROWSER)
get_queue_list_by_type(Q_LIST_TYPE_BROWSER_TO_SIP)


def get_pc_for_wsid(wsid):
    """ Return RPC for websocket UUID
    """
    for pc in rtcpc_clients:
        if pc["uuid"] == wsid:
            return pc["pc"]

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

def sip_call_cb_notify_ws(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'pj.CallInfo'):
    """ 
        Callback triggered on call statuses from hgnsip.sip_call
        Notifies the WS clients of the state
    """
    logger = get_logger("sip_call_cb_notify_ws")
    data = asdict(get_sip_call_info(call))

    msg = {
        "type": "on_call_status",
        "call": data
    }
    logger.debug(msg)
    run_async_as_sync(global_call_manager.send_ws_message(msg))
    # asyncio.run(global_call_manager.send_ws_message(msg))


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
        global_call_manager.browser_add_rtc_handler(websocket.id, rtc_conn)
        rtc_connections.append(rtc_conn)

    msg_type = message["type"]
    # logger.debug(f"type={msg_type}")

    if msg_type == "offer":
        answer = await rtc_conn.process_offer_and_form_answer(message)
        logger.debug("Responding with answer")
        await websocket.send(message_to_str(answer, "rtc"))
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
        await global_call_manager.browser_join_call(websocket.id, target_call_id)
    elif msg_type == "end_call":
        target_call_id = message["call_id"]
        logger.debug(f"Wants to disconnect from call. callid={target_call_id}")
        await global_call_manager.browser_leave_call(websocket.id)
    elif msg_type == "get_call_list":
        await global_call_manager.send_browser_call_list(websocket.id)


async def handle_signaling(websocket: ServerConnection):
    global websocket_clients
    websocket_clients.add(websocket)
    logger = get_logger(f"ws-handle-signalling[{websocket.id}]")
    logger.debug(f"New websocket client remote_address={websocket.remote_address}")
    browser_id = websocket.id
    global_call_manager.add_browser(browser_id, websocket)

    try:
        should_run = True
        while should_run:
            try:
                # Wait for messages from the browser
                message = await asyncio.wait_for(websocket.recv(), timeout=10)
                data = json.loads(message)
                logger.debug(f"Received message. msg={data}")
                msg_channel = data["channel"]

                if msg_channel == "rtc":
                    logger.debug(f"Received message for RTC Channel, triggering process_rtc_msg")
                    await process_rtc_msg(websocket, data["message"])
                elif msg_channel == "SIP":
                    logger.debug(f"Received message for SIP Channel, triggering process_sip_msg")
                    await process_sip_msg(websocket, data["message"])
            except asyncio.TimeoutError:
                # Send a ping to the browser to keep the connection alive
                wait_pong = await websocket.ping()
                # latency = await wait_pong
                # logger.debug(f"ping response. latency={latency}s")
            except ConnectionClosedOK as e:
                should_run = False
                logger.debug("Connection closed (ok)")
                global_call_manager.remove_browser(browser_id)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        global_call_manager.remove_browser(browser_id)
        raise
    finally:
        if websocket is not None:
            logger.debug(f"Connection from {websocket.remote_address} closed")
            global_call_manager.remove_browser(browser_id)
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
