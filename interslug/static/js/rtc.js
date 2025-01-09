import { SocketHandler } from './ws_mgr.js';

let socketHandler;
window.onload = function() {
    socketHandler = new SocketHandler();
};