import { useEffect, useRef, useState } from 'react'
import { DRAW_MS, PAUSE_MS, dayNumber, dotDate, isoDay, legTimes, tripColor } from './data.js'

// Bottom timeline: drag to replay trips in order, or press play to watch them unfold one by one.
// The cursor is a point on the day clock (fractional days); the globe draws every leg that
// has set off by then, so the bar and the lines always show the same moment.
export default function Timeline({ trips, cursor, onCursor, onOpen, onPlaying }) {
  const [playing, setPlayingState] = useState(false)
  const setPlaying = (p) => {
    const next = typeof p === 'function' ? p(playing) : p
    setPlayingState(next)
    onPlaying(next)
  }
  const timer = useRef(0)
  if (!trips.length) return <div className="timeline empty" />

  const min = dayNumber(trips[0].start_date) - 3
  const max = dayNumber(trips[trips.length - 1].end_date) + 3
  const value = cursor ?? max
  const pct = (iso) => ((dayNumber(iso) - min) / (max - min)) * 100

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
              className={`tick ${legTimes(t)[0].depart <= value ? 'on' : ''}`}
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
          step="any"
          value={value}
          onChange={(e) => {
            setPlaying(false)
            const v = +e.target.value
            onCursor(v >= max ? null : v)
          }}
          aria-label="Timeline"
        />
        <div className="ends">
          <span>{dotDate(trips[0].start_date)}</span>
          <span className="now">{cursor === null ? 'today' : dotDate(isoDay(cursor))}</span>
          <span>{dotDate(trips[trips.length - 1].end_date)}</span>
        </div>
      </div>
      <Player playing={playing} trips={trips} min={min} max={max} onCursor={onCursor} onDone={() => setPlaying(false)} timer={timer} />
    </div>
  )
}

// Runs the replay on the same clock the globe uses: the cursor walks the calendar to each
// trip, then moves through every leg exactly while that leg draws, rests while the stamp
// lands, and sets off again. The camera follows each leg as it starts.
const GAP_MS = 1400 // time spent travelling the calendar between two trips

function Player({ playing, trips, min, max, onCursor, onDone, timer }) {
  useEffect(() => {
    if (!playing) return
    // Segments of [fromDay, toDay, durationMs].
    const segments = []
    let day = min
    for (const t of trips) {
      const legs = legTimes(t)
      segments.push([day, legs[0].depart, GAP_MS])
      legs.forEach((leg, i) => {
        segments.push([leg.depart, leg.arrive, DRAW_MS])
        segments.push([leg.arrive, legs[i + 1]?.depart ?? leg.arrive, PAUSE_MS])
      })
      day = legs[legs.length - 1].arrive
    }
    segments.push([day, max, GAP_MS])
    const total = segments.reduce((sum, seg) => sum + seg[2], 0)
    const start = performance.now()
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
      onCursor(seg[0] + (seg[1] - seg[0]) * Math.min(1, elapsed / seg[2]))
      timer.current = requestAnimationFrame(step)
    }
    onCursor(min)
    timer.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(timer.current)
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}
