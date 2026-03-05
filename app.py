import math
import uuid
import json
import calendar as cal_module
import streamlit.components.v1 as components
import streamlit as st
from datetime import date, timedelta
from supabase import create_client, Client
from streamlit_cookies_controller import CookieController

# ── page config (must be first Streamlit call) ────────────────────
st.set_page_config(page_title="Momentum", page_icon="✅", layout="wide")

# ── cookie controller (must be instantiated at top level) ─────────
cookie_ctrl = CookieController(key="momentum_cookies")

# ── constants ─────────────────────────────────────────────────────
DEFAULT_COLORS = ['#2563eb', '#16a34a', '#d97706', '#db2777', '#7c3aed', '#0891b2', '#ea580c']

# ── Supabase clients ──────────────────────────────────────────────
@st.cache_resource
def get_auth_client() -> Client:
    """Anon-key client — used only for auth.sign_in / sign_up."""
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


@st.cache_resource
def get_supabase() -> Client:
    """Service-role client — full DB access, filtered manually by user_id."""
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_SERVICE_KEY"])


# ── auth wall ─────────────────────────────────────────────────────
_COOKIE_NAME   = "momentum_auth"
_COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 days

def auth_wall():
    """Show login/signup if not authenticated. Returns on success, st.stop() otherwise."""
    if "user_id" in st.session_state:
        return

    # ── try to restore session from cookie ────────────────────────
    # On the very first render the CookieController component hasn't yet sent
    # cookie values back to Python, so get() returns None. We wait one rerun
    # (showing a spinner) before deciding to show the login form.
    saved = cookie_ctrl.get(_COOKIE_NAME)
    if saved is None and not st.session_state.get("_cookies_ready"):
        # First render — cookies not loaded yet; wait for component round-trip
        st.session_state["_cookies_ready"] = True
        with st.spinner(""):
            st.stop()
    if saved:
        try:
            tokens = json.loads(saved) if isinstance(saved, str) else saved
            auth_c = get_auth_client()
            try:
                res = auth_c.auth.set_session(tokens["access_token"], tokens["refresh_token"])
            except Exception:
                res = auth_c.auth.refresh_session(tokens["refresh_token"])
            st.session_state.user_id    = res.user.id
            st.session_state.user_email = res.user.email
            # Refresh cookie with latest tokens
            cookie_ctrl.set(_COOKIE_NAME, json.dumps({
                "access_token":  res.session.access_token,
                "refresh_token": res.session.refresh_token,
            }), max_age=_COOKIE_MAX_AGE)
            return
        except Exception:
            cookie_ctrl.remove(_COOKIE_NAME)

    # ── login / signup UI ─────────────────────────────────────────
    st.markdown(
        "<div style='text-align:center;margin-top:3rem'>"
        "<svg width='48' height='56' viewBox='0 0 48 56' fill='none' xmlns='http://www.w3.org/2000/svg' style='vertical-align:middle;margin-bottom:4px'>"
        "<polygon points='4,2 44,2 24,26' fill='white'/>"
        "<polygon points='4,54 44,54 24,30' fill='white'/>"
        "</svg>"
        "<span style='font-size:2.2rem;font-weight:700;vertical-align:middle;margin-left:12px'>Momentum</span>"
        "</div>"
        "<p style='text-align:center;color:#6b7280'>tiny habits. big life. let's go!</p>",
        unsafe_allow_html=True,
    )
    col = st.columns([1, 2, 1])[1]
    with col:
        tab_in, tab_up = st.tabs(["Log In", "Sign Up"])

        with tab_in:
            email = st.text_input("Email", key="li_email")
            pwd   = st.text_input("Password", type="password", key="li_pwd")
            if st.button("Log In", type="primary", use_container_width=True):
                try:
                    res = get_auth_client().auth.sign_in_with_password(
                        {"email": email, "password": pwd}
                    )
                    st.session_state.user_id    = res.user.id
                    st.session_state.user_email = res.user.email
                    cookie_ctrl.set(_COOKIE_NAME, json.dumps({
                        "access_token":  res.session.access_token,
                        "refresh_token": res.session.refresh_token,
                    }), max_age=_COOKIE_MAX_AGE)
                    st.rerun()
                except Exception:
                    st.error("Invalid email or password.")

        with tab_up:
            email = st.text_input("Email", key="su_email")
            pwd   = st.text_input("Password", type="password", key="su_pwd")
            st.caption("Password must be at least 6 characters.")
            if st.button("Create Account", type="primary", use_container_width=True):
                try:
                    get_auth_client().auth.sign_up({"email": email, "password": pwd})
                    st.success("Account created! Check your email to confirm, then log in.")
                except Exception as e:
                    st.error(f"Sign up failed: {e}")

    st.stop()


