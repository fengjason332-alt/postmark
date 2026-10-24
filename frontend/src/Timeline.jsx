import { useEffect, useRef, useState } from 'react'
import { DRAW_MS, dotDate, isoDay, tripColor } from './data.js'

// Bottom timeline (shown only for a replay): drag to replay trips in order, or press play to
// watch them unfold one by one. The bar runs on the same story clock as the lines on the globe
// (see storyline in data.js): each leg owns an equal stretch, so wherever the knob is, the line
// is drawn exactly that far. Each trip is a small dot; its title shows on hover or focus, and
// for the named trip: the one the replay is in, otherwise the one the user last opened.
export default function Timeline({ trips, story, cursor, selectedId, onCursor, onOpen, onPlaying, onClose }) {
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
  // Trips are in story order, so the last one that has started is the one the replay is in.
  const current = cursor === null ? null : trips.reduce((hit, t) => (startOf(t) <= cursor ? t : hit), null)
  const named = current?.id ?? selectedId

  return (
    <div className="timeline">
      <button className="play" onClick={() => setPlaying((p) => !p)} aria-label={playing ? 'Pause' : cursor === null ? 'Replay from the start' : 'Resume'}>
        {playing ? '❚❚' : '▶'}
      </button>
      <div className="track">
        <div className="ticks">
          {/* --shift slides each title so the first one starts at its dot and the last one ends at it. */}
          {trips.map((t) => (
            <button
              key={t.id}
              className={`tick ${startOf(t) <= value ? 'on' : ''} ${t.id === named ? 'selected' : ''}`}
              style={{ left: `${pct(t)}%`, '--c': tripColor(t), '--shift': `${-pct(t)}%` }}
              onClick={() => onOpen(t)}
              aria-label={`${t.title}, ${dotDate(t.start_date)}`}
              aria-current={t.id === named ? 'true' : undefined}
            >
              <span className="tick-label" aria-hidden="true">{t.title}</span>
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
      <button className="replay-close" onClick={onClose} aria-label="Close replay">×</button>
      <Player playing={playing} max={max} cursor={cursor} onCursor={onCursor} onDone={() => setPlaying(false)} timer={timer} />
    </div>
  )
}

// Runs the replay: the knob moves at one even speed, one leg's stretch per DRAW_MS, updated
// every frame. The globe reads the same position, so bar and lines can't drift apart.
function Player({ playing, max, cursor, onCursor, onDone, timer }) {
  const latest = useRef(cursor)
  latest.current = cursor
  useEffect(() => {
    if (!playing) return
    // Resume from where it was paused (or dragged to); from the start when it had finished.
    const at = latest.current
    const from = at !== null && at > 0 && at < max ? at : 0
    const start = performance.now() - from * DRAW_MS
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
    onCursor(from)
    timer.current = requestAnimationFrame(step)
    return () => cancelAnimationFrame(timer.current)
  }, [playing]) // eslint-disable-line react-hooks/exhaustive-deps
  return null
}
