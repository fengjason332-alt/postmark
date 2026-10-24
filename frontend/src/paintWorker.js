// Web Worker: runs the heavy pixel work off the main thread so the globe and the page
// stay responsive while a logbook full of photos is being painted.
import { paintPixels } from './paintCore.js'

self.onmessage = (e) => {
  const { id, w, h, buffer } = e.data
  const px = new Uint8ClampedArray(buffer)
  paintPixels(px, w, h)
  self.postMessage({ id, buffer }, [buffer])
}
