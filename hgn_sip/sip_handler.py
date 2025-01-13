import pjsua2 as pj
import threading
from config import PJSUA_LOG_LEVEL
from logging_config import get_logger
from .sip_account import SIPAccount

class SIPHandler:
    def __init__(self, bind_ip: str, bind_port: int):
        self.logger = get_logger("sip_handler")
        self.shutdown_flag = threading.Event()

        # Binding IP:PORT for the SIP Endpoint
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.account: SIPAccount = None

        self.endpoint = pj.Endpoint()
        self.logger.info(f"Creating new SIPHandler on bind_ip={bind_ip}, bind_port={bind_port}")
        
        # Initialise Config Objects
        transport_config = pj.TransportConfig()
        log_config = pj.LogConfig()
        ep_config = pj.EpConfig()

        # Set up Log Config
        self.logger.debug(f"Setting PJSUA2 Log level to log_level={PJSUA_LOG_LEVEL}")
        log_config.level = PJSUA_LOG_LEVEL
        log_config.consoleLevel = PJSUA_LOG_LEVEL

        # Attach Log Config to Endpoint Config
        self.logger.debug(f"Attaching LogConfig to EpConfig")
        ep_config.logConfig = log_config

        # Configure Transport Config
        self.logger.debug(f"Setting Transport Config boundAddress:port. boundAddress={self.bind_ip}, port={self.bind_port}")
        transport_config.port = self.bind_port
        transport_config.boundAddress = self.bind_ip

        self.transport_config = transport_config
        self.ep_config = ep_config
    def create_endpoint(self):
        # Init Endpoint with relevant Config.
        self.logger.debug(f"Creating Endpoint")
        self.endpoint.libCreate()
        self.logger.debug(f"Initialising Endpoint with EpConfig")
        self.endpoint.libInit(self.ep_config)
        
        # Set to Null Audio Device so that the calls don't shit themselves. Ignore incoming audio, and transmit silence.
        adm: pj.AudDevManager = self.endpoint.audDevManager()
        if PJSUA_LOG_LEVEL >= 3:
            aud_devs: list[pj.AudioDevInfo] = adm.enumDev2()
            for dev_info in aud_devs:
                self.logger.debug(f"Audio device: name={dev_info.name}, driver={dev_info.driver}, input_channels={dev_info.inputCount}, output_channels={dev_info.outputCount}")
            self.logger.debug("Setting null audio dev")
        adm.setNullDev()

        # Attach SIP/UDP Transport to Endpoint (with relevant config)
        self.logger.debug(f"Registering SIP/UDP Transport with TransportConfig")
        self.endpoint.transportCreate(pj.PJSIP_TRANSPORT_UDP, self.transport_config)

        # Start the Endpoint now it's configured.
        self.logger.debug(f"Starting Endpoint")
        self.endpoint.libStart()
        self.endpoint.libRegisterThread("thread-siphandler")
        self.logger.info("SIP handler started")
    
    def register_account(self, sip_handle: str):
        # Create Account's RTP config and mark it's IP's
        self.logger.debug(f"Registering Account. handle={sip_handle}")
        rtp_config = pj.TransportConfig()
        acc_config = pj.AccountConfig()
        acc_nat_config = pj.AccountNatConfig()
        acc_media_config = pj.AccountMediaConfig()
        acc_sip_config = pj.AccountSipConfig()
        acc_config.idUri = f"sip:{sip_handle}@{self.bind_ip}:{self.bind_port}"

        # Set bind IP and Public IP to that of the handler
        rtp_config.boundAddress = self.bind_ip
        rtp_config.publicAddress = self.bind_ip
        
        # Attach RTP config to account for Media
        acc_media_config.transportConfig = rtp_config
        # Set contactForced to the idURI to prevent it being rewritten behind NAT.
        acc_sip_config.contactForced = acc_config.idUri

        # Set Nat Config, disable STUN and Nat
        acc_nat_config.sipStunUse = pj.PJSUA_STUN_USE_DISABLED
        acc_nat_config.mediaStunUse = pj.PJSUA_STUN_USE_DISABLED

        # Attach Media and SipConfigs to the AccountConfig
        acc_config.mediaConfig = acc_media_config
        acc_config.sipConfig = acc_sip_config
        acc_config.natConfig = acc_nat_config
        
        # Initialise account object and attach to the SIPHandler
        self.logger.info("Creating SIPAccount on Endpoint with Config")
        self.account = SIPAccount(self.endpoint)
        self.account.create(acc_config)
        self.logger.info("Account created")
    
    def stop(self):
        self.logger.info("Stopping SIPHandler")
        # Register thread because the Endpoint's running in another one and will shit the bed if main touches it
        self.endpoint.libRegisterThread("main-thread")
        self.logger.info("Destroying Account")
        self.account.destroy()
        self.logger.info("Destorying Endpoint")
        self.endpoint.libDestroy()
        self.logger.info("SIP handler stopped.")