import { useEffect, useRef, useState } from 'react'
import { dotDate, tripColor, tripDrawMs } from './data.js'

const DAY = 86400000
const toDay = (iso) => Math.round(new Date(iso + 'T00:00:00Z').getTime() / DAY)
const fromDay = (n) => new Date(n * DAY).toISOString().slice(0, 10)

// Bottom timeline: drag to replay trips in order, or press play to watch them unfold one by one.
export default function Timeline({ trips, cursor, onCursor, onOpen, onPlaying }) {
  const [playing, setPlayingState] = useState(false)
  const setPlaying = (p) => {
    const next = typeof p === 'function' ? p(playing) : p
    setPlayingState(next)
    onPlaying(next)
  }
  const timer = useRef(0)
  if (!trips.length) return <div className="timeline empty" />

  const min = toDay(trips[0].start_date) - 3
  const max = toDay(trips[trips.length - 1].end_date) + 3
  const value = cursor ? toDay(cursor) : max
  const pct = (iso) => ((toDay(iso) - min) / (max - min)) * 100

  return (
    <div className="timeline">
      <button className="play" onClick={() => setPlaying((p) => !p)} aria-label={playing ? 'Pause' : 'Replay from the start'}>
        {playing ? '❚❚' : '▶'}
      </button>
      <div className="track">
        <div className="ticks">
          {trips.map((t) => (
            <button
              key={t.id}
              className={`tick ${toDay(t.start_date) <= value ? 'on' : ''}`}
              style={{ left: `${pct(t.start_date)}%`, '--c': tripColor(t), '--shift': `${-pct(t.start_date)}%` }}
              onClick={() => onOpen(t)}
              title={`${t.title} · ${dotDate(t.start_date)}`}
            >
              <span>{t.title}</span>
            </button>
          ))}
        </div>
        <input
          type="range"
          min={min}
          max={max}
          value={value}
          onChange={(e) => {
            setPlaying(false)
            const v = +e.target.value
            onCursor(v >= max ? null : fromDay(v))
          }}
          aria-label="Timeline"
        />
        <div className="ends">
          <span>{dotDate(trips[0].start_date)}</span>
          <span className="now">{cursor ? dotDate(cursor) : 'today'}</span>
          <span>{dotDate(trips[trips.length - 1].end_date)}</span>
        </div>
      </div>
      <Player playing={playing} trips={trips} min={min} max={max} onCursor={onCursor} onDone={() => setPlaying(false)} timer={timer} />
    </div>
  )
}

// Runs the replay in date order: the cursor walks the real calendar, stopping on each
// trip for as long as its lines take to draw (the globe follows them), then moves on.
const GAP_MS = 1400 // time spent travelling the calendar between two trips

function Player({ playing, trips, min, max, onCursor, onDone, timer }) {
  useEffect(() => {
    if (!playing) return
    // Segments of [fromDay, toDay, durationMs]: the gap before each trip, then the trip itself.
    const segments = []
    let day = min
    for (const t of trips) {
      const s = toDay(t.start_date)
      const e = toDay(t.end_date)
      segments.push([day, s, GAP_MS], [s, e, tripDrawMs(t)])
      day = e
    }
    segments.push([day, max, GAP_MS])
    const total = segments.reduce((sum, seg) => sum + seg[2], 0)
    const start = performance.now()
    let shown = null
    const step = () => {
      let elapsed = performance.now() - start
      if (elapsed >= total) {
        onCursor(null)
        onDone()
        return
      }
      let seg = segments[0]
      for (seg of segments) {
        if (elapsed < seg[2]) break
        elapsed -= seg[2]
      }
      const iso = fromDay(Math.round(seg[0] + (seg[1] - seg[0]) * Math.min(1, elapsed / seg[2])))
      if (iso !== shown) onCursor((shown = iso))
      timer.current = requestAnimationFrame(step)
    }
    onCursor(fromDay(min))
    timer.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(timer.current)
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}
