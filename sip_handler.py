import pjsua as pj

class SIPHandler:
    def __init__(self):
        self.lib = pj.Lib()
        self.transport = None
        self.account = None

    def setup(self):
        self.lib.init()
        self.transport = self.lib.create_transport(pj.TransportType.UDP, pj.TransportConfig(port=5060))
        self.lib.start()

        # A basic account with no registration to a SIP server
        acc_cfg = pj.AccountConfig()
        self.account = self.lib.create_account(acc_cfg)

    def make_call(self, target_uri):
        """Initiate a call to the specified URI."""
        print(f"Making call to {target_uri}")
        call = self.account.make_call(target_uri)

    def send_message(self, target_uri, message):
        """Send a SIP message to the specified URI."""
        print(f"Sending message to {target_uri}: {message}")
        self.account.send_message(target_uri, message)

    def answer_call(self, call_id):
        """Answer an incoming call."""
        print(f"Answering call with ID {call_id}")
        call = self.lib.get_call(call_id)
        if call:
            call.answer(200)
        else:
            print("No call found to answer.")

    def shutdown(self):
        """Clean up the SIP stack."""
        print("Shutting down SIP")
        self.lib.destroy()
