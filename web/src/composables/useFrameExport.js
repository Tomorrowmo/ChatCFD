// Frame-sequence export: drives a multi-frame viewer through every frame,
// captures each as PNG, and packages the result as a ZIP of PNGs or a GIF.
//
// The caller wires it up by:
//   1. passing a ref to the VtkViewer component (must expose captureFrame())
//   2. passing the currentFrame + frameCount refs it already owns
//   3. calling notifyLoaded() from the viewer's `loaded` event
//
// Frame stepping waits on the viewer's `loaded` event so capture never
// races an unfinished render.

import { ref } from 'vue'
import JSZip from 'jszip'
import { GIFEncoder, quantize, applyPalette } from 'gifenc'

export function useFrameExport({ viewerRef, currentFrame, frameCount }) {
  const exporting = ref(false)
  const progress = ref(0)        // 0..1
  const exportLabel = ref('')    // 'PNG 序列' | 'GIF'
  let cancelled = false
  let loadedResolve = null

  // Called by the parent from the viewer's `loaded` event.
  function notifyLoaded() {
    if (loadedResolve) {
      const r = loadedResolve
      loadedResolve = null
      r()
    }
  }

  function cancel() { cancelled = true }

  // Step through every frame; call onFrame(index, pngDataUrl) for each.
  async function captureAll(onFrame) {
    const n = frameCount.value
    for (let i = 0; i < n; i++) {
      if (cancelled) break
      // Only wait for a reload if we actually change the frame — setting
      // currentFrame to its current value emits no change → no `loaded`.
      if (currentFrame.value !== i) {
        const wait = new Promise((res) => { loadedResolve = res })
        currentFrame.value = i
        await wait
      }
      await new Promise((r) => setTimeout(r, 60))  // let the render settle
      const png = await viewerRef.value?.captureFrame()
      if (png) await onFrame(i, png)
      progress.value = (i + 1) / n
    }
  }

  async function exportPNG() {
    if (exporting.value) return
    exporting.value = true
    cancelled = false
    progress.value = 0
    exportLabel.value = 'PNG 序列'
    try {
      const zip = new JSZip()
      await captureAll((i, png) => {
        zip.file(`frame_${String(i).padStart(4, '0')}.png`, png.split(',')[1], { base64: true })
      })
      if (!cancelled) {
        const blob = await zip.generateAsync({ type: 'blob' })
        triggerDownload(blob, 'frames.zip')
      }
    } catch (e) {
      console.error('[useFrameExport] PNG export failed:', e)
    } finally {
      exporting.value = false
    }
  }

  async function exportGIF(fps = 5) {
    if (exporting.value) return
    exporting.value = true
    cancelled = false
    progress.value = 0
    exportLabel.value = 'GIF'
    try {
      const gif = GIFEncoder()
      const delay = Math.round(1000 / fps)
      await captureAll(async (i, png) => {
        const { data, width, height } = await pngToImageData(png)
        const palette = quantize(data, 256)
        const index = applyPalette(data, palette)
        gif.writeFrame(index, width, height, { palette, delay })
      })
      if (!cancelled) {
        gif.finish()
        triggerDownload(new Blob([gif.bytes()], { type: 'image/gif' }), 'animation.gif')
      }
    } catch (e) {
      console.error('[useFrameExport] GIF export failed:', e)
    } finally {
      exporting.value = false
    }
  }

  // Client-side video export. Captures every frame as PNG, then plays them
  // back onto an offscreen canvas at a fixed cadence while MediaRecorder
  // records the canvas stream. Output is WEBM (VP9/VP8) — universally
  // playable in browsers; transcode to MP4 externally if needed.
  async function exportWEBM(fps = 10) {
    if (exporting.value) return
    if (typeof MediaRecorder === 'undefined') {
      console.error('[useFrameExport] MediaRecorder unavailable in this browser')
      return
    }
    exporting.value = true
    cancelled = false
    progress.value = 0
    exportLabel.value = 'WEBM 采集'
    try {
      // Pass 1 — capture frames as PNG data URLs (strings stay memory-light)
      const pngs = []
      await captureAll((i, png) => { pngs.push(png) })
      if (cancelled || !pngs.length) return

      // Pass 2 — replay onto a canvas at fixed cadence, record the stream
      exportLabel.value = 'WEBM 编码'
      progress.value = 0
      const first = await pngToImage(pngs[0])
      const canvas = document.createElement('canvas')
      canvas.width = first.width
      canvas.height = first.height
      const ctx = canvas.getContext('2d')
      const stream = canvas.captureStream(0)
      const track = stream.getVideoTracks()[0]
      const mime = MediaRecorder.isTypeSupported('video/webm;codecs=vp9')
        ? 'video/webm;codecs=vp9' : 'video/webm'
      const chunks = []
      const recorder = new MediaRecorder(stream, { mimeType: mime })
      recorder.ondataavailable = (e) => { if (e.data && e.data.size) chunks.push(e.data) }
      const recorderStopped = new Promise((res) => { recorder.onstop = res })
      recorder.start()

      const frameDelay = 1000 / fps
      for (let i = 0; i < pngs.length && !cancelled; i++) {
        const img = i === 0 ? first : await pngToImage(pngs[i])
        ctx.drawImage(img, 0, 0)
        if (track.requestFrame) track.requestFrame()
        await new Promise((r) => setTimeout(r, frameDelay))
        progress.value = (i + 1) / pngs.length
      }
      recorder.stop()
      await recorderStopped
      if (!cancelled && chunks.length) {
        triggerDownload(new Blob(chunks, { type: 'video/webm' }), 'animation.webm')
      }
    } catch (e) {
      console.error('[useFrameExport] WEBM export failed:', e)
    } finally {
      exporting.value = false
    }
  }

  return { exporting, progress, exportLabel, notifyLoaded, cancel, exportPNG, exportGIF, exportWEBM }
}

function triggerDownload(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

// Decode a PNG data URL to an HTMLImageElement.
function pngToImage(dataUrl) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = dataUrl
  })
}

// Decode a PNG data URL to raw RGBA pixels (gifenc needs ImageData).
async function pngToImageData(dataUrl) {
  const img = await pngToImage(dataUrl)
  const canvas = document.createElement('canvas')
  canvas.width = img.width
  canvas.height = img.height
  const ctx = canvas.getContext('2d')
  ctx.drawImage(img, 0, 0)
  const id = ctx.getImageData(0, 0, img.width, img.height)
  return { data: id.data, width: img.width, height: img.height }
}
