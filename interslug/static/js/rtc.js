const ws = new WebSocket("wss://pi4b.localhost.direct:8765");
const audioElement = document.getElementById("remoteAudio");
const statusElement = document.getElementById("status");
const detailsElement = document.getElementById("details");
const debugText = document.getElementById('debug-text');
const buttonsDiv = document.getElementById("phone_buttons");
const answerBtn = document.getElementById("answer");
const declineBtn = document.getElementById("decline");
let pc = new RTCPeerConnection();
let activeCall = false;
let incomingCallInfo;
let liveCallInfo;

// Log debug information
function logDebugInfo(message, obj=null) {
    const timestamp = new Date().toISOString(); // Get the current timestamp in ISO format
    logmsg = `[${timestamp}] ${message}`
    if (obj !== null) {
        console.log(timestamp, message, obj);
    } else {
        console.log(timestamp, message);
    }

    debugText.textContent += logmsg + '\n';
}

function toggleButtonsVisible(visible) {
    if(visible) {
        buttonsDiv.classList.remove("phone_buttons-hidden")
    } else {
        !buttonsDiv.classList.contains("phone_buttons-hidden") && buttonsDiv.classList.add("phone_buttons-hidden")
    }
}

answerBtn.onclick = (ev) => {
    if (incomingCallInfo && incomingCallInfo.call_id) {
        /* Answer call, send back to server */
        response = {
            channel: "sip",
            message: {
                type: "answer_call",
                call_id: incomingCallInfo.call_id
            }
        }
        logDebugInfo("Sending req to answer call:", response);
        ws.send(JSON.stringify(response));
    }
    return false;
};
declineBtn.onclick = (ev) => {
    if (incomingCallInfo && incomingCallInfo.call_id) {
        /* Answer call, send back to server */
        response = {
            channel: "sip",
            message: {
                type: "decline_call",
                call_id: incomingCallInfo.call_id
            }
        }
        logDebugInfo("Sending req to decline call:", response);
        ws.send(JSON.stringify(response));
    }
    if (liveCallInfo && liveCallInfo.call_id) {
        response = {
            channel: "sip",
            message: {
                type: "end_call",
                call_id: liveCallInfo.call_id
            }
        }
        logDebugInfo("Sending req to end call:", response);
        ws.send(JSON.stringify(response));

    }
    return false;
};

async function test_pc() {
    // Create a new RTCPeerConnection
    pc = new RTCPeerConnection();
    // Set up event listeners for the connection
    pc.onicecandidate = (event) => {
        logDebugInfo("(onIceCandidate)", event)
        if (event.candidate) {
            ip = event.candidate.address
            if(ip.indexOf("172") !== -1) {
                logDebugInfo(`Ignoring candidate based on IP ip=${ip}`)
                return
            }
            cd = event.candidate
            str = `candidate received: ${cd.protocol}://${cd.address}:${cd.port}.\nfull_candidate=${cd.candidate}`
            logDebugInfo(str)
            cd_obj = {
                component: event.candidate.component,
                foundation: event.candidate.foundation,
                ip: event.candidate.address,
                port: event.candidate.port,
                priority: event.candidate.priority,
                protocol: event.candidate.protocol,
                type: event.candidate.type,
                relatedAddress: event.candidate.relatedAddress,
                relatedPort: event.candidate.relatedPort,
                sdpMid: event.candidate.sdpMid,
                sdpMLineIndex: event.candidate.sdpMLineIndex,
                tcpType: event.candidate.tcpType 
            }
            resp_obj = {
                channel: "rtc",
                message: {
                    type: "icecandidate",
                    candidate: cd_obj
                }
            }
            ws.send(JSON.stringify(resp_obj))
        }
    };
    pc.ontrack = (event) => {
        logDebugInfo("(onTrack)", event)
        // Ensure it's an audio track
        if (event.track.kind === 'audio') {
            logDebugInfo(`Received track: ${event.track.id}, kind: ${event.track.kind}`);
            logDebugInfo(`Track details: codec: ${event.track.kind}, state: ${event.track.readyState}`);

            // Attach the audio stream to the <audio> element
            audioElement.srcObject = event.streams[0];

            // Additional debug info
            logDebugInfo(`Track attached to <audio> element. Stream id: ${event.streams[0].id}`);
        }
    };      
    // tcv_opts = {
    //     direction: "recvonly"
    // }
    // logDebugInfo("Adding receive only transceiver")
    // pc.addTransceiver("audio", tcv_opts)
    const offer = await pc.createOffer();
    await pc.setLocalDescription(offer);
    // Send the offer to the signaling server (not shown here, but you should send it via WebSocket)
    logDebugInfo("Sending offer:", offer);
    resp_obj = {
        channel: "rtc",
        message: {
            type: "offer",
            sdp: offer.sdp
        }
    }
    ws.send(JSON.stringify(resp_obj));
}
async function handleRtcMsg(msg) {
    if (msg.type == "answer") {
        logDebugInfo("Processing answer response")
        await pc.setRemoteDescription(new RTCSessionDescription(msg))
    } else if (msg.type == "offer") {
        logDebugInfo("Processing new offer update")
        await pc.setRemoteDescription(new RTCSessionDescription(msg))
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        // Send the offer to the signaling server (not shown here, but you should send it via WebSocket)
        logDebugInfo("Sending answer:", answer);
        resp_obj = {
            channel: "rtc",
            message: {
                type: "answer",
                sdp: answer.sdp
            }
        }
        ws.send(JSON.stringify(resp_obj));
    }
}
async function handleSipMsg(msg) {
    logDebugInfo(msg)
    if (msg.type == "on_call_status") {
        logDebugInfo("on_call_status_msg")
        call_status = msg.call_status
        
        if (call_status === "INCOMING") {
            logDebugInfo("incoming")
            incomingCallInfo = msg
            statusElement.innerText = "Status: Incoming Call";
            toggleButtonsVisible(true)

        } else if (call_status === "CONFIRMED") {
            statusElement.innerText = "Status: Active Call";
            liveCallInfo = msg

        } else if (call_status === "DISCONNECTED") {
            statusElement.innerText = "Status: Call disconnected";
            toggleButtonsVisible(false)
            
        }
    }
}
setTimeout(test_pc, 500);
ws.onmessage = async (event) => {
    const body = JSON.parse(event.data);
    if (body.type !== "ping") {
        logDebugInfo(body)
        detailsElement.innerText = event.data
    }

    if (body.channel == "rtc") {
        await handleRtcMsg(body.message)
    } else if (body.channel == "sip") {
        await handleSipMsg(body.message)

    }
};