# ── data persistence ──────────────────────────────────────────────
def load_data(user_id: str) -> dict:
    sb = get_supabase()
    habits_rows  = (
        sb.table("habits").select("id,name,color")
        .eq("user_id", user_id).order("created_at").execute().data or []
    )
    checkin_rows = (
        sb.table("checkins").select("date,habit_id,progress,note")
        .eq("user_id", user_id).execute().data or []
    )
    goal_rows = (
        sb.table("goals").select("habit_id,weekly_target")
        .eq("user_id", user_id).execute().data or []
    )

    checkins: dict = {}
    for row in checkin_rows:
        d = row["date"]
        if d not in checkins:
            checkins[d] = {}
        checkins[d][row["habit_id"]] = {"progress": row["progress"], "note": row["note"]}

    goals: dict = {
        row["habit_id"]: {"weeklyTarget": row["weekly_target"]} for row in goal_rows
    }
    return {
        "habits":   [{"id": h["id"], "name": h["name"], "color": h["color"]} for h in habits_rows],
        "checkins": checkins,
        "goals":    goals,
    }


def save_habit_add(habit: dict, user_id: str):
    get_supabase().table("habits").insert(
        {"id": habit["id"], "name": habit["name"], "color": habit["color"], "user_id": user_id}
    ).execute()


def save_habit_delete(hid: str):
    # ON DELETE CASCADE removes related checkins and goals automatically
    get_supabase().table("habits").delete().eq("id", hid).execute()


def save_checkin(iso: str, hid: str, entry: dict, user_id: str):
    get_supabase().table("checkins").upsert(
        {
            "date": iso, "habit_id": hid,
            "progress": entry["progress"], "note": entry["note"],
            "user_id": user_id,
        },
        on_conflict="date,habit_id",
    ).execute()


def save_goal(hid: str, weekly_target: int, user_id: str):
    get_supabase().table("goals").upsert(
        {"habit_id": hid, "weekly_target": weekly_target, "user_id": user_id},
        on_conflict="habit_id",
    ).execute()


# ── auth ──────────────────────────────────────────────────────────
auth_wall()  # stops page here if not logged in
user_id = st.session_state.user_id

# ── session state ─────────────────────────────────────────────────
# Reload data when user changes (e.g. after logout/login)
if "data" not in st.session_state or st.session_state.get("data_user") != user_id:
    st.session_state.data             = load_data(user_id)
    st.session_state.data_user        = user_id
    st.session_state.pending_checkins = {}   # {(iso, hid): entry}
    st.session_state.pending_goals    = {}   # {hid: weekly_target}

if "pending_checkins" not in st.session_state:
    st.session_state.pending_checkins = {}
if "pending_goals" not in st.session_state:
    st.session_state.pending_goals = {}

data = st.session_state.data


# ── debounced DB flush (runs every 3 s in background) ────────────
@st.fragment(run_every="3s")
def db_flush_fragment():
    uid              = st.session_state.get("user_id")
    pending_checkins = st.session_state.get("pending_checkins", {})
    pending_goals    = st.session_state.get("pending_goals", {})
    if not uid or (not pending_checkins and not pending_goals):
        return
    for (iso, hid), entry in list(pending_checkins.items()):
        save_checkin(iso, hid, entry, uid)
    for hid, target in list(pending_goals.items()):
        save_goal(hid, target, uid)
    st.session_state.pending_checkins = {}
    st.session_state.pending_goals    = {}

db_flush_fragment()

