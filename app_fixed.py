# app_fixed.py  (uKids Guys Availability Form - 2 multiselect UI, but saves Yes/No per service column)
import time
import random
from io import BytesIO
from datetime import datetime

import pandas as pd
import streamlit as st

# ✅ Timezone-aware deadlines
try:
    from zoneinfo import ZoneInfo
except Exception:
    ZoneInfo = None  # fallback

# Optional: Google Sheets libs.
try:
    import gspread
    from gspread.exceptions import APIError, WorksheetNotFound
except Exception:
    gspread = None

    class APIError(Exception):
        ...

    class WorksheetNotFound(Exception):
        ...


# ──────────────────────────────────────────────────────────────────────────────
# UI CONFIG + mobile tweaks
# ──────────────────────────────────────────────────────────────────────────────
st.set_page_config(page_title="uKids Guys Availability Form", page_icon="🗓️", layout="centered")
st.title("🗓️ uKids Guys Availability Form")

st.markdown(
    """
<style>
  .stButton > button { width: 100%; height: 48px; font-size: 16px; }
  @media (max-width: 520px){
    div[data-testid="column"] { width: 100% !important; flex: 0 0 100% !important; }
    pre, code { font-size: 15px; line-height: 1.35; }
  }
  .sticky-submit {
    position: sticky; bottom: 0; z-index: 999;
    background: #fff; padding: 10px 0; border-top: 1px solid #eee;
  }
</style>
""",
    unsafe_allow_html=True,
)

# ──────────────────────────────────────────────────────────────────────────────
# Google Sheets tabs
# ──────────────────────────────────────────────────────────────────────────────
TAB_RESPONSES = "uKids Guys responses"
TAB_SB = "uKids Guys SB"
TAB_DEADLINES = "Deadlines"
TAB_DATES = "Kids & Guys ServiceDates"


# ──────────────────────────────────────────────────────────────────────────────
# Secrets helpers
# ──────────────────────────────────────────────────────────────────────────────
def _get_secret_any(*paths):
    try:
        cur = st.secrets
    except Exception:
        return None
    for path in paths:
        c = cur
        ok = True
        for k in path:
            if k in c:
                c = c[k]
            else:
                ok = False
                break
        if ok:
            return c
    return None


def get_admin_key() -> str:
    v = _get_secret_any(["ADMIN_KEY"], ["general", "ADMIN_KEY"])
    return str(v) if v else ""


ADMIN_KEY = get_admin_key()


def is_sheets_enabled() -> bool:
    if gspread is None:
        return False
    sa = _get_secret_any(["gcp_service_account"], ["general", "gcp_service_account"])
    sid = _get_secret_any(["GSHEET_ID"], ["general", "GSHEET_ID"])
    return bool(sa and sid)


if not is_sheets_enabled():
    st.error("Google Sheets is not configured. Add GSHEET_ID and [gcp_service_account] to Secrets.")
    st.stop()


# ──────────────────────────────────────────────────────────────────────────────
# Google Sheets helpers
# ──────────────────────────────────────────────────────────────────────────────
def gs_retry(func, *args, **kwargs):
    for attempt in range(5):
        try:
            return func(*args, **kwargs)
        except APIError as e:
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status in (429, 500, 502, 503):
                time.sleep(min(10, (2**attempt) + random.random()))
                continue
            raise


@st.cache_resource
def get_spreadsheet():
    sa = _get_secret_any(["gcp_service_account"], ["general", "gcp_service_account"])
    sheet_id = _get_secret_any(["GSHEET_ID"], ["general", "GSHEET_ID"])
    if not sa or not sheet_id:
        raise RuntimeError("Missing GSHEET_ID or gcp_service_account in secrets.")

    sa = dict(sa)
    pk = sa.get("private_key", "")
    if isinstance(pk, str):
        pk = pk.replace("\\n", "\n").strip()
        if not pk.endswith("\n"):
            pk += "\n"
        sa["private_key"] = pk

    gc = gspread.service_account_from_dict(sa)
    return gs_retry(gc.open_by_key, sheet_id)


