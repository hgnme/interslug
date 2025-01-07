import pjsua2 as pj
from logging_config import get_logger
from .sip_buddy import SIPBuddy
from .sip_callbacks import SIPCallStateCallback
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .sip_account import SIPAccount

def get_call_param(code:int) -> pj.CallOpParam:
    ret = pj.CallOpParam()
    ret.statusCode = code
    return ret

def get_call_media_status_string(code):
    call_media_status_strings = ["PJSUA_CALL_MEDIA_NONE", "PJSUA_CALL_MEDIA_ACTIVE", "PJSUA_CALL_MEDIA_LOCAL_HOLD", "PJSUA_CALL_MEDIA_REMOTE_HOLD", "PJSUA_CALL_MEDIA_ERROR"]
    return call_media_status_strings[code]

def get_call_media_direction_string(code):
    call_media_direction_strings = ["PJMEDIA_DIR_NONE", "PJMEDIA_DIR_ENCODING", "PJMEDIA_DIR_CAPTURE", "PJMEDIA_DIR_DECODING", "PJMEDIA_DIR_PLAYBACK", "PJMEDIA_DIR_RENDER", "PJMEDIA_DIR_ENCODING_DECODING", "PJMEDIA_DIR_CAPTURE_PLAYBACK", "PJMEDIA_DIR_CAPTURE_RENDER"]
    return call_media_direction_strings[code]
    
def get_call_media_type_string(code):
    call_media_type_strings = ["PJMEDIA_TYPE_NONE", "PJMEDIA_TYPE_AUDIO", "PJMEDIA_TYPE_VIDEO", "PJMEDIA_TYPE_APPLICATION", "PJMEDIA_TYPE_UNKNOWN", ]
    return call_media_type_strings[code]

class SIPCall(pj.Call):
    def __init__(self, acc, call_id = pj.PJSUA_INVALID_ID, callbacks: list[SIPCallStateCallback] = []):
        # Init logger
        self.logger = get_logger("new-call")
        self.logger.info(f"Initialising new call. call_id={call_id}")
        # Init the PJSUA2 Call with the Account and Call ID provided from SIPAccount
        pj.Call.__init__(self, acc, call_id)
        self.acc: SIPAccount = acc
        self.connected = False
        self.msg_sent = False
        self.call_id = call_id
        self.onCallStateCallBacks = callbacks
        self.is_outgoing = True if call_id == pj.PJSUA_INVALID_ID else False
        self.ports = []
    def end_call(self):
        self.logger.info("Hanging up call")
        self.hangup(get_call_param(pj.PJSIP_SC_REQUEST_TERMINATED))
    
    def dump_audio_media_details(self, am):
        port_info: pj.ConfPortInfo = am.getPortInfo()
        port_format: pj.MediaFormatAudio = port_info.format
        self.logger.debug(f"port info. id={port_info.portId}, name={port_info.name}, txLevelAdj={port_info.txLevelAdj}, rxLevelAdj={port_info.rxLevelAdj}")
        self.logger.debug(f"format info. clockRate={port_format.clockRate}, channelCount={port_format.channelCount}, frameTimeUsec={port_format.frameTimeUsec}, bitsPerSample={port_format.bitsPerSample}, type={port_format.type}")

    def dump_audio_media_info(self):
        ci: pj.CallInfo = self.getInfo()
        call_media_info_list: list[pj.CallMediaInfo] = ci.media
        for call_media_info in call_media_info_list:
            self.logger.debug(f"media found type={call_media_info.type}, idx={call_media_info.index}, status={call_media_info.status}, direction={call_media_info.dir}, type_str={get_call_media_type_string(call_media_info.type)}, status_str={get_call_media_status_string(call_media_info.status)}, direction_str={get_call_media_direction_string(call_media_info.dir)}")
            if call_media_info.type == pj.PJMEDIA_TYPE_AUDIO:
                audio_media: pj.AudioMedia = self.getAudioMedia(call_media_info.index)
                self.dump_audio_media_details(audio_media)
    
    def get_call_audio_media(self) -> pj.AudioMedia:
        ci = self.getInfo()
        cmil = ci.media
        for cmi in cmil:
            if cmi.type == pj.PJMEDIA_TYPE_AUDIO:
                return self.getAudioMedia(cmi.index)
    
    def make_call(self, remote_uri):
        cs = pj.CallSetting(True)
        cs.audioCount = 1
        cs.videoCount = 0
        params = pj.CallOpParam(True)
        params.opt = cs
        self.makeCall(remote_uri, params)

    def onCallState(self, param: pj.OnCallStateParam):
        # When call state changes, this runs. Depending on the state, do different things.
        # param has nothing useful, so just get info straight away.
        ci: pj.CallInfo = self.getInfo()
        self.logger.debug(f"Call state change. state={ci.state} stateText={ci.stateText} lastReason={ci.lastReason} accId={ci.accId} callIdString={ci.callIdString} localUri={ci.localUri} remoteUri={ci.remoteUri} lastReason={ci.lastReason}")
        if ci.stateText == "INCOMING":
            # Incoming call, mark it as as Ringing
            self.logger.debug("Call incoming, marking as Ringing")
            self.answer(get_call_param(pj.PJSIP_SC_RINGING))
        elif ci.stateText == "EARLY" and ci.lastReason == "Ringing" and not self.is_outgoing:
            # Call changed to Early, answering ("accepting") (only if it's not Incoming)
            self.logger.debug("Call ringing, marking as Accepted")
            self.answer(get_call_param(pj.PJSIP_SC_ACCEPTED))
        elif ci.stateText == "CONFIRMED" and ci.lastReason == "Accepted":
            # Call is connected and live.
            self.logger.debug("Call is now live.")
            self.connected = True
        
        # Execute all callbacks based on their StateText
        for cb in self.onCallStateCallBacks:
            if ci.stateText == cb.on_state_text:
                cb.execute(call = self, call_info = ci)    
        if ci.stateText == "DISCONNECTED":
            for port in self.ports:
                try:
                    port = None
                except Exception as e:
                    self.logger.error(f"Unable to detach custom port, error={e}")
            self.logger.debug("Call disconnected")
            self.acc.delete_call(self.call_id)
        
    # How the fk does Media Work in this
    def onCallMediaState(self, prm: pj.OnCallMediaStateParam):
        self.logger.info("on call media state")
        ci: pj.CallInfo = self.getInfo()
        mi: pj.CallMediaInfo = ci.media

    # Dont think sending IMs in calls is even a thing?
    def onInstantMessageStatus(self, param: pj.OnInstantMessageStatusParam):
        self.logger.info(f"onInstantMessageStatusCall: code={param.code}, reason={param.reason}")

    # Same here. Can delete
    def onInstantMessage(self, param: pj.OnInstantMessageParam):
        contactUri = param.contactUri
        contentType = param.contentType
        fromUri = param.fromUri
        msgBody = param.msgBody
        toUri = param.toUri
        self.logger.info(f"onInstantMessageCall: contactUri={contactUri}, contentType={contentType}, fromUri={fromUri}, toUri={toUri}, msgBody={msgBody}")
