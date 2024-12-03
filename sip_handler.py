import time
import pjsua2 as pj
from logging_config import get_logger

unlock_message_content = """<params>
        <app>talk</app>
        <event>unlock</event>
        <event_url>/talk/unlock</event_url>
        <host>3000410</host>
        <build>3</build>
        <unit>0</unit>
        <floor>4</floor>
        <family>10</family>
</params>"""
class NewCall(pj.Call):
    def __init__(self, acc, call_id = pj.PJSUA_INVALID_ID):
        self.logger = get_logger("new-call")
        self.logger.debug(f"new call id: {call_id}")
        pj.Call.__init__(self, acc, call_id)
        self.logger.debug("init complete")
        self.acc = acc
        self.connected = False
        self.msg_sent = False

    def onCallState(self, prm):
        ci = self.getInfo()
        self.logger.debug(f"Call state {ci.state}")
        self.connected = ci.state == pj.PJSIP_INV_STATE_CONFIRMED # PJSIP_INV_STATE_CONFIRMED == 5

        if self.connected:
            self.logger.info("Call is now connected, sleeping 1 second")
            time.sleep(1)
            self.logger.info("sending unlock")
            self.send_message_in_call(unlock_message_content)
            self.logger.info("sleeping 5 seconds")
            time.sleep(5)
            call_param = pj.CallOpParam()
            call_param.statusCode = 200
            self.logger.info("hanging up")
            self.hangup(call_param)
   
    def onCallMediaState(self):
        call_info = self.getInfo()
        self.logger.info(f"Call media state changed: {call_info.mediaStatus}")
        
        # Check the media state and attach transport if needed
        if call_info.mediaStatus == pj.PJSIP_MEDIA_ACTIVE:
            for media_idx in range(len(call_info.media)):
                media = self.getMedia(media_idx)
                if isinstance(media, pj.AudioMedia):
                    # Set a null (dummy) audio media transport
                    null_media = pj.AudioMediaNull()
                    media.startTransmit(null_media)  # Attach the null media
                    self.logger.info(f"Dummy media attached for media index {media_idx}.")

    def onInstantMessage(self, prm):
        self.logger.info(f"Incoming message from {prm.fromUri}: {prm.msgBody}")

        # chat instance should have been initalized

    def onInstantMessageStatus(self, prm):
        # if prm.code/100 == 2: return
        # # chat instance should have been initalized
        # if not self.chat: return
        
        self.logger.info("sending message to '%s' (%d): %s" % (self.peerUri, prm.code, prm.reason))

    def send_message_in_call(self, content):
        if self.msg_sent:
            return
        try:
            msg_param = pj.SendInstantMessageParam()
            msg_param.content = content
            # msg_param.
            self.sendInstantMessage(msg_param)
            self.logger.info(f"Message sent: {content}")
            msg_param = None
            self.msg_sent = True
        except pj.Error as e:
            self.logger.error(f"Failed to send message: {e}")
    
    def onCallMediaTransportState(self, prm):
        self.logger.info("Media transport state")
        pass

class MyAccount(pj.Account):
    def __init__(self):
        super().__init__()
        self.logger = get_logger("sip_account")
        self.calls = []
    
    def onIncomingCall(self, prm):
        self.logger.info("Incoming call detected.")
        
        call = NewCall(self, call_id = prm.callId)
        call_param = pj.CallOpParam()
        call_param.statusCode = 180
        # Answer the call
        try:
            self.logger.info("Answering call.")
            call.answer(call_param)
            self.logger.info("Call answered.")
            call_info = call.getInfo()
            self.logger.info(call_info)
            call_param.statusCode = 200
            call.answer(call_param)
        except Exception as e:
            self.logger.error(f"Failed to answer the call: {e}")
            call.hangup(call_param)
        
        self.calls.append(call)
    def onInstantMessage(self, prm: pj.OnInstantMessageParam):
        self.logger.info(f"Incoming message from {prm.fromUri}: {prm.msgBody}")

class SIPHandler:
    def __init__(self, ip):
        self.logger = get_logger("sip_handler")
        self.endpoint = pj.Endpoint()
        self.endpoint.libCreate()

        log_cfg = pj.LogConfig()
        log_cfg.level = 3
        log_cfg.consoleLevel = 3

        config = pj.EpConfig()
        config.logConfig = log_cfg
        self.endpoint.libInit(config)
        
        transport_config = pj.TransportConfig()
        transport_config.port = 5060
        transport_config.boundAddress = ip
        self.endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, transport_config)
            
        # Apply the media configuration
        self.endpoint.libStart()

        # self.endpoint.libStart()
        self.logger.info("SIP handler started.")
        
        
        rtp_config = pj.TransportConfig()
        rtp_config.boundAddress = ip
        rtp_config.publicAddress = ip
        
        self.account = MyAccount()
        acc_config = pj.AccountConfig()
        acc_config.mediaConfig = pj.AccountMediaConfig()
        acc_config.mediaConfig.transportConfig = rtp_config
        acc_config.idUri = f"sip:3000999@{ip}"
        self.account.create(acc_config)
    
    def stop(self):
        self.endpoint.libDestroy()
        self.logger.info("SIP handler stopped.")