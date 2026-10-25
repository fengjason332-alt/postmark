// Turns a photo into a small gouache-style painting, entirely in the browser:
// soften, cut into a handful of flat colour masses, push them toward a muted
// palette, add brush texture and a ragged painted edge on cream paper.
// Nothing leaves the device; results are cached per image URL.
import { useEffect, useState } from 'react'
import PaintWorker from './paintWorker.js?worker&inline'

const cache = new Map() // src -> Promise<dataURL>
const done = new Map() // src -> dataURL, once finished, so a second look shows it on the first frame
const MAX = 520 // longest side of the painting, in pixels

export function paint(src) {
  if (!cache.has(src)) cache.set(src, load(src).then(render).then((u) => { done.set(src, u); return u }))
  return cache.get(src)
}

// Start the painting and download the photo ahead of a click (e.g. on hover), so the viewer opens ready.
export function prepare(src) {
  paint(src).catch(() => {})
}

// React helper: the painted data URL, or null while it is still being made.
// Pass enabled=false to hold off (e.g. until the photo scrolls into view).
export function usePainting(src, enabled = true) {
  const [url, setUrl] = useState(() => done.get(src) ?? null)
  useEffect(() => {
    if (!enabled) return undefined
    if (done.has(src)) { setUrl(done.get(src)); return undefined }
    let live = true
    paint(src).then((u) => live && setUrl(u)).catch(() => live && setUrl(src))
    return () => { live = false }
  }, [src, enabled])
  return url
}

function load(src) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => resolve(img)
    img.onerror = reject
    img.src = src
  })
}

function render(img) {
  const scale = Math.min(1, MAX / Math.max(img.naturalWidth, img.naturalHeight))
  const w = Math.max(8, Math.round(img.naturalWidth * scale))
  const h = Math.max(8, Math.round(img.naturalHeight * scale))
  const canvas = document.createElement('canvas')
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext('2d', { willReadFrequently: true })

  // Soften: draw small then scale back up, which blurs without ctx.filter (Safari lacks it).
  const small = document.createElement('canvas')
  small.width = Math.max(4, Math.round(w / 5))
  small.height = Math.max(4, Math.round(h / 5))
  const sctx = small.getContext('2d')
  sctx.imageSmoothingQuality = 'high'
  sctx.drawImage(img, 0, 0, small.width, small.height)
  ctx.imageSmoothingQuality = 'high'
  ctx.drawImage(small, 0, 0, w, h)
  const data = ctx.getImageData(0, 0, w, h)
  return runWorker(data.data.buffer, w, h).then((buffer) => {
    // The original buffer was handed to the worker, so build a fresh ImageData from its reply.
    ctx.putImageData(new ImageData(new Uint8ClampedArray(buffer), w, h), 0, 0)
    return canvas.toDataURL('image/jpeg', 0.88)
  })
}

// One shared worker; jobs queue up inside it and run one at a time. If workers are
// blocked (some sandboxed pages), fall back to painting on the main thread.
let worker = null
let nextId = 0
const pending = new Map()
function runWorker(buffer, w, h) {
  if (worker === false) return paintHere(buffer, w, h)
  if (!worker) {
    try {
      worker = new PaintWorker()
    } catch {
      worker = false
      return paintHere(buffer, w, h)
    }
    worker.onmessage = (e) => {
      pending.get(e.data.id)?.resolve(e.data.buffer)
      pending.delete(e.data.id)
    }
    worker.onerror = () => {
      worker = false
      for (const job of pending.values()) job.retry()
      pending.clear()
    }
  }
  const id = nextId++
  const copy = buffer.slice(0) // kept in case the worker fails and the job must be redone here
  return new Promise((resolve) => {
    pending.set(id, { resolve, retry: () => paintHere(copy, w, h).then(resolve) })
    worker.postMessage({ id, w, h, buffer }, [buffer])
  })
}

async function paintHere(buffer, w, h) {
  const { paintPixels } = await import('./paintCore.js')
  await new Promise((r) => setTimeout(r, 0)) // let the page breathe between paintings
  paintPixels(new Uint8ClampedArray(buffer), w, h)
  return buffer
}

// A short poetic title for a painting, chosen by the photo's tag and id so it stays stable.
const TITLES = {
  food: ['Where the Table Lingers', 'Bread and Slow Light', 'The Warmth Between Plates'],
  nature: ['Where the Hills Hold Still', 'Green in Repose', 'The Quiet Before Wind'],
  city: ['Where the Streets Hum', 'Corners in Repose', 'Where the Crowd Holds Its Breath'],
  night: ['Where the Lamps Stay On', 'After the Last Train', 'The Hour of Soft Light'],
  museum: ['Where the Walls Remember', 'Rooms That Keep Time', 'Where the Shadow Holds'],
  beach: ['Where the Tide Lingers', 'Hull in Repose', 'Salt and Open Air'],
  other: ['Where the Road Paused', 'Where the Shadow Holds', 'A Small Hour, Kept'],
}

export function paintingTitle(photo) {
  const tag = (photo.tags ?? []).find((t) => TITLES[t]) ?? 'other'
  let h = 0
  for (const ch of photo.id) h = (h * 31 + ch.charCodeAt(0)) | 0
  const list = TITLES[tag]
  return list[Math.abs(h) % list.length]
}
