// Centralized service URLs. Change here once when ports move.
// Optional Vite env override: set VITE_POST_SERVICE_URL in .env.local
export const POST_SERVICE_URL = import.meta.env.VITE_POST_SERVICE_URL || 'http://localhost:8001'
export const AGENT_WS_URL = import.meta.env.VITE_AGENT_WS_URL || 'ws://localhost:8080/ws'
