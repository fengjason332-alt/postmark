import { useEffect, useRef, useState } from 'react'
import { dotDate, tripColor } from './data.js'

const DAY = 86400000
const toDay = (iso) => Math.round(new Date(iso + 'T00:00:00Z').getTime() / DAY)
const fromDay = (n) => new Date(n * DAY).toISOString().slice(0, 10)

// Bottom timeline: drag to replay trips in order, or press play to watch the lines fly out.
export default function Timeline({ trips, cursor, onCursor, onOpen }) {
  const [playing, setPlaying] = useState(false)
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
      <Player playing={playing} min={min} max={max} onCursor={onCursor} onDone={() => setPlaying(false)} timer={timer} />
    </div>
  )
}

// Runs the replay: a blank globe, then each trip's ink line in date order over ~9 seconds.
function Player({ playing, min, max, onCursor, onDone, timer }) {
  useEffect(() => {
    if (!playing) return
    const start = performance.now()
    const total = 9000
    onCursor(fromDay(min))
    const step = () => {
      const t = Math.min(1, (performance.now() - start) / total)
      const day = Math.round(min + (max - min) * t)
      if (t >= 1) {
        onCursor(null)
        onDone()
        return
      }
      onCursor(fromDay(day))
      timer.current = requestAnimationFrame(step)
    }
    timer.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(timer.current)
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}