def ensure_worksheet(sh, title: str, rows: int = 2000, cols: int = 50):
    try:
        return sh.worksheet(title)
    except WorksheetNotFound:
        return sh.add_worksheet(title=title, rows=rows, cols=cols)


def ws_get_df(ws) -> pd.DataFrame:
    values = gs_retry(ws.get_all_values)
    if not values:
        return pd.DataFrame()
    header, rows = values[0], values[1:]

    # If SB is a list of names without header
    if not header or all(str(h).strip() == "" for h in header):
        flat = [r[0] for r in rows if r and str(r[0]).strip()]
        return pd.DataFrame(flat, columns=["Name"])

    # If SB has first name in header row (common mistake)
    if len(header) == 1 and header[0] and (not rows or (rows and len(rows[0]) <= 1)):
        maybe_first = str(header[0]).strip()
        if maybe_first.lower() not in ("name", "serving guy", "person", "serving person"):
            flat = [maybe_first] + [str(r[0]).strip() for r in rows if r and str(r[0]).strip()]
            return pd.DataFrame(flat, columns=["Name"])

    return pd.DataFrame(rows, columns=header)


def ws_ensure_header(ws, desired_header: list[str]) -> list[str]:
    header = gs_retry(ws.row_values, 1)
    if not header:
        gs_retry(ws.update, "1:1", [desired_header])
        return desired_header
    missing = [c for c in desired_header if c not in header]
    if missing:
        header = header + missing
        gs_retry(ws.update, "1:1", [header])
    return header


@st.cache_data(ttl=30, show_spinner=False)
def fetch_sb_df() -> pd.DataFrame:
    sh = get_spreadsheet()
    ws = ensure_worksheet(sh, TAB_SB, rows=4000, cols=20)
    return ws_get_df(ws)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_deadlines_df() -> pd.DataFrame:
    sh = get_spreadsheet()
    ws = ensure_worksheet(sh, TAB_DEADLINES, rows=500, cols=10)
    return ws_get_df(ws)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_service_dates_df() -> pd.DataFrame:
    sh = get_spreadsheet()
    ws = ensure_worksheet(sh, TAB_DATES, rows=4000, cols=10)
    return ws_get_df(ws)


@st.cache_data(ttl=30, show_spinner=False)
def fetch_responses_df() -> pd.DataFrame:
    sh = get_spreadsheet()
    ws = ensure_worksheet(sh, TAB_RESPONSES, rows=8000, cols=250)
    return ws_get_df(ws)


def append_response_row(desired_header: list[str], row_map: dict):
    sh = get_spreadsheet()
    ws = ensure_worksheet(sh, TAB_RESPONSES, rows=8000, cols=max(250, len(desired_header) + 10))
    header = ws_ensure_header(ws, desired_header)
    row = [row_map.get(col, "") for col in header]
    gs_retry(ws.append_row, row)


def clear_caches():
    for fn in (fetch_sb_df, fetch_deadlines_df, fetch_service_dates_df, fetch_responses_df):
        try:
            fn.clear()
        except Exception:
            pass
    try:
        st.cache_data.clear()
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────
# Time helpers
# ─────────────────────────────────────────────────────────────
def get_now_in_tz(tz_name: str) -> datetime:
    if ZoneInfo is None:
        return datetime.utcnow()
    return datetime.now(ZoneInfo(tz_name))


def add_one_month(dt: datetime) -> datetime:
    y, m = dt.year, dt.month
    if m == 12:
        y2, m2 = y + 1, 1
    else:
        y2, m2 = y, m + 1
    if dt.tzinfo:
        return datetime(y2, m2, 1, tzinfo=dt.tzinfo)
    return datetime(y2, m2, 1)


def get_target_month_key(now_local: datetime) -> str:
    return add_one_month(now_local).strftime("%Y-%m")


def parse_deadline_local(deadline_local: str, tz_name: str) -> datetime:
    dt_naive = datetime.strptime(deadline_local, "%Y-%m-%d %H:%M")
    if ZoneInfo is None:
        return dt_naive
    return dt_naive.replace(tzinfo=ZoneInfo(tz_name))


