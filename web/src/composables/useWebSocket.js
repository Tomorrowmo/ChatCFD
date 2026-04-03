import { ref } from 'vue'
import { useChatStore } from '../stores/chat.js'

const AGENT_WS_URL = 'ws://localhost:8080/ws'
const MOCK_MODE = true // Set to false when Agent WebSocket is available

// Mock responses for frontend development
const MOCK_RESPONSES = [
  {
    content: 'File loaded successfully. The dataset contains 3 zones with pressure, velocity, and temperature fields.',
    artifacts: [
      {
        title: 'Load Summary',
        type: 'numerical',
        summary: 'Loaded case_run023: 3 zones, 156,832 cells total',
        data: {
          zones: ['inlet', 'outlet', 'wall'],
          total_cells: 156832,
          scalars: ['Pressure', 'Velocity', 'Temperature'],
          file: 'case_run023.vtm',
        },
      },
    ],
  },
  {
    content: 'Force and moment calculation completed. The total drag force is 12.45 N and lift force is 89.23 N.',
    artifacts: [
      {
        title: 'Force & Moment',
        type: 'numerical',
        summary: 'Drag=12.45N, Lift=89.23N, L/D=7.17',
        data: {
          drag: { value: 12.45, unit: 'N' },
          lift: { value: 89.23, unit: 'N' },
          moment_x: { value: 0.34, unit: 'N*m' },
          moment_y: { value: -1.22, unit: 'N*m' },
          moment_z: { value: 0.08, unit: 'N*m' },
          lift_to_drag: 7.17,
        },
      },
    ],
  },
  {
    content: 'Here is the pressure distribution data exported as CSV.',
    artifacts: [
      {
        title: 'Pressure Export',
        type: 'file',
        summary: 'Exported pressure data for wall zone (1,024 points)',
        file_path: '/exports/pressure_wall.csv',
        data: null,
      },
    ],
  },
]

let mockIndex = 0

function createMockWebSocket() {
  const { addMessage, addArtifact } = useChatStore()

  function send(message) {
    // Simulate delay then respond
    setTimeout(() => {
      const resp = MOCK_RESPONSES[mockIndex % MOCK_RESPONSES.length]
      mockIndex++

      const artifactRefs = []
      if (resp.artifacts) {
        for (const art of resp.artifacts) {
          const added = addArtifact(art)
          artifactRefs.push({ id: added.id, title: added.title })
        }
      }

      addMessage('assistant', resp.content, artifactRefs)
    }, 800 + Math.random() * 700)
  }

  function connect() {
    console.log('[WebSocket] Mock mode enabled - no real connection')
  }

  function disconnect() {
    // no-op in mock mode
  }

  return { send, connect, disconnect }
}

function createRealWebSocket() {
  const { addMessage, addArtifact } = useChatStore()
  const ws = ref(null)
  let reconnectTimer = null

  function connect() {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) return

    ws.value = new WebSocket(AGENT_WS_URL)

    ws.value.onopen = () => {
      console.log('[WebSocket] Connected to', AGENT_WS_URL)
      if (reconnectTimer) {
        clearTimeout(reconnectTimer)
        reconnectTimer = null
      }
    }

    ws.value.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        const artifactRefs = []

        if (data.artifacts) {
          for (const art of data.artifacts) {
            const added = addArtifact(art)
            artifactRefs.push({ id: added.id, title: added.title })
          }
        }

        addMessage('assistant', data.content || '', artifactRefs)
      } catch (err) {
        console.error('[WebSocket] Failed to parse message:', err)
      }
    }

    ws.value.onclose = () => {
      console.log('[WebSocket] Disconnected, reconnecting in 3s...')
      reconnectTimer = setTimeout(connect, 3000)
    }

    ws.value.onerror = (err) => {
      console.error('[WebSocket] Error:', err)
      ws.value.close()
    }
  }

  function send(message) {
    if (ws.value && ws.value.readyState === WebSocket.OPEN) {
      ws.value.send(JSON.stringify({ content: message }))
    } else {
      console.warn('[WebSocket] Not connected, cannot send')
    }
  }

  function disconnect() {
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws.value) {
      ws.value.close()
      ws.value = null
    }
  }

  return { send, connect, disconnect }
}

export function useWebSocket() {
  if (MOCK_MODE) {
    return createMockWebSocket()
  }
  return createRealWebSocket()
}