# ── helpers ───────────────────────────────────────────────────────
def normalize_entry(raw):
    if isinstance(raw, bool):
        return {"progress": 100 if raw else 0, "note": ""}
    if isinstance(raw, dict):
        return {"progress": int(raw.get("progress", 0)), "note": raw.get("note", "")}
    return {"progress": 0, "note": ""}


def get_monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def dates_in_range(start: date, end: date):
    out, cur = [], start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def logged_habits_for_day(checkins: dict, iso: str, habits: list):
    rec = checkins.get(iso, {})
    return [(h, normalize_entry(rec.get(h["id"])))
            for h in habits if normalize_entry(rec.get(h["id"]))["progress"] > 0]


def tally_habits(checkins: dict, dates: list, habits: list):
    counts = {h["id"]: 0 for h in habits}
    for d in dates:
        for hid, raw in checkins.get(d.strftime("%Y-%m-%d"), {}).items():
            if normalize_entry(raw)["progress"] > 0:
                counts[hid] = counts.get(hid, 0) + 1
    return counts


def week_progress(hid: str, for_date: date, data: dict) -> tuple[int, int]:
    """Return (done_this_week, weekly_goal) for a habit relative to for_date's week."""
    goal  = data["goals"].get(hid, {}).get("weeklyTarget", 0)
    if not goal:
        return 0, 0
    monday    = get_monday_of(for_date)
    week_days = dates_in_range(monday, for_date)  # Mon → for_date (inclusive)
    done      = sum(
        1 for d in week_days
        if normalize_entry(
            data["checkins"].get(d.strftime("%Y-%m-%d"), {}).get(hid)
        )["progress"] > 0
    )
    return done, goal


def get_available_weeks(today: date):
    cur_mon = get_monday_of(today)
    prev_m  = today.month - 1 or 12
    prev_y  = today.year if today.month > 1 else today.year - 1
    cursor  = get_monday_of(date(prev_y, prev_m, 1))
    anchor  = date(prev_y, prev_m, 1)
    if cursor < anchor:
        cursor += timedelta(weeks=1)
    weeks = []
    while cursor <= cur_mon:
        weeks.append(cursor)
        cursor += timedelta(weeks=1)
    return weeks


def fmt_week(monday: date, today: date) -> str:
    end = min(monday + timedelta(days=6), today)
    lbl = f"{monday.strftime('%d %b')} – {end.strftime('%d %b %Y')}"
    return lbl + "  (this week)" if monday == get_monday_of(today) else lbl


def build_calendar_html(year: int, month: int, checkins: dict, habits: list, sel_iso: str) -> str:
    total   = cal_module.monthrange(year, month)[1]
    # Python weekday(): Mon=0…Sun=6 → Sun-first offset = (weekday+1) % 7
    offset  = (date(year, month, 1).weekday() + 1) % 7
    today_iso = date.today().strftime("%Y-%m-%d")

    cells = ["<div class='e'></div>"] * offset
    for day in range(1, total + 1):
        iso    = f"{year}-{month:02d}-{day:02d}"
        logged = logged_habits_for_day(checkins, iso, habits)
        cls    = "d"
        if iso == sel_iso:   cls += " sel"
        if iso == today_iso: cls += " tod"

        if not logged:
            fill = "<span class='ef'></span>"
        elif len(logged) == 1:
            fill = f"<span class='ff' style='background:{logged[0][0]['color']}'></span>"
        else:
            strips = "".join("<i style='background:" + h['color'] + "'></i>" for h, _ in logged)
            fill = f"<span class='mf'>{strips}</span>"

        cells.append(f"<div class='{cls}'><b class='dn'>{day}</b>{fill}</div>")

    wd   = "".join(f"<div class='wd'>{d}</div>" for d in ["Sun","Mon","Tue","Wed","Thu","Fri","Sat"])
    grid = "\n".join(cells)
    return f"""<html><head><style>
*{{box-sizing:border-box;margin:0;padding:0;font-family:Inter,system-ui,sans-serif}}
body{{background:transparent;padding:2px}}
.wds,.grid{{display:grid;grid-template-columns:repeat(7,minmax(0,1fr));gap:3px}}
.wds{{margin-bottom:3px}}
.wd{{text-align:center;font-size:11px;color:#6b7280;padding:3px 0}}
.d{{min-height:50px;border-radius:7px;border:1px solid #e5e7eb;background:#f9fafb;
    display:grid;align-content:space-between;justify-items:start;padding:3px}}
.d.sel{{border:2px solid #111827}}
.d.tod{{background:#eff6ff}}
.e{{visibility:hidden;min-height:50px}}
.dn{{font-size:11px;font-weight:700;display:block}}
.ef{{width:100%;height:9px;border-radius:3px;background:#e5e7eb}}
.ff{{width:100%;height:9px;border-radius:3px}}
.mf{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:2px;width:100%}}
.mf i{{display:block;height:9px;border-radius:2px}}
</style></head><body>
<div class="wds">{wd}</div>
<div class="grid">{grid}</div>
</body></html>"""