def format_minutes_remaining(delta_seconds: float) -> str:
    mins = max(0, int(delta_seconds // 60))
    hrs = mins // 60
    rem_m = mins % 60
    return f"{hrs}h {rem_m}m" if hrs > 0 else f"{rem_m}m"


def _safe_parse_date_ymd(s: str) -> datetime:
    try:
        return datetime.strptime(str(s).strip(), "%Y-%m-%d")
    except Exception:
        return datetime(1900, 1, 1)


def _is_truthy_service_day(v) -> bool:
    s = str(v).strip().lower()
    return s in ("1", "true", "yes", "y", "t")


def _display_date_only(label: str) -> str:
    """
    Turns:
      '1 March Morning Service' -> '1 March'
      '3 April - Good Friday Morning Service' -> '3 April - Good Friday'
    """
    s = str(label).strip()
    s = s.replace("Morning Service", "").replace("Evening Service", "")
    s = s.replace("Morning", "").replace("Evening", "")
    s = s.replace("Service", "")
    return " ".join(s.split()).strip(" -")


def _dedupe_keep_order(seq):
    seen = set()
    out = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def build_human_report(target_month_key: str, name: str, date_labels: list[str], yes_map: dict) -> str:
    lines = [
        f"Availability month: {target_month_key}",
        f"Serving Guy: {name or '—'}",
        "Availability:",
    ]
    for lbl in date_labels:
        lines.append(f"{lbl}: {yes_map.get(lbl, 'No')}")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────
# Load config
# ─────────────────────────────────────────────────────────────
try:
    sb_df = fetch_sb_df()
    deadlines_df = fetch_deadlines_df()
    service_dates_all = fetch_service_dates_df()
except Exception as e:
    st.error(f"Failed to load config from Google Sheets: {e}")
    st.stop()

# Validate columns
for df, name, needed in [
    (deadlines_df, TAB_DEADLINES, {"month", "deadline_local", "timezone"}),
    (service_dates_all, TAB_DATES, {"target_month", "date", "label", "is_service_day"}),
]:
    miss = needed - set(df.columns)
    if miss:
        st.error(f"Google Sheet tab '{name}' is missing columns: {', '.join(sorted(miss))}")
        st.stop()

# Guys list from SB
guys = []
if sb_df is not None and not sb_df.empty:
    possible_cols = [c for c in sb_df.columns if str(c).strip().lower() in ("name", "serving guy", "person", "serving person")]
    col = possible_cols[0] if possible_cols else sb_df.columns[0]
    guys = sb_df[col].astype(str).str.strip().tolist()
guys = sorted({g for g in guys if g and g.lower() != "nan"})

# Clean deadlines + dates
deadlines_df["month"] = deadlines_df["month"].astype(str).str.strip()
deadlines_df["deadline_local"] = deadlines_df["deadline_local"].astype(str).str.strip()
deadlines_df["timezone"] = deadlines_df["timezone"].astype(str).str.strip()

service_dates_all["target_month"] = service_dates_all["target_month"].astype(str).str.strip()
service_dates_all["date"] = service_dates_all["date"].astype(str).str.strip()
service_dates_all["label"] = service_dates_all["label"].astype(str).str.strip()
service_dates_all["is_service_day"] = service_dates_all["is_service_day"].astype(str).str.strip()

# Base TZ
BASE_TZ = "Africa/Johannesburg"
try:
    tz0 = str(deadlines_df["timezone"].iloc[0]).strip()
    if tz0:
        BASE_TZ = tz0
except Exception:
    pass

now_base = get_now_in_tz(BASE_TZ)
target_month_key = get_target_month_key(now_base)

# Filter month services
month_dates = service_dates_all[
    (service_dates_all["target_month"] == target_month_key)
    & (service_dates_all["is_service_day"].map(_is_truthy_service_day))
].copy()

if month_dates.empty:
    st.markdown(
        f"""
        ## 🔒 This month’s availability form is not open yet.

        No service dates were found for **{target_month_key}**.
        """
    )
    st.stop()

month_dates["_sort"] = month_dates["date"].map(_safe_parse_date_ymd)
month_dates = month_dates.sort_values("_sort").drop(columns=["_sort"])

# IMPORTANT: these are the ACTUAL column names we must save
date_labels = month_dates["label"].astype(str).tolist()

# Build morning/evening label lists
morning_labels = [l for l in date_labels if "morning" in l.lower()]
evening_labels = [l for l in date_labels if "evening" in l.lower()]

# Build display -> actual label mapping
def _build_display_map(labels):
    display_map = {}
    used = set()
    for lbl in labels:
        base = _display_date_only(lbl)
        disp = base
        # avoid duplicates if any (rare, but safe)
        i = 2
        while disp in used:
            disp = f"{base} ({i})"
            i += 1
        used.add(disp)
        display_map[disp] = lbl
    return display_map

morning_display_map = _build_display_map(morning_labels)
evening_display_map = _build_display_map(evening_labels)

morning_options = list(morning_display_map.keys())
evening_options = list(evening_display_map.keys())

# Deadline
def get_deadline_for_target_month(deadlines: pd.DataFrame, month_key: str):
    match = deadlines[deadlines["month"] == month_key]
    if match.empty:
        return None, BASE_TZ
    row = match.iloc[0]
    tz_name = str(row["timezone"]).strip() or BASE_TZ
    dl = parse_deadline_local(str(row["deadline_local"]).strip(), tz_name)
    return dl, tz_name

deadline_dt, deadline_tz = get_deadline_for_target_month(deadlines_df, target_month_key)

is_closed = True
if deadline_dt is not None:
    now_local = get_now_in_tz(deadline_tz)
    is_closed = (deadline_dt - now_local).total_seconds() <= 0

if is_closed:
    target_month_name = datetime.strptime(target_month_key, "%Y-%m").strftime("%B")
    st.markdown(
        f"""
        ## 🔒 {target_month_name} availability submissions are now closed.
        """,
        unsafe_allow_html=True,
    )
    st.stop()

# Header info
now_local = get_now_in_tz(deadline_tz)
remaining_seconds = (deadline_dt - now_local).total_seconds()

st.info(
    f"🗓️ Submitting availability for **{target_month_key}**.\n\n"
    f"⏳ Form closes at **{deadline_dt.strftime('%Y-%m-%d %H:%M')}** ({deadline_tz}). "
    f"Time remaining: **{format_minutes_remaining(remaining_seconds)}**\n\n"
    f"🔁 You can submit more than once — we will use your most recent submission."
)

if st.button("Refresh timer"):
    st.rerun()

# ─────────────────────────────────────────────────────────────
# UI state
# ─────────────────────────────────────────────────────────────
if "answers" not in st.session_state:
    st.session_state.answers = {}
answers = st.session_state.answers

# ─────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────
st.subheader("Your details")
if not guys:
    st.warning("No names found in 'uKids Guys SB'. Please add names in column A.")
    st.stop()

answers["Q_NAME"] = st.selectbox("Please select your name", options=[""] + guys, index=0)

st.subheader(f"Availability for {target_month_key}")

answers["MORNING_SELECTED"] = st.multiselect(
    "Which morning services are you available?",
    options=morning_options,
    default=answers.get("MORNING_SELECTED", []),
)

answers["EVENING_SELECTED"] = st.multiselect(
    "Which evening services are you available?",
    options=evening_options,
    default=answers.get("EVENING_SELECTED", []),
)

# Review
st.subheader("Review")
c1, c2, c3 = st.columns(3)
with c1:
    st.metric("Name", answers.get("Q_NAME") or "—")
with c2:
    st.metric("Morning selected", len(answers.get("MORNING_SELECTED", [])))
with c3:
    st.metric("Evening selected", len(answers.get("EVENING_SELECTED", [])))

# ─────────────────────────────────────────────────────────────
# Submit (sticky)
# ─────────────────────────────────────────────────────────────
st.markdown('<div class="sticky-submit">', unsafe_allow_html=True)
submitted = st.button("Submit")
st.markdown("</div>", unsafe_allow_html=True)

if submitted:
    now_check = get_now_in_tz(deadline_tz)
    if (deadline_dt - now_check).total_seconds() <= 0:
        st.error("Form is closed.")
        st.stop()

    if not answers.get("Q_NAME"):
        st.error("Please select your name.")
        st.stop()

    # Convert selections back to the actual label columns
    selected_morning_labels = {morning_display_map[d] for d in answers.get("MORNING_SELECTED", []) if d in morning_display_map}
    selected_evening_labels = {evening_display_map[d] for d in answers.get("EVENING_SELECTED", []) if d in evening_display_map}

    selected_all = selected_morning_labels.union(selected_evening_labels)

    # Build Yes/No map for each service label (this is what your sheet expects)
    yes_map = {}
    for lbl in date_labels:
        yes_map[lbl] = "Yes" if lbl in selected_all else "No"

    now = datetime.utcnow().isoformat() + "Z"
    row_map = {
        "timestamp": now,
        "Availability month": target_month_key,
        "Serving Guy": answers.get("Q_NAME") or "",
    }
    row_map.update(yes_map)

    desired_header = ["timestamp", "Availability month", "Serving Guy"] + date_labels

    try:
        append_response_row(desired_header, row_map)
        clear_caches()
        st.success("Submission saved to Google Sheets.")
    except Exception as e:
        st.error(f"Failed to save submission: {e}")

    report_text = build_human_report(
        target_month_key=target_month_key,
        name=answers.get("Q_NAME") or "",
        date_labels=date_labels,
        yes_map=yes_map,
    )
    st.markdown("### 📄 Screenshot-friendly report (text)")
    st.code(report_text, language=None)

# ─────────────────────────────────────────────────────────────
# Admin: exports + non-responders (current month) + diagnostics
# ─────────────────────────────────────────────────────────────
def compute_nonresponders_current_month(sb_names: list[str], responses_df: pd.DataFrame, month_key: str) -> pd.DataFrame:
    base = pd.DataFrame({"Serving Guy": sorted({n for n in sb_names if n})})
    if base.empty:
        return pd.DataFrame(columns=["Serving Guy", "Status"])

    if responses_df is None or responses_df.empty:
        out = base.copy()
        out["Status"] = "Non-responder"
        return out

    df = responses_df.copy()
    for col in ["Availability month", "Serving Guy"]:
        if col not in df.columns:
            df[col] = ""

    df["Availability month"] = df["Availability month"].astype(str).str.strip()
    df["Serving Guy"] = df["Serving Guy"].astype(str).str.strip()
    df = df[df["Availability month"] == month_key].copy()

    responded = set(df["Serving Guy"].dropna().tolist())
    out = base[~base["Serving Guy"].isin(responded)].copy()
    out["Status"] = "Non-responder"
    return out.reset_index(drop=True)


with st.expander("Admin"):
    st.caption("Mode: Google Sheets (guys tabs)")
    if not ADMIN_KEY:
        st.info("To protect exports, set an ADMIN_KEY in Streamlit Secrets (optional).")

    key = st.text_input("Enter admin key to access exports", type="password")
    if ADMIN_KEY and key != ADMIN_KEY:
        if key:
            st.error("Incorrect admin key.")
    else:
        st.success("Admin unlocked.")
        try:
            responses_df = fetch_responses_df()
        except Exception as e:
            st.error(f"Could not load responses: {e}")
            responses_df = pd.DataFrame()

        st.write(f"Total submissions (all months): **{len(responses_df)}**")
        if not responses_df.empty:
            st.dataframe(responses_df, use_container_width=True)

        st.markdown("### ❌ Non-responders (current month only)")
        nonresp_df = compute_nonresponders_current_month(guys, responses_df, target_month_key)
        st.write(f"Shown: **{len(nonresp_df)}**  |  Total guys in SB: **{len(guys)}**")
        st.dataframe(nonresp_df[["Serving Guy", "Status"]], use_container_width=True)
