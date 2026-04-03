const BASE_URL = 'http://localhost:8000'

export function useApi() {
  async function getMesh(sessionId, zone) {
    const resp = await fetch(`${BASE_URL}/api/mesh/${sessionId}/${zone}`)
    if (!resp.ok) throw new Error(`getMesh failed: ${resp.status}`)
    return await resp.arrayBuffer()
  }

  async function getScalar(sessionId, zone, name) {
    const resp = await fetch(`${BASE_URL}/api/scalar/${sessionId}/${zone}/${name}`)
    if (!resp.ok) throw new Error(`getScalar failed: ${resp.status}`)
    return await resp.arrayBuffer()
  }

  async function downloadFile(path) {
    const resp = await fetch(`${BASE_URL}/api/file?path=${encodeURIComponent(path)}`)
    if (!resp.ok) throw new Error(`downloadFile failed: ${resp.status}`)
    return await resp.blob()
  }

  async function uploadFile(file) {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch(`${BASE_URL}/api/upload`, {
      method: 'POST',
      body: form,
    })
    if (!resp.ok) throw new Error(`uploadFile failed: ${resp.status}`)
    return await resp.json()
  }

  return { getMesh, getScalar, downloadFile, uploadFile }
}