# ── global styles ─────────────────────────────────────────────────
st.markdown("""<style>
.block-container{padding-top:3.5rem}
.color-dot{display:inline-block;width:12px;height:12px;border-radius:50%;margin-right:6px;vertical-align:middle}
[data-testid="stSliderThumbValue"] { display: none !important; }
[data-testid="stTickBarMin"], [data-testid="stTickBarMax"] { display: none !important; }
[data-testid="stTabs"] { margin-top: 0.5rem; }
</style>""", unsafe_allow_html=True)


def color_dot(color: str, size: int = 14) -> str:
    return f"<span style='display:inline-block;width:{size}px;height:{size}px;border-radius:50%;background:{color};margin-right:6px;vertical-align:middle'></span>"


# ═════════════════════════════════════════════════════════════════
# SIDEBAR – habit management
# ═════════════════════════════════════════════════════════════════
with st.sidebar:
    st.title("Momentum")
    st.caption(st.session_state.get("user_email", ""))
    if st.button("Log Out", use_container_width=True):
        cookie_ctrl.remove(_COOKIE_NAME)
        for key in ["user_id", "user_email", "data", "data_user", "_cookies_ready"]:
            st.session_state.pop(key, None)
        st.rerun()
    st.divider()

    st.subheader("Add a Habit for the day")
    new_name  = st.text_input("Name", placeholder="e.g. Morning walk", key="new_name")
    color_idx = len(data["habits"]) % len(DEFAULT_COLORS)
    new_color = st.color_picker("Colour", DEFAULT_COLORS[color_idx], key="new_color")

    if st.button("Add Habit", type="primary", use_container_width=True):
        name = new_name.strip()
        if name:
            existing_lower = [h["name"].lower() for h in data["habits"]]
            if name.lower() in existing_lower:
                st.session_state["dup_warn"] = name
            else:
                new_habit = {"id": str(uuid.uuid4()), "name": name, "color": new_color}
                data["habits"].append(new_habit)
                save_habit_add(new_habit, user_id)
                st.session_state.pop("dup_warn", None)
                st.session_state.pop("new_color", None)
                st.session_state.pop("new_name", None)
                st.rerun()

    if "dup_warn" in st.session_state:
        st.warning(f"⚠️ **{st.session_state['dup_warn']}** already exists. "
                   "Are you sure you haven't logged this yet?")
        ca, cb = st.columns(2)
        with ca:
            if st.button("Add Anyway"):
                new_habit = {"id": str(uuid.uuid4()), "name": st.session_state["dup_warn"], "color": new_color}
                data["habits"].append(new_habit)
                save_habit_add(new_habit, user_id)
                st.session_state.pop("dup_warn")
                st.session_state.pop("new_color", None)
                st.session_state.pop("new_name", None)
                st.rerun()
        with cb:
            if st.button("Cancel"):
                st.session_state.pop("dup_warn")
                st.rerun()

    st.divider()
    st.subheader("📋 Habits")
    if not data["habits"]:
        st.caption("No habits yet.")
    else:
        for habit in list(data["habits"]):
            c1, c2 = st.columns([5, 1])
            with c1:
                st.markdown(color_dot(habit["color"]) + f"**{habit['name']}**",
                            unsafe_allow_html=True)
            with c2:
                if st.button("✕", key=f"rm_{habit['id']}", help="Remove"):
                    hid_rm = habit["id"]
                    data["habits"] = [h for h in data["habits"] if h["id"] != hid_rm]
                    for day in data["checkins"]:
                        data["checkins"][day].pop(hid_rm, None)
                    save_habit_delete(hid_rm)
                    st.rerun()


