import { useEffect, useRef, useState } from 'react'
import { DRAW_MS, dotDate, isoDay, tripColor } from './data.js'

// Bottom timeline: drag to replay trips in order, or press play to watch them unfold one by one.
// The bar runs on the same story clock as the lines on the globe (see storyline in data.js):
// each leg owns an equal stretch, so wherever the knob is, the line is drawn exactly that far.
export default function Timeline({ trips, story, cursor, onCursor, onOpen, onPlaying }) {
  const [playing, setPlayingState] = useState(false)
  const setPlaying = (p) => {
    const next = typeof p === 'function' ? p(playing) : p
    setPlayingState(next)
    onPlaying(next)
  }
  const timer = useRef(0)
  if (!trips.length) return <div className="timeline empty" />

  const max = story.total
  const value = cursor ?? max
  const startOf = (t) => story.legs[t.id][0].start
  const pct = (t) => (startOf(t) / max) * 100

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
              className={`tick ${startOf(t) <= value ? 'on' : ''}`}
              style={{ left: `${pct(t)}%`, '--c': tripColor(t), '--shift': `${-pct(t)}%` }}
              onClick={() => onOpen(t)}
              title={`${t.title} · ${dotDate(t.start_date)}`}
            >
              <span>{t.title}</span>
            </button>
          ))}
        </div>
        <input
          type="range"
          min={0}
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
          <span className="now">{cursor === null ? 'today' : dotDate(isoDay(story.dayAt(cursor)))}</span>
          <span>{dotDate(trips[trips.length - 1].end_date)}</span>
        </div>
      </div>
      <Player playing={playing} max={max} onCursor={onCursor} onDone={() => setPlaying(false)} timer={timer} />
    </div>
  )
}

// Runs the replay: the knob moves at one even speed, one leg's stretch per DRAW_MS, updated
// every frame. The globe reads the same position, so bar and lines can't drift apart.
function Player({ playing, max, onCursor, onDone, timer }) {
  useEffect(() => {
    if (!playing) return
    const start = performance.now()
    const step = (now) => {
      const pos = (now - start) / DRAW_MS
      if (pos >= max) {
        onCursor(null)
        onDone()
        return
      }
      onCursor(pos)
      timer.current = requestAnimationFrame(step)
    }
    onCursor(0)
    timer.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(timer.current)
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}
