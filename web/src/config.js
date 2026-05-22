// Centralized service URLs. Change here once when ports move.
// Optional Vite env override: set VITE_POST_SERVICE_URL in .env.local
//
// Host is derived from the page's own hostname so a LAN client reaches the
// server it loaded the page from — not its own machine. Open the UI as
// http://<server-LAN-IP>:5173 and every API/WS call follows that IP.
const HOST = (typeof window !== 'undefined' && window.location.hostname) || 'localhost'

export const POST_SERVICE_URL = import.meta.env.VITE_POST_SERVICE_URL || `http://${HOST}:8001`
export const AGENT_WS_URL = import.meta.env.VITE_AGENT_WS_URL || `ws://${HOST}:8090/ws`
export const AGENT_HTTP_URL = import.meta.env.VITE_AGENT_HTTP_URL || `http://${HOST}:8090`
