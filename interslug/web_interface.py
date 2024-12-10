from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit
from logging_config import get_logger
from typing import TYPE_CHECKING
from .intercom_handler import trigger_send_unlock_to_wallpanel, wall_panels
if TYPE_CHECKING:
    from udp_handler import UDPHandler
    from .intercom_handler import IntercomSIPHandler

# ChatGPT did all this
class WebInterface:
    def __init__(self, udp_handler: 'UDPHandler', intercom_sip_handler: 'IntercomSIPHandler'):
        self.udp_handler = udp_handler
        self.sip_handler = intercom_sip_handler.sip_handler
        self.logger = get_logger("web-interface")
        self.app = Flask(__name__)
        self.socketio = SocketIO(self.app)
        self.wall_panels = wall_panels
        self._setup_routes()
        self._setup_socket_events()

    def _setup_routes(self):
        @self.app.route("/")
        def control_panel():
            return render_template_string(self._html_template(), panels=self.wall_panels)

    def _setup_socket_events(self):
        @self.socketio.on("action")
        def handle_action(data):
            action = data.get("action")
            selected_panel_id = data.get("destination")
            message = None
            if action == "call_elevator":
                self.logger.info("Call Elevator button pressed")
                self.udp_handler.elevator_request(3, 4)  # Adjust parameters as needed
                message = "Elevator request sent!"
            elif action == "trigger_intercom":
                self.logger.info("Trigger Intercom button pressed")
                trigger_send_unlock_to_wallpanel(selected_panel_id, self.sip_handler.account)
                message = "Intercom triggered!"
            emit("action_response", {"message": message})

    def _html_template(self):
        return """
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Control Panel</title>
            <script src="https://cdn.socket.io/4.5.1/socket.io.min.js"></script>
            <script>
                const socket = io();

                function sendAction(action) {
                    const destination = document.getElementById("destination").value;
                    socket.emit("action", { action: action, destination: destination });
                }

                socket.on("action_response", function(data) {
                    const message = document.getElementById("message");
                    message.innerText = data.message;
                });
            </script>
        </head>
        <body>
            <h1>Control Panel</h1>
            <label for="destination">Select Destination:</label>
            <select name="destination" id="destination">
                {% for panel in panels %}
                <option value="{{ panel.name }}">{{ panel.name }} ({{ panel.ip }})</option>
                {% endfor %}
            </select>
            <br><br>
            <button onclick="sendAction('call_elevator')">Call Elevator</button>
            <button onclick="sendAction('trigger_intercom')">Trigger Intercom</button>
            <p id="message"></p>
        </body>
        </html>
        """

    def run(self, host: str, port: int):
        self.socketio.run(self.app, host=host, port=port, debug=False)
