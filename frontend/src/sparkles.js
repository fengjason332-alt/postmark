// A light dusting of pigment flecks around the globe's rim: a puff where the pointer
// first touches the globe, then a faint shimmer along the edge while it stays there.
// Drawn on a 2D canvas over the globe; the loop only runs while flecks are alive.
const COLORS = ['184,134,42', '168,71,58', '52,85,122', '79,107,82', '243,239,231']

export function createSparkles(canvas) {
  const ctx = canvas.getContext('2d')
  const flecks = []
  let raf = 0
  let rim = null // { x, y, r } of the globe on screen, refreshed by the caller
  let hovering = false
  let last = 0
  const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  function size() {
    const dpr = Math.min(2, window.devicePixelRatio || 1)
    canvas.width = canvas.clientWidth * dpr
    canvas.height = canvas.clientHeight * dpr
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  function spawn(angle, spread, speed) {
    if (!rim) return
    const a = angle + (Math.random() - 0.5) * spread
    const d = rim.r * (0.97 + Math.random() * 0.08)
    flecks.push({
      x: rim.x + Math.cos(a) * d,
      y: rim.y + Math.sin(a) * d,
      vx: Math.cos(a) * speed * (0.3 + Math.random()),
      vy: Math.sin(a) * speed * (0.3 + Math.random()) - 0.08,
      life: 0,
      max: 900 + Math.random() * 900,
      size: 0.6 + Math.random() * 1.8,
      color: COLORS[(Math.random() * COLORS.length) | 0],
    })
  }

  function frame(now) {
    const dt = Math.min(48, now - (last || now))
    last = now
    if (hovering && rim && Math.random() < 0.35) spawn(Math.random() * Math.PI * 2, 0, 0.12)
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight)
    for (let i = flecks.length - 1; i >= 0; i--) {
      const f = flecks[i]
      f.life += dt
      if (f.life > f.max) {
        flecks.splice(i, 1)
        continue
      }
      f.x += f.vx * dt * 0.06
      f.y += f.vy * dt * 0.06
      const t = f.life / f.max
      const alpha = Math.sin(Math.PI * t) * 0.75 // fade in, then out
      ctx.fillStyle = `rgba(${f.color},${alpha.toFixed(3)})`
      ctx.beginPath()
      ctx.arc(f.x, f.y, f.size, 0, Math.PI * 2)
      ctx.fill()
    }
    raf = flecks.length || hovering ? requestAnimationFrame(frame) : 0
    if (!raf) last = 0
  }

  function run() {
    if (!raf) raf = requestAnimationFrame(frame)
  }

  size()
  return {
    resize: size,
    setRim(r) {
      rim = r
    },
    // The pointer has just come onto the globe at (x, y): a small puff from that side.
    enter(x, y) {
      if (reduced || !rim) return
      hovering = true
      const angle = Math.atan2(y - rim.y, x - rim.x)
      for (let i = 0; i < 26; i++) spawn(angle, 1.1, 0.5)
      run()
    },
    leave() {
      hovering = false
    },
    dispose() {
      cancelAnimationFrame(raf)
    },
  }
}
