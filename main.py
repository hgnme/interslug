import threading
import signal
import time
from logging_config import get_logger
from service_helper import stop_event
from udp_handler import UDPHandler
from interslug.intercom_handler import IntercomSIPHandler
from interslug.web_interface import WebInterface, WebInterfaceWrapper

from config import FAKE_ID, SHOULD_RUN_DHCP, SHOULD_RUN_SIP, SHOULD_RUN_UDP_HANDLER, SHOULD_RUN_WEB, SIP_LOCAL_PORT, BIND_IP_ADDRESS, TAILSCALE_BIND_IP_ADDRESS, LOCAL_WEB_BIND_IP_ADDRESS

main_logger = get_logger("main")

def main():
    main_logger.info("Starting main thread")

    main_logger.info(f"Creating SIPHandler. ip={BIND_IP_ADDRESS}, port={SIP_LOCAL_PORT}")
    intercom_sip_handler = IntercomSIPHandler(BIND_IP_ADDRESS, SIP_LOCAL_PORT, FAKE_ID)

    main_logger.info(f"Creating UDPHandler")
    udp_handler = UDPHandler()

    main_logger.info(f"Creating WebInterface")
    web_interface = WebInterface(udp_handler, intercom_sip_handler)
    web_wrapper = WebInterfaceWrapper(web_interface)
    def signal_handler(signum, frame):
        main_logger.info(f"Signal received, stopping. signum={signum}")
        stop_event.set()

    # Setup to trigger signal_handler on SIGINT/TERM
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


    try:
        if SHOULD_RUN_SIP:
            # Create SIP thread (which also registers the account)
            main_logger.info(f"Starting thread for SIPHandler")
            sip_thread = threading.Thread(target=intercom_sip_handler.run, name="thread-siphandler", daemon=True)
            sip_thread.start()

        if SHOULD_RUN_UDP_HANDLER:
            # Create thread to process incoming packets
            main_logger.info(f"Starting thread for UDPHandler.receive")
            threading.Thread(target=udp_handler.receive, name="thread-udphandler-receive", daemon=True).start()
        if SHOULD_RUN_DHCP:
            # Create thread to occasionally transmit DHCP packet
            main_logger.info(f"Starting thread for UDPHandler.periodic_dhcp")
            threading.Thread(target=udp_handler.periodic_dhcp, name="thread-udphandler-periodic_dhcp", daemon=True).start()
        if SHOULD_RUN_WEB:
            # Start Flask web listener
            web_wrapper.run(LOCAL_WEB_BIND_IP_ADDRESS, 5000)
            web_wrapper.run(TAILSCALE_BIND_IP_ADDRESS, 5000)
        # threading.Thread(target=web_interface.run, args=("192.168.1.185", 5000), name="thread-web-interface", daemon=True).start()
        # threading.Thread(target=web_interface.run, args=(TAILSCALE_BIND_IP_ADDRESS, 5000), name="thread-web-interface-ts", daemon=True).start()
        print("Running... Press Ctrl+C to interrupt")
        while not stop_event.is_set():
            time.sleep(1)
    except KeyboardInterrupt:
        signal.raise_signal(signal.SIGINT)
    finally:
        web_wrapper.stop()
        udp_handler.stop()
        intercom_sip_handler.stop()
if __name__ == "__main__":
    main()