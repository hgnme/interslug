import threading
from logging_config import get_logger
import requests 

from udp_handler import UDPHandler
from hgn_sip.sip_handler import SIPHandler
from interslug.intercom_handler import IntercomSIPHandler
from interslug.web_interface import WebInterface

from config import FAKE_ID

main_logger = get_logger("main")

def download_file(url, filename):
    try:
        main_logger.info(f"Starting download from {url}")
        response = requests.get(url)
        with open(filename, 'wb') as file:
            file.write(response.content)
        main_logger.info(f"File downloaded successfully: {filename}")
    except Exception as e:
        main_logger.error(f"Error downloading file: {e}")

def main():
    main_logger.info("Starting main thread")
    bind_ip_address = "192.168.67.98"
    ts_ip_address = "100.82.195.107"
    bind_sip_port = 5060

    main_logger.info(f"Creating SIPHandler. ip={bind_ip_address}, port={bind_sip_port}")
    intercom_sip_handler = IntercomSIPHandler(bind_ip_address, bind_sip_port, FAKE_ID)

    main_logger.info(f"Creating UDPHandler")
    udp_handler = UDPHandler()

    main_logger.info(f"Creating WebInterface")
    web_interface = WebInterface(udp_handler, intercom_sip_handler)

    download_url = 'http://ftp.iinet.net.au/pub/knoppix/KNOPPIX_V9.1CD-2021-01-25-EN.iso'
    download_filename = 'KNOPPIX_V9.1CD-2021-01-25-EN.iso'
    threading.Thread(target=download_file, args=(download_url, download_filename), daemon=True).start()

    try:
        # Create SIP thread (which also registers the account)
        main_logger.info(f"Starting thread for SIPHandler")
        sip_thread = threading.Thread(target=intercom_sip_handler.run, name="thread-siphandler", daemon=True)
        sip_thread.start()
        # Create thread to process incoming packets
        main_logger.info(f"Starting thread for UDPHandler.receive")
        threading.Thread(target=udp_handler.receive, name="thread-udphandler-receive", daemon=True).start()
        # Create thread to occasionally transmit DHCP packet
        main_logger.info(f"Starting thread for UDPHandler.periodic_dhcp")
        threading.Thread(target=udp_handler.periodic_dhcp, name="thread-udphandler-periodic_dhcp", daemon=True).start()

        # Start Flask web listener
        threading.Thread(target=web_interface.run, args=("192.168.1.185", 5000), name="thread-web-interface", daemon=True).start()
        threading.Thread(target=web_interface.run, args=(ts_ip_address, 5000), name="thread-web-interface-ts", daemon=True).start()
        input("Press Enter to exit...\n")
    finally:
        udp_handler.stop()
        intercom_sip_handler.stop()
if __name__ == "__main__":
    main()