# ═════════════════════════════════════════════════════════════════
# TABS
# ═════════════════════════════════════════════════════════════════
tab_daily, tab_cal, tab_weekly, tab_monthly, tab_goals = st.tabs([
    "📋  Daily Log",
    "📅  Calendar",
    "📊  Weekly Summary",
    "📆  Monthly Summary",
    "🎯  Goals",
])


# ── TAB: DAILY LOG ────────────────────────────────────────────────
STATUS_OPTIONS = [
    ("✗ Skip", 0,   "#e5e7eb", "#374151"),
    ("✓ Done", 100, "#dcfce7", "#15803d"),
]

def progress_to_status(prog: int) -> int:
    """Return the index in STATUS_OPTIONS closest to prog."""
    return min(range(len(STATUS_OPTIONS)), key=lambda i: abs(STATUS_OPTIONS[i][1] - prog))

@st.fragment
def daily_log_fragment():
    today = date.today()
    sel_date: date = st.date_input("Date", value=today, max_value=today,
                                   key="daily_date", label_visibility="visible")
    iso = sel_date.strftime("%Y-%m-%d")

    if sel_date > today:
        st.error("🚀 You can't time travel! Please select today or a past date.")
        return

    st.subheader(f"Habits for {iso}")

    if not data["habits"]:
        st.info("Add habits in the sidebar to start tracking!")
        return

    if iso not in data["checkins"]:
        data["checkins"][iso] = {}

    # Sort: due-and-not-yet-done first, then done, then no goal / skipped
    def habit_sort_key(h):
        hid   = h["id"]
        done, goal = week_progress(hid, sel_date, data)
        entry = normalize_entry(data["checkins"][iso].get(hid))
        if goal > 0 and entry["progress"] == 0:  # due, not done today
            return (0, done - goal)               # most behind first
        if entry["progress"] == 100:              # done today
            return (2, 0)
        return (1, 0)                             # no goal / skipped

    sorted_habits = sorted(data["habits"], key=habit_sort_key)

    for habit in sorted_habits:
        hid   = habit["id"]
        entry = normalize_entry(data["checkins"][iso].get(hid))
        cur_status = progress_to_status(entry["progress"])

        with st.container(border=True):
            h1, h2 = st.columns([7, 2])
            with h1:
                done, goal = week_progress(hid, sel_date, data)
                due_badge  = ""
                if goal > 0 and entry["progress"] == 0:
                    remaining = goal - done
                    due_badge = (
                        f" <span style='background:#fff7ed;color:#c2410c;"
                        f"padding:2px 8px;border-radius:999px;font-size:0.78rem;"
                        f"font-weight:600'>🔔 {done}/{goal} this week</span>"
                    )
                st.markdown(
                    color_dot(habit["color"], 16) + f"**{habit['name']}**" + due_badge,
                    unsafe_allow_html=True,
                )
            with h2:
                label, pct, bg, fg = STATUS_OPTIONS[cur_status]
                st.markdown(
                    f"<span style='background:{bg};color:{fg};padding:3px 10px;"
                    f"border-radius:999px;font-size:0.85rem;font-weight:600'>{label}</span>",
                    unsafe_allow_html=True,
                )

            # One-click status buttons
            cols = st.columns(len(STATUS_OPTIONS))
            new_status = cur_status
            for idx, (lbl, pct, bg, fg) in enumerate(STATUS_OPTIONS):
                with cols[idx]:
                    active = idx == cur_status
                    border = f"2px solid {fg}" if active else "1px solid #e5e7eb"
                    if st.button(
                        lbl,
                        key=f"status_{hid}_{iso}_{idx}",
                        use_container_width=True,
                        help=f"{pct}% complete",
                    ):
                        new_status = idx

            new_prog = STATUS_OPTIONS[new_status][1]

            note = st.text_area(
                "Notes", value=entry["note"],
                placeholder=f"Notes for {habit['name']} on {iso}…",
                key=f"note_{hid}_{iso}",
                height=75,
                label_visibility="collapsed",
            )

            new_entry = {"progress": new_prog, "note": note}
            if new_entry != entry:
                data["checkins"][iso][hid] = new_entry
                st.session_state.pending_checkins[(iso, hid)] = new_entry
                st.rerun()  # full rerun so calendar, weekly, monthly reflect the change

