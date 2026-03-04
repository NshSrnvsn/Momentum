import { useEffect, useMemo, useState } from 'react'

const HABITS_KEY   = 'habitTracker.habits'
const CHECKINS_KEY = 'habitTracker.checkins'
const GOALS_KEY    = 'habitTracker.goals'

const todayISO = new Date().toISOString().slice(0, 10)
const DEFAULT_COLORS = ['#2563eb', '#16a34a', '#d97706', '#db2777', '#7c3aed', '#0891b2', '#ea580c']

/* ─── storage ─────────────────────────────────────────────── */
function readStorage(key, fallback) {
  try {
    const v = localStorage.getItem(key)
    return v ? JSON.parse(v) : fallback
  } catch { return fallback }
}

/* ─── date helpers ─────────────────────────────────────────── */
function isoToLocal(iso) {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(y, m - 1, d)
}

function addDays(iso, n) {
  const d = isoToLocal(iso)
  d.setDate(d.getDate() + n)
  return d.toISOString().slice(0, 10)
}

function dateKey(year, month, day) {
  return `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
}

// Returns the Monday ISO for the week that contains `iso`
function getMondayOf(iso) {
  const d = isoToLocal(iso)
  const dow = d.getDay()               // 0=Sun … 6=Sat
  const diff = dow === 0 ? -6 : 1 - dow
  d.setDate(d.getDate() + diff)
  return d.toISOString().slice(0, 10)
}

// End of week = Sunday, but capped at today for the current week
function getWeekEnd(mondayISO) {
  const sunday = addDays(mondayISO, 6)
  return sunday > todayISO ? todayISO : sunday
}

function datesInRange(start, end) {
  const out = []
  let cur = start
  while (cur <= end) { out.push(cur); cur = addDays(cur, 1) }
  return out
}

// All Mondays from the start of last month up to the current week Monday
function getAvailableWeeks() {
  const today  = isoToLocal(todayISO)
  const curMon = getMondayOf(todayISO)

  const anchorISO = new Date(today.getFullYear(), today.getMonth() - 1, 1)
    .toISOString().slice(0, 10)
  let cursor = getMondayOf(anchorISO)
  if (cursor < anchorISO) cursor = addDays(cursor, 7)

  const weeks = []
  while (cursor <= curMon) { weeks.push(cursor); cursor = addDays(cursor, 7) }
  return weeks
}

function formatWeekLabel(mondayISO) {
  const end = getWeekEnd(mondayISO)
  const fmt = (iso) => { const [y,m,d] = iso.split('-'); return `${d}/${m}/${y}` }
  const lbl = `${fmt(mondayISO)} – ${fmt(end)}`
  return mondayISO === getMondayOf(todayISO) ? `${lbl}  (this week)` : lbl
}

/* ─── month / calendar helpers ─────────────────────────────── */
function monthMeta(date) {
  const year  = date.getFullYear()
  const month = date.getMonth()
  return {
    year,
    month,
    totalDays:    new Date(year, month + 1, 0).getDate(),
    firstWeekDay: new Date(year, month, 1).getDay()
  }
}

/* ─── checkin helpers ──────────────────────────────────────── */
function normalizeEntry(raw) {
  if (typeof raw === 'boolean') return { progress: raw ? 100 : 0, note: '' }
  return {
    progress: typeof raw?.progress === 'number' ? raw.progress : 0,
    note:     typeof raw?.note     === 'string'  ? raw.note     : ''
  }
}

function getEntry(checkins, date, habitId) {
  return normalizeEntry(checkins[date]?.[habitId])
}

function loggedHabitsForDay(dayRecord, habits) {
  if (!dayRecord) return []
  return habits
    .map(habit => ({ habit, entry: normalizeEntry(dayRecord[habit.id]) }))
    .filter(({ entry }) => entry.progress > 0)
}

// Returns { habitId: occurrenceCount } over an array of ISO date strings
function tallyHabits(checkins, dates) {
  const out = {}
  for (const date of dates) {
    const rec = checkins[date]
    if (!rec) continue
    for (const [id, raw] of Object.entries(rec)) {
      if (normalizeEntry(raw).progress > 0) out[id] = (out[id] || 0) + 1
    }
  }
  return out
}

/* ─── SummaryRow component (outside App to avoid remounts) ─── */
function SummaryRow({ habit, count, target, periodLabel }) {
  const met = target > 0 && count >= target
  return (
    <div className={`summary-row${met ? ' goal-met' : ''}`}>
      <span className="habit-color" style={{ background: habit.color }} />
      <span className="summary-name">{habit.name}</span>
      <span className="summary-count">{count}× logged</span>
      {target > 0 && (
        <span className="summary-goal">
          Goal: {target}×{periodLabel}
          {met && <span className="goal-badge"> ✓</span>}
        </span>
      )}
      {met && <span className="party-burst" aria-hidden="true">🎉</span>}
    </div>
  )
}

export default function App() {
  const [habits,    setHabits]    = useState(() => readStorage(HABITS_KEY,   []))
  const [checkins,  setCheckins]  = useState(() => readStorage(CHECKINS_KEY, {}))
  const [goals,     setGoals]     = useState(() => readStorage(GOALS_KEY,    {}))

  const [newHabit,      setNewHabit]      = useState('')
  const [newHabitColor, setNewHabitColor] = useState(DEFAULT_COLORS[0])
  const [pendingDup,    setPendingDup]    = useState(null)

  const [selectedDate,  setSelectedDate]  = useState(todayISO)
  const [dayModalOpen,  setDayModalOpen]  = useState(false)
  const [summaryType,   setSummaryType]   = useState(null) // null | 'weekly' | 'monthly' | 'goals'

  const [selectedWeek,  setSelectedWeek]  = useState(() => getMondayOf(todayISO))
  const [summaryMonth,  setSummaryMonth]  = useState(() => {
    const n = new Date()
    return `${n.getFullYear()}-${String(n.getMonth() + 1).padStart(2, '0')}`
  })
  const [calendarDate, setCalendarDate] = useState(() => {
    const n = new Date(); return new Date(n.getFullYear(), n.getMonth(), 1)
  })

  const { year, month, totalDays, firstWeekDay } = useMemo(() => monthMeta(calendarDate), [calendarDate])

  const anyModalOpen = dayModalOpen || summaryType !== null
  useEffect(() => {
    document.body.style.overflow = anyModalOpen ? 'hidden' : ''
    return () => { document.body.style.overflow = '' }
  }, [anyModalOpen])

  /* ── weekly data ── */
  const availableWeeks = useMemo(() => getAvailableWeeks(), [])
  const weekEnd   = useMemo(() => getWeekEnd(selectedWeek), [selectedWeek])
  const weekDates = useMemo(() => datesInRange(selectedWeek, weekEnd), [selectedWeek, weekEnd])
  const weekTally = useMemo(() => tallyHabits(checkins, weekDates), [checkins, weekDates])

  /* ── monthly data ── */
  const [smYear, smMonth] = summaryMonth.split('-').map(Number)
  const monthDayCount = new Date(smYear, smMonth, 0).getDate()
  const monthDates = useMemo(() => {
    const out = []
    for (let d = 1; d <= monthDayCount; d++) out.push(dateKey(smYear, smMonth - 1, d))
    return out
  }, [summaryMonth])
  const monthTally   = useMemo(() => tallyHabits(checkins, monthDates), [checkins, monthDates])
  const weeksInMonth = Math.ceil(monthDayCount / 7)

  const loggedToday = loggedHabitsForDay(checkins[selectedDate], habits)

  /* ── persist ── */
  function saveHabits(next)   { setHabits(next);   localStorage.setItem(HABITS_KEY,   JSON.stringify(next)) }
  function saveCheckins(next) { setCheckins(next);  localStorage.setItem(CHECKINS_KEY, JSON.stringify(next)) }
  function saveGoals(next)    { setGoals(next);     localStorage.setItem(GOALS_KEY,    JSON.stringify(next)) }

  /* ── habit CRUD ── */
  function addHabit(force = false) {
    const name = newHabit.trim()
    if (!name) return
    const dup = habits.some(h => h.name.trim().toLowerCase() === name.toLowerCase())
    if (dup && !force) { setPendingDup(name); return }
    setPendingDup(null)
    saveHabits([...habits, { id: crypto.randomUUID(), name, color: newHabitColor }])
    setNewHabit('')
    setNewHabitColor(DEFAULT_COLORS[(DEFAULT_COLORS.indexOf(newHabitColor) + 1) % DEFAULT_COLORS.length])
  }

  function removeHabit(id) {
    const nextCheckins = { ...checkins }
    for (const day in nextCheckins) {
      if (nextCheckins[day]?.[id] !== undefined) {
        const m = { ...nextCheckins[day] }; delete m[id]; nextCheckins[day] = m
      }
    }
    saveHabits(habits.filter(h => h.id !== id))
    saveCheckins(nextCheckins)
  }

  function updateProgress(habitId, progress) {
    const existing = getEntry(checkins, selectedDate, habitId)
    saveCheckins({ ...checkins, [selectedDate]: { ...(checkins[selectedDate] || {}), [habitId]: { ...existing, progress } } })
  }

  function updateNote(habitId, note) {
    const existing = getEntry(checkins, selectedDate, habitId)
    saveCheckins({ ...checkins, [selectedDate]: { ...(checkins[selectedDate] || {}), [habitId]: { ...existing, note } } })
  }

  function setGoal(habitId, weeklyTarget) {
    saveGoals({ ...goals, [habitId]: { weeklyTarget: Math.max(0, Number(weeklyTarget) || 0) } })
  }

  function moveMonth(offset) { setCalendarDate(new Date(year, month + offset, 1)) }

  /* ── calendar cells ── */
  const dayCells = []
  for (let i = 0; i < firstWeekDay; i++) dayCells.push(<div className="day empty" key={`e-${i}`} />)
  for (let day = 1; day <= totalDays; day++) {
    const key    = dateKey(year, month, day)
    const logged = loggedHabitsForDay(checkins[key], habits)
    dayCells.push(
      <button key={key} type="button"
        className={`day${selectedDate === key ? ' selected' : ''}`}
        onClick={() => { setSelectedDate(key); setDayModalOpen(true) }}
        title={key}
      >
        <span className="day-number">{day}</span>
        {logged.length === 0 && <span className="day-empty-fill" />}
        {logged.length === 1 && <span className="day-full-fill" style={{ background: logged[0].habit.color }} />}
        {logged.length > 1 && (
          <span className="day-multi-fill">
            {logged.map(({ habit }) => <i key={habit.id} style={{ background: habit.color }} />)}
          </span>
        )}
      </button>
    )
  }

  /* ── render ── */
  return (
    <main className="app">
      <h1>Habit Tracker</h1>

      {/* toolbar */}
      <div className="toolbar">
        <button type="button" className="outline" onClick={() => setSummaryType('weekly')}>📅 Weekly Summary</button>
        <button type="button" className="outline" onClick={() => setSummaryType('monthly')}>📆 Monthly Summary</button>
        <button type="button" className="outline" onClick={() => setSummaryType('goals')}>🎯 Set Goals</button>
      </div>

      {/* habits card */}
      <section className="card">
        <h2>Habits for {selectedDate}</h2>

        <div className="row">
          <input value={newHabit} placeholder="Add a new habit"
            onKeyDown={(e) => e.key === 'Enter' && addHabit()}
            onChange={(e) => { setNewHabit(e.target.value); setPendingDup(null) }}
          />
          <input className="color-input" type="color" value={newHabitColor}
            onChange={(e) => setNewHabitColor(e.target.value)} title="Habit color" />
          <button type="button" onClick={() => addHabit()}>Add</button>
        </div>

        {pendingDup && (
          <div className="duplicate-warning">
            <span>⚠️ <strong>{pendingDup}</strong> already exists. Are you sure you haven&apos;t logged this yet?</span>
            <div className="row">
              <button type="button" onClick={() => addHabit(true)}>Add Anyway</button>
              <button type="button" className="ghost" onClick={() => setPendingDup(null)}>Cancel</button>
            </div>
          </div>
        )}

        <div className="habit-list">
          {habits.length === 0 && <p className="muted">No habits yet. Add one above.</p>}
          {habits.map((habit) => {
            const entry = getEntry(checkins, selectedDate, habit.id)
            return (
              <div className="habit-item" key={habit.id}>
                <div className="habit-head">
                  <span className="habit-color" style={{ background: habit.color }} />
                  <strong>{habit.name}</strong>
                  <button type="button" className="danger" onClick={() => removeHabit(habit.id)}>Remove</button>
                </div>

                <div className="habit-progress-row">
                  <div className="pie" style={{
                    background: `conic-gradient(${habit.color} ${entry.progress * 3.6}deg, #e5e7eb 0deg)`
                  }}>
                    <span>{entry.progress}%</span>
                  </div>
                  <input type="range" min="0" max="100" value={entry.progress}
                    onChange={(e) => updateProgress(habit.id, Number(e.target.value))} />
                </div>

                <textarea rows={2} placeholder="Notes for this habit on selected date…"
                  value={entry.note} onChange={(e) => updateNote(habit.id, e.target.value)} />
              </div>
            )
          })}
        </div>
      </section>

      {/* calendar */}
      <section className="card">
        <div className="calendar-header">
          <h2>Calendar Overview</h2>
          <div className="row">
            <button type="button" onClick={() => moveMonth(-1)}>Prev</button>
            <strong>{calendarDate.toLocaleString(undefined, { month: 'long', year: 'numeric' })}</strong>
            <button type="button" onClick={() => moveMonth(1)}>Next</button>
          </div>
        </div>
        <div className="weekdays">
          {['Sun','Mon','Tue','Wed','Thu','Fri','Sat'].map(n => <div key={n} className="weekday">{n}</div>)}
        </div>
        <div className="calendar-grid">{dayCells}</div>
        <div className="legend">
          <span><i className="dot none" /> No habits logged</span>
          <span><i className="dot marker" /> Single habit fills box</span>
          <span><i className="dot marker" /> Multi habit uses colour strips</span>
        </div>
      </section>

      {/* day detail modal */}
      {dayModalOpen && (
        <div className="modal-overlay" onClick={() => setDayModalOpen(false)}>
          <div className="modal" onClick={e => e.stopPropagation()}>
            <h3>Logged Habits • {selectedDate}</h3>
            {loggedToday.length === 0
              ? <p className="muted">No habits logged for this day.</p>
              : <div className="modal-list">
                  {loggedToday.map(({ habit, entry }) => (
                    <div key={habit.id} className="modal-item">
                      <div className="row">
                        <span className="habit-color" style={{ background: habit.color }} />
                        <strong>{habit.name}</strong>
                        <span className="muted">{entry.progress}%</span>
                      </div>
                      {entry.note && <p>{entry.note}</p>}
                    </div>
                  ))}
                </div>
            }
            <button type="button" onClick={() => setDayModalOpen(false)}>Close</button>
          </div>
        </div>
      )}

      {/* weekly summary modal */}
      {summaryType === 'weekly' && (
        <div className="modal-overlay" onClick={() => setSummaryType(null)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
            <h3>📅 Weekly Summary</h3>

            <div className="row">
              <label htmlFor="week-sel"><strong>Week:</strong></label>
              <select id="week-sel" value={selectedWeek} onChange={e => setSelectedWeek(e.target.value)}>
                {availableWeeks.map(mon => (
                  <option key={mon} value={mon}>{formatWeekLabel(mon)}</option>
                ))}
              </select>
            </div>
            <p className="muted">{selectedWeek} → {weekEnd} &nbsp;({weekDates.length} days)</p>

            {habits.length === 0
              ? <p className="muted">No habits yet.</p>
              : <div className="modal-list">
                  {habits.map(habit => (
                    <SummaryRow key={habit.id} habit={habit}
                      count={weekTally[habit.id] || 0}
                      target={goals[habit.id]?.weeklyTarget || 0}
                      periodLabel="/wk"
                    />
                  ))}
                </div>
            }
            <button type="button" onClick={() => setSummaryType(null)}>Close</button>
          </div>
        </div>
      )}

      {/* monthly summary modal */}
      {summaryType === 'monthly' && (
        <div className="modal-overlay" onClick={() => setSummaryType(null)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
            <h3>📆 Monthly Summary</h3>

            <div className="row">
              <label htmlFor="month-sel"><strong>Month:</strong></label>
              <input id="month-sel" type="month" value={summaryMonth}
                onChange={e => setSummaryMonth(e.target.value)} style={{ width: 'auto' }} />
            </div>
            <p className="muted">{monthDayCount} days · ~{weeksInMonth} weeks</p>

            {habits.length === 0
              ? <p className="muted">No habits yet.</p>
              : <div className="modal-list">
                  {habits.map(habit => (
                    <SummaryRow key={habit.id} habit={habit}
                      count={monthTally[habit.id] || 0}
                      target={goals[habit.id]?.weeklyTarget ? goals[habit.id].weeklyTarget * weeksInMonth : 0}
                      periodLabel="/mo"
                    />
                  ))}
                </div>
            }
            <button type="button" onClick={() => setSummaryType(null)}>Close</button>
          </div>
        </div>
      )}

      {/* goals modal */}
      {summaryType === 'goals' && (
        <div className="modal-overlay" onClick={() => setSummaryType(null)}>
          <div className="modal modal-wide" onClick={e => e.stopPropagation()}>
            <h3>🎯 Set Goals</h3>
            <p className="muted">
              Set how many times <strong>per week</strong> you want to complete each habit.
              Monthly summaries scale this automatically. In any summary, hover a row that
              hit its goal to celebrate! 🎉
            </p>

            {habits.length === 0
              ? <p className="muted">No habits yet. Add habits first.</p>
              : <div className="modal-list">
                  {habits.map(habit => (
                    <div key={habit.id} className="modal-item goal-item">
                      <div className="row">
                        <span className="habit-color" style={{ background: habit.color }} />
                        <strong>{habit.name}</strong>
                        {goals[habit.id]?.weeklyTarget > 0 &&
                          <span className="muted">({goals[habit.id].weeklyTarget}×/wk)</span>}
                      </div>
                      <div className="row goal-input-row">
                        <label>Times per week:</label>
                        <input type="number" min="0" max="7" style={{ width: '80px' }}
                          value={goals[habit.id]?.weeklyTarget ?? ''}
                          placeholder="e.g. 3"
                          onChange={e => setGoal(habit.id, e.target.value)}
                        />
                      </div>
                    </div>
                  ))}
                </div>
            }
            <button type="button" onClick={() => setSummaryType(null)}>Save &amp; Close</button>
          </div>
        </div>
      )}
    </main>
  )
}
