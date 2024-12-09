from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from hgn_sip.sip_account import SIPAccount
    from hgn_sip.sip_call import SIPCall
    from hgn_sip.sip_handler import SIPHandler
    from hgn_sip.sip_buddy import SIPBuddy

from pjsua2 import CallInfo, SendInstantMessageParam, Error, OnInstantMessageStatusParam, SipRxData
from hgn_sip.sip_handler import SIPHandler
from hgn_sip.sip_callbacks import SIPCallStateCallback, SIPInstantMessageStatusStateCallback
from logging_config import get_logger


# Set up the intercom to listen on FAKEID@IP
# Setup hooks to answer when call is answered, to send unlock message
# call, call_account, call_info

def cs_cb_send_unlock_on_connected(call: 'SIPCall', call_account: 'SIPAccount', call_info: 'CallInfo'):
    logger = get_logger("cs_cb_send_unlock_on_connected")
    logger.info("Callback has been triggered")
    unlock_message_content = """
    <params>
        <app>talk</app>
        <event>unlock</event>
        <event_url>/talk/unlock</event_url>
        <host>3000410</host>
        <build>3</build>
        <unit>0</unit>
        <floor>4</floor>
        <family>99</family>
    </params>"""
    mp = SendInstantMessageParam()
    mp.content = unlock_message_content
    mp.contentType = "text/plain"

    dest_buddy: SIPBuddy = call_account.find_buddy(call_info.remoteUri)

    try: 
        logger.info(f"Attempting to send buddy IM. remote_uri={call_info.remoteUri}")
        dest_buddy.sendInstantMessage(mp)
        logger.info(f"Message sent")
    except Error as e:
        logger.error(f"Failed to send message: {e}")

    logger.info("Callback complete")

def im_cb_check_if_message_accepted(im_status_param: 'OnInstantMessageStatusParam', sip_account: 'SIPAccount'):
    logger = get_logger("im_cb_check_if_message_accepted")
    resp_data: 'SipRxData' = im_status_param.rdata
    resp_parts = resp_data.wholeMsg.split("\r\n\r\n", 1)

    if len(resp_parts) > 1:
        resp_body = resp_parts[1]
        logger.info(f"onInstantMessageStatus: Response included body text. body={resp_body}")
        origin_call = sip_account.find_call(im_status_param.toUri)
        if origin_call is not None:
            logger.info(f"match call found, hanging up.")
            origin_call.end_call()


on_call_state_callbacks = [
    SIPCallStateCallback("CONFIRMED", cs_cb_send_unlock_on_connected)
]
on_im_status_callbacks = [
    SIPInstantMessageStatusStateCallback(im_cb_check_if_message_accepted)
]


class IntercomSIPHandler():
    def __init__(self, bind_ip_address: str, bind_sip_port: int, sip_identifier: str):
        self.sip_handler = SIPHandler(bind_ip_address, bind_sip_port)
        self.sip_identifier = sip_identifier
        
    def run(self):
        self.sip_handler.create_endpoint()
        self.sip_handler.register_account(self.sip_identifier)
        self.sip_handler.account.onCallStateCallbacks = on_call_state_callbacks
        self.sip_handler.account.onInstantMessageCallbacks = on_im_status_callbacks

    def stop(self):
        self.sip_handler.stop()
