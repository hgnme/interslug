import threading
from flask import Flask, render_template, request, jsonify
from logging_config import get_logger
from service_helper import stop_event
from typing import TYPE_CHECKING
from .intercom_handler import trigger_send_unlock_to_wallpanel
from config import WALL_PANELS
from werkzeug.serving import make_server, BaseWSGIServer

if TYPE_CHECKING:
    from udp_handler import UDPHandler
    from .intercom_handler import IntercomSIPHandler

# ChatGPT did all this
class WebInterface:
    def __init__(self, udp_handler: 'UDPHandler', intercom_sip_handler: 'IntercomSIPHandler'):
        self.udp_handler = udp_handler
        self.sip_handler = intercom_sip_handler.sip_handler
        self.logger = get_logger("web-interface")
        self.app = Flask(__name__, template_folder="templates")
        self.wall_panels = WALL_PANELS
        self._setup_routes()
        self.servers: list[BaseWSGIServer] = []

    def _setup_routes(self):
        @self.app.route("/", methods=["GET"])
        def control_panel_ui():
            # Pass wall panels to the template
            return render_template("index.html", panels=self.wall_panels)

        @self.app.route("/api/list_panels", methods=["GET"])
        def handle_panels_list():
            panels_list = []
            panel_ids = []
            panel_labels = []
            panels_dict = {}
            for panel in WALL_PANELS:
                panels_dict[f"{panel.label}"] = panel.name
                panels_list.append({"key":panel.name, "label": f"{panel.label}"})
                panel_ids.append(panel.name)
                panel_labels.append(f"{panel.label}")
            
            return jsonify({"success":True, "panels": panels_list, "panel_ids": panel_ids, "panel_labels": panel_labels, "panels_dict":panels_dict})
        @self.app.route("/api/action", methods=["POST"])
        def handle_action():
            data = request.json
            action = data.get("action")
            destination = data.get("destination")
            message = ""

            if action == "call_elevator":
                self.logger.info("Call Elevator action triggered")
                self.udp_handler.elevator_request(3, 4)  # Adjust logic as needed
                message = "Elevator request sent!"
            elif action == "trigger_intercom":
                self.logger.info(f"Trigger Intercom action triggered for {destination}")
                trigger_send_unlock_to_wallpanel(destination, self.sip_handler.account)
                message = f"Intercom triggered for {destination}!"
            else:
                self.logger.warning(f"Unknown action: {action}")
                return jsonify({"message": "Unknown action", "success": False}), 400

            return jsonify({"message": message, "success": True})

    def run(self, host: str, port: int):
        # Use a server that can be manually shut down
        server = make_server(host, port, self.app)
        self.servers.append(server)
        # Start the server and block until shutdown
        self.logger.info(f"Starting Flask server on {host}:{port}")
        server.serve_forever()
    def shutdown_all(self):
        for server in self.servers:
            server.shutdown()
        
class WebInterfaceWrapper:
    def __init__(self, web_interface: WebInterface):
        self.logger = get_logger("web-interface-wrapper")
        self.web_interface = web_interface
        self.threads: list[threading.Thread] = []
# web_interface.run, args=("192.168.1.185", 5000), name="thread-web-interface", daemon=True).start()
    def run(self, host: str, port: int):
        self.logger.info(f"Starting webserver for ip={host}, port={port}")
        thread = threading.Thread(target=self._run_server, args=(host, port), daemon=True)
        thread.start()
        self.threads.append(thread)

    def _run_server(self, host: str, port: int):
        self.web_interface.run(host=host, port=port)

    def stop(self):
        self.logger.info("Shutting down servers")
        self.web_interface.shutdown_all()
        for thread in self.threads:
            thread.join()  # Ensure that all threads finish before exiting