with tab_daily:
    daily_log_fragment()


# ── TAB: CALENDAR ─────────────────────────────────────────────────
with tab_cal:
    today = date.today()
    if "cal_year" not in st.session_state:
        st.session_state.cal_year  = today.year
        st.session_state.cal_month = today.month

    prev_col, title_col, next_col = st.columns([1, 4, 1])
    with prev_col:
        if st.button("← Prev", key="cal_prev"):
            m = st.session_state.cal_month - 1
            if m == 0:
                st.session_state.cal_month = 12
                st.session_state.cal_year -= 1
            else:
                st.session_state.cal_month = m
            st.rerun()
    with title_col:
        st.markdown(
            f"<h3 style='text-align:center'>"
            f"{date(st.session_state.cal_year, st.session_state.cal_month, 1).strftime('%B %Y')}"
            f"</h3>",
            unsafe_allow_html=True,
        )
    with next_col:
        if st.button("Next →", key="cal_next"):
            m = st.session_state.cal_month + 1
            if m == 13:
                st.session_state.cal_month = 1
                st.session_state.cal_year += 1
            else:
                st.session_state.cal_month = m
            st.rerun()

    cal_picked: date = st.date_input("Jump to / select a day",
                                      value=today, key="cal_pick")
    sel_cal_iso = cal_picked.strftime("%Y-%m-%d")

    # Keep month in sync when user jumps via date input
    if (cal_picked.year != st.session_state.cal_year
            or cal_picked.month != st.session_state.cal_month):
        st.session_state.cal_year  = cal_picked.year
        st.session_state.cal_month = cal_picked.month

    html = build_calendar_html(
        st.session_state.cal_year,
        st.session_state.cal_month,
        data["checkins"],
        data["habits"],
        sel_cal_iso,
    )
    components.html(html, height=330, scrolling=False)

    # Legend
    st.caption("⬜ No habits logged  |  Solid strip = single habit  |  Coloured boxes = multiple habits")
    st.divider()

    # Day detail (replaces the click-modal from React)
    logged_day = logged_habits_for_day(data["checkins"], sel_cal_iso, data["habits"])
    st.subheader(f"📌 {sel_cal_iso}")
    if logged_day:
        for habit, entry in logged_day:
            with st.container(border=True):
                c1, c2, c3 = st.columns([1, 6, 2])
                with c1:
                    st.markdown(color_dot(habit["color"]), unsafe_allow_html=True)
                with c2:
                    st.markdown(f"**{habit['name']}**")
                    if entry["note"]:
                        st.caption(entry["note"])
                with c3:
                    st.metric("Progress", f"Complete!", label_visibility="hidden")
    else:
        st.caption("No habits logged for this day.")


# ── TAB: WEEKLY SUMMARY ───────────────────────────────────────────
@st.fragment
def weekly_fragment():
    st.subheader("📊 Weekly Summary")
    today = date.today()
    avail_weeks = get_available_weeks(today)
    week_labels = [fmt_week(w, today) for w in avail_weeks]
    week_idx = st.selectbox(
        "Week",
        range(len(avail_weeks)),
        format_func=lambda i: week_labels[i],
        index=len(avail_weeks) - 1,
        key="week_sel",
    )
    sel_mon    = avail_weeks[week_idx]
    sel_sun    = sel_mon + timedelta(days=6)
    week_end   = min(sel_sun, today)
    week_dates = dates_in_range(sel_mon, week_end)
    w_tally    = tally_habits(data["checkins"], week_dates, data["habits"])
    st.caption(f"{sel_mon.strftime('%d %b')} → {week_end.strftime('%d %b %Y')}  ·  {len(week_dates)} days")
    st.divider()

    if not data["habits"]:
        st.info("No habits yet.")
    else:
        for habit in data["habits"]:
            hid    = habit["id"]
            count  = w_tally.get(hid, 0)
            target = data["goals"].get(hid, {}).get("weeklyTarget", 0)
            met    = target > 0 and count >= target

            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 4, 2, 3])
                with c1:
                    st.markdown(color_dot(habit["color"]), unsafe_allow_html=True)
                with c2:
                    label = f"**{habit['name']}**" + ("  🎉" if met else "")
                    st.markdown(label)
                with c3:
                    st.markdown(f"`{count}×` logged")
                with c4:
                    if target > 0:
                        st.progress(min(count / target, 1.0),
                                    text=f"Goal: {target}×/wk")
                        if met:
                            st.success("✓ Goal met!", icon="🟢")
                    else:
                        st.caption("No goal set")

