import asyncio
from dataclasses import asdict, dataclass
import json

from websockets import ConnectionClosedError, serve
from websockets.asyncio.server import ServerConnection
from websockets.exceptions import ConnectionClosedOK

from .rtc_handler import RTCHandler
from interslug.media_cookery.queuing import Q_LIST_TYPE_SIP_TO_BROWSER, Q_LIST_TYPE_BROWSER_TO_SIP, get_queue_list_by_type
from interslug.messages.message_builder import message_to_str
from logging_config import get_logger
from config import HGN_SSL_CONTEXT

from interslug.state.call_manager import global_call_manager
from service_helper import stop_event

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
        await websocket.send(message_to_str(answer, "RTC"))
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
        logger.debug(f"BROWSER INITIATE ANSWER CALL. callid={target_call_id}")
        await global_call_manager.browser_join_call(websocket.id, target_call_id)
    elif msg_type == "end_call":
        target_call_id = message["call_id"]
        logger.debug(f"BROWSER INITIATE END CALL. callid={target_call_id}")
        global_call_manager.browser_leave_call(websocket.id)
    elif msg_type == "get_call_list":
        global_call_manager.send_browser_call_list(websocket.id)


async def handle_signaling(websocket: ServerConnection):
    global websocket_clients
    websocket_clients.add(websocket)
    logger = get_logger(f"ws-handle-signalling[{websocket.id}]")
    logger.debug(f"New websocket client remote_address={websocket.remote_address}")
    browser_id = websocket.id
    global_call_manager.add_browser(browser_id, websocket)

    try:
        while not stop_event.is_set():
            try:
                # Race between receiving message and shutdown
                message_task = asyncio.create_task(websocket.recv())
                shutdown_task = asyncio.create_task(stop_event.wait())
                
                done, pending = await asyncio.wait(
                    [message_task, shutdown_task], 
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=10
                )
                
                # Cancel pending tasks
                for task in pending:
                    task.cancel()
                
                if shutdown_task in done:
                    logger.debug("Shutdown signal received, closing connection")
                    break
                
                if message_task in done:
                    message = message_task.result()
                    data = json.loads(message)
                    msg_channel = data["channel"]

                    if msg_channel == "RTC":
                        await process_rtc_msg(websocket, data["message"])
                    elif msg_channel == "SIP":
                        await process_sip_msg(websocket, data["message"])
                else:
                    # Timeout - send ping
                    wait_pong = await websocket.ping()
                    
            except ConnectionClosedOK as e:
                logger.debug("Connection closed (ok)")
                break
            except ConnectionClosedError as e:
                logger.debug(f"Connection closed with error: {e}")
                break
            except asyncio.CancelledError:
                logger.debug("Connection cancelled during shutdown")
                break
                
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        raise
    finally:
        logger.debug(f"Connection from {websocket.remote_address} closed")
        global_call_manager.remove_browser(browser_id)
        pc = get_pc_for_wsid(websocket.id)
        if pc is not None:
            await pc.close()
        if websocket in websocket_clients:
            websocket_clients.remove(websocket)

async def start_web_sip_bridge(host: str):
    logger = get_logger("start_web_sip_bridge")
    
    def is_shutdown_event_set():
        is_set = stop_event.is_set()
        if is_set:
            logger.info(f"Websockets[wss://{host}:8765]: Shutdown Event detected")
        return is_set

    async with serve(handle_signaling, host, 8765, ssl=HGN_SSL_CONTEXT):
        logger.info(f"Websockets[wss://{host}:8765]: Server Started")        
        # Poll the threading event in an async way
        while not is_shutdown_event_set():
            await asyncio.sleep(0.5)
    
    logger.info(f"Websockets[wss://{host}:8765]: Server stopped")