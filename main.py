import threading
from udp_handler import UDPHandler
# from sip_handler import SIPHandler
# from config import SIP_USER, SIP_PASSWORD, SIP_SERVER

def main():
    print("hi")
    udp = UDPHandler()
    print("die")
    # sip = SIPHandler()

    try:
        # udp.periodic_broadcast("Static packet content")
        threading.Thread(target=udp.receive, daemon=True).start()
        threading.Thread(target=udp.periodic_dhcp, daemon=True).start()
        udp.elevator_request()
        # sip.setup()
        # # Example direct interactions:
        # sip.make_call("user@192.168.1.100:5060")
        # sip.send_message("user@192.168.1.100:5060", "Hello from Raspberry Pi!")
        # Add logic for user input or triggers
        input("Press Enter to exit...\n")
    finally:
        udp.stop()
        # sip.shutdown()
if __name__ == "__main__":
    main()