with tab_weekly:
    weekly_fragment()


# ── TAB: MONTHLY SUMMARY ──────────────────────────────────────────
@st.fragment
def monthly_fragment():
    st.subheader("📆 Monthly Summary")
    today = date.today()
    mc1, mc2 = st.columns(2)
    with mc1:
        sel_month_i = st.selectbox(
            "Month", range(1, 13),
            format_func=lambda m: date(2000, m, 1).strftime("%B"),
            index=today.month - 1, key="sum_month",
        )
    with mc2:
        sel_year_i = int(st.number_input(
            "Year", min_value=2020, max_value=today.year + 1,
            value=today.year, step=1, key="sum_year",
        ))

    day_cnt     = cal_module.monthrange(sel_year_i, sel_month_i)[1]
    month_dates = [date(sel_year_i, sel_month_i, d) for d in range(1, day_cnt + 1)]
    wks_cnt     = math.ceil(day_cnt / 7)
    m_tally     = tally_habits(data["checkins"], month_dates, data["habits"])

    st.caption(f"{day_cnt} days  ·  ~{wks_cnt} weeks")
    st.divider()

    if not data["habits"]:
        st.info("No habits yet.")
    else:
        for habit in data["habits"]:
            hid    = habit["id"]
            count  = m_tally.get(hid, 0)
            wt     = data["goals"].get(hid, {}).get("weeklyTarget", 0)
            target = wt * wks_cnt if wt else 0
            met    = target > 0 and count >= target

            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([1, 4, 2, 3])
                with c1:
                    st.markdown(color_dot(habit["color"]), unsafe_allow_html=True)
                with c2:
                    label = f"**{habit['name']}**" + ("  🎉" if met else "")
                    st.markdown(label)
                with c3:
                    st.markdown(f"`{count}×` logged")
                with c4:
                    if target > 0:
                        st.progress(min(count / target, 1.0),
                                    text=f"Goal: {target}×/mo")
                        if met:
                            st.success("✓ Goal met!", icon="🟢")
                    else:
                        st.caption("No goal set")

with tab_monthly:
    monthly_fragment()


# ── TAB: GOALS ────────────────────────────────────────────────────
@st.fragment
def goals_fragment():
    st.subheader("🎯 Set Goals")
    st.caption(
        "Set how many times **per week** you want to complete each habit. "
        "The Monthly Summary scales this up automatically. "
        "When a goal is met in any summary the row shows 🎉."
    )
    st.divider()

    if not data["habits"]:
        st.info("Add habits in the sidebar first.")
    else:
        goals_changed = False
        for habit in data["habits"]:
            hid     = habit["id"]
            current = data["goals"].get(hid, {}).get("weeklyTarget", 0)
            with st.container(border=True):
                g1, g2, g3 = st.columns([1, 5, 3])
                with g1:
                    st.markdown(color_dot(habit["color"]), unsafe_allow_html=True)
                with g2:
                    st.markdown(f"**{habit['name']}**")
                with g3:
                    val = st.number_input(
                        "×/week", min_value=0, max_value=7,
                        value=current, step=1,
                        key=f"goal_{hid}",
                    )
                if val != current:
                    if hid not in data["goals"]:
                        data["goals"][hid] = {}
                    data["goals"][hid]["weeklyTarget"] = int(val)
                    st.session_state.pending_goals[hid] = int(val)
                    goals_changed = True

        if goals_changed:
            st.toast("Goals saved!", icon="🎯")
            st.rerun()  # full rerun so weekly + monthly tabs reflect new targets

with tab_goals:
    goals_fragment()
