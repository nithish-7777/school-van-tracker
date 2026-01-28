import os
import sqlite3
import json
from contextlib import closing
from datetime import datetime, date, time, timedelta
from typing import List, Optional
import hashlib  

import pandas as pd
import plotly.express as px
import streamlit as st
import streamlit.components.v1 as components


DB_PATH = "school_van_complaints.db"
UPLOAD_DIR = "uploads"


# -----------------------------
# Database helpers
# -----------------------------


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    with closing(get_connection()) as conn, conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS complaints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bus_number INTEGER NOT NULL,
                complaint_datetime TEXT NOT NULL,
                problem_type TEXT NOT NULL,
                details TEXT NOT NULL,
                photo_paths TEXT,
                status TEXT NOT NULL DEFAULT 'Open',
                org_response TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                resolved_at TEXT,
                chairman_reaction TEXT
            )
            """
        )

        # Seed default users if not present
        users = [
            ("principal", "principal123", "principal"),
            ("org", "org123", "org"),
            ("chairman", "chairman123", "chairman"),
        ]
        for username, password, role in users:
            conn.execute(
                """
                INSERT OR IGNORE INTO users (username, password, role)
                VALUES (?, ?, ?)
                """,
                (username, password, role),
            )


def fetch_user(username: str, password: str) -> Optional[sqlite3.Row]:
    """FIXED - Now hashes password for login"""
    hashed_password = hashlib.sha256(password.encode('utf-8')).hexdigest()
    with closing(get_connection()) as conn, conn:
        cur = conn.execute(
            "SELECT * FROM users WHERE username = ? AND password = ?",
            (username.strip(), hashed_password),
        )
        return cur.fetchone()


def insert_complaint(
    bus_number: int,
    complaint_dt: datetime,
    problem_type: str,
    details: str,
    photo_paths: List[str],
):
    now = datetime.utcnow().isoformat()
    with closing(get_connection()) as conn, conn:
        conn.execute(
            """
            INSERT INTO complaints (
                bus_number,
                complaint_datetime,
                problem_type,
                details,
                photo_paths,
                status,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'Open', ?, ?)
            """,
            (
                bus_number,
                complaint_dt.isoformat(),
                problem_type,
                details,
                json.dumps(photo_paths),
                now,
                now,
            ),
        )


def update_complaint_status(
    complaint_id: int,
    status: str,
    response: Optional[str],
):
    now = datetime.utcnow().isoformat()
    resolved_at = now if status == "Resolved" else None
    with closing(get_connection()) as conn, conn:
        conn.execute(
            """
            UPDATE complaints
            SET status = ?,
                org_response = ?,
                updated_at = ?,
                resolved_at = CASE WHEN ? IS NULL THEN resolved_at ELSE ? END
            WHERE id = ?
            """,
            (status, response, now, resolved_at, resolved_at, complaint_id),
        )


def set_chairman_reaction(complaint_id: int, reaction: str):
    now = datetime.utcnow().isoformat()
    with closing(get_connection()) as conn, conn:
        conn.execute(
            """
            UPDATE complaints
            SET chairman_reaction = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (reaction, now, complaint_id),
        )


def fetch_complaints(
    bus: Optional[int] = None,
    problem: Optional[str] = None,
    status: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
):
    query = "SELECT * FROM complaints WHERE 1=1"
    params: List = []

    if bus is not None:
        query += " AND bus_number = ?"
        params.append(bus)
    if problem:
        query += " AND problem_type LIKE ?"
        params.append(f"%{problem}%")
    if status and status != "All":
        query += " AND status = ?"
        params.append(status)
    if start_date:
        query += " AND date(complaint_datetime) >= ?"
        params.append(start_date.isoformat())
    if end_date:
        query += " AND date(complaint_datetime) <= ?"
        params.append(end_date.isoformat())

    query += " ORDER BY complaint_datetime DESC"

    with closing(get_connection()) as conn, conn:
        cur = conn.execute(query, params)
        rows = cur.fetchall()
        return rows


def complaints_to_df(rows: List[sqlite3.Row]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(
            columns=[
                "ID",
                "Bus",
                "Date/Time",
                "Problem",
                "Status",
                "Org Response",
                "Photos",
            ]
        )
    data = []
    for r in rows:
        photos = json.loads(r["photo_paths"] or "[]")
        data.append(
            {
                "ID": r["id"],
                "Bus": r["bus_number"],
                "Date/Time": r["complaint_datetime"],
                "Problem": r["problem_type"],
                "Status": r["status"],
                "Org Response": r["org_response"] or "",
                "Photos": len(photos),
            }
        )
    return pd.DataFrame(data)


# -----------------------------
# PWA / Theming helpers
# -----------------------------


def inject_pwa_and_theme():
    """
    Injects manifest + client-side service worker registration for basic PWA support
    and sets some global CSS for a polished, mobile-first look.
    """
    manifest = {
        "name": "School Van Complaint Tracker",
        "short_name": "Van Complaints",
        "start_url": ".",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0ea5e9",
        "icons": [
            {
                "src": "https://static.streamlit.io/examples/favicon.png",
                "sizes": "192x192",
                "type": "image/png",
            },
            {
                "src": "https://static.streamlit.io/examples/favicon.png",
                "sizes": "512x512",
                "type": "image/png",
            },
        ],
    }

    manifest_json = json.dumps(manifest)

    sw_js = """
    const CACHE_NAME = 'van-complaints-cache-v1';
    const OFFLINE_URLS = ['.', '/'];

    self.addEventListener('install', event => {
      event.waitUntil(
        caches.open(CACHE_NAME).then(cache => cache.addAll(OFFLINE_URLS))
      );
      self.skipWaiting();
    });

    self.addEventListener('activate', event => {
      event.waitUntil(
        caches.keys().then(keys =>
          Promise.all(
            keys.map(key => {
              if (key !== CACHE_NAME) return caches.delete(key);
            })
          )
        )
      );
      self.clients.claim();
    });

    self.addEventListener('fetch', event => {
      if (event.request.method !== 'GET') return;
      event.respondWith(
        caches.match(event.request).then(response => {
          return (
            response ||
            fetch(event.request).catch(() => caches.match('.'))
          );
        })
      );
    });
    """

    html = f"""
    <script>
      // Inject manifest dynamically
      const existing = document.querySelector('link[rel="manifest"]');
      if (!existing) {{
        const manifest = document.createElement('link');
        manifest.rel = 'manifest';
        const blob = new Blob(
          [JSON.stringify({manifest_json})],
          {{ type: 'application/json' }}
        );
        manifest.href = URL.createObjectURL(blob);
        document.head.appendChild(manifest);
      }}

      // Register service worker
      if ('serviceWorker' in navigator) {{
        const swBlob = new Blob(
          [`{sw_js}`],
          {{ type: 'text/javascript' }}
        );
        const swUrl = URL.createObjectURL(swBlob);
        navigator.serviceWorker
          .register(swUrl)
          .catch(err => console.error('SW registration failed', err));
      }}
    </script>
    <style>
      /* Global app background */
      body {{
        background: radial-gradient(circle at top left, #0f172a, #020617);
        color: #e5e7eb;
      }}
      .van-metric-card {{
        border-radius: 18px;
        padding: 1rem 1.25rem;
        background: linear-gradient(135deg, #0ea5e9, #22c55e);
        color: white;
        box-shadow: 0 18px 45px rgba(15, 23, 42, 0.6);
      }}
      .van-metric-card.alt {{
        background: linear-gradient(135deg, #6366f1, #ec4899);
      }}
      .van-metric-label {{
        font-size: 0.8rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        opacity: 0.85;
      }}
      .van-metric-value {{
        font-size: 1.8rem;
        font-weight: 700;
        margin-top: 0.2rem;
      }}
      @media (max-width: 768px) {{
        .block-container {{
          padding-left: 0.75rem;
          padding-right: 0.75rem;
          padding-top: 0.75rem;
        }}
      }}
    </style>
    """

    components.html(html, height=0)


# -----------------------------
# Authentication
# -----------------------------


def login():
    st.sidebar.markdown("### 🔐 Sign In / Sign Up")
    
    tab1, tab2 = st.sidebar.tabs(["Sign In", "Sign Up"])
    
    with tab1:
        st.markdown("**Already registered? Sign in here**")
        username = st.text_input("👤 Username", key="login_user")
        password = st.text_input("🔑 Password", type="password", key="login_pass")
        if st.button("🚀 Sign In", type="primary", key="signin_btn"):
            if username and password:
                user = fetch_user(username, password)
                if user:
                    st.session_state["user"] = {
                        "id": user["id"],
                        "username": user["username"],
                        "role": user["role"],
                    }
                    st.success(f"✅ Welcome {user['username']}!")
                    st.rerun()
                else:
                    st.error("❌ Wrong username/password")
                    st.info("💡 Check database with sqlite3 command above")
            else:
                st.warning("👆 Enter username/password")
    
    with tab2:
        st.markdown("**New user? Create account**")
        new_username = st.text_input("👤 New Username", key="new_user")
        new_password = st.text_input("🔑 New Password", type="password", key="new_pass")
        role = st.selectbox("Role", ["principal", "org", "chairman"], key="new_role")
        
        if st.button("✅ Create Account", key="signup_btn"):
            if new_username and new_password:
                hashed_pw = hashlib.sha256(new_password.encode('utf-8')).hexdigest()
                try:
                    with closing(get_connection()) as conn, conn:
                        conn.execute(
                            "INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                            (new_username.strip(), hashed_pw, role)
                        )
                        conn.commit()
                    st.success(f"✅ {new_username} created! Now Sign In above 👆")
                    st.rerun()
                except Exception as e:
                    st.error("❌ Username exists or error")
            else:
                st.warning("👆 Fill all fields")

# CHANGE 3: Update init_db() default users (around line 60) - just change passwords
users = [
    ("admin_principal", "admin123", "principal"),  # CHANGE PASSWORDS HERE
    ("admin_org", "admin456", "org"),
    ("admin_chairman", "admin789", "chairman"),
]



def logout():
    if "user" in st.session_state:
        del st.session_state["user"]
    st.rerun()


# -----------------------------
# Principal Page
# -----------------------------


def principal_page():
    st.markdown(
        """
        <div style="padding: 0.5rem 0 0.5rem;">
          <h2 style="margin-bottom:0.25rem;">School Van Complaint Form</h2>
          <p style="color:#9ca3af;margin:0;">
            Capture student transport incidents in real time – structured, photographic evidence in under a minute.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.form("principal_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            bus_number = st.selectbox("Bus Number", list(range(1, 71)))
        with col2:
            dt_default = datetime.now()
            complaint_date = st.date_input("Date", dt_default.date())
            complaint_time = st.time_input("Time", dt_default.time())

        problem_type = st.selectbox(
            "Problem Type",
            [
                "Fight",
                "Driver Misconduct",
                "Delay",
                "Breakdown",
                "Other",
            ],
        )

        details = st.text_area(
            "Detailed Description",
            placeholder="Describe what happened, who was involved, and any immediate action taken.",
            height=160,
        )

        photos = st.file_uploader(
            "Attach Photos (optional)",
            type=["png", "jpg", "jpeg"],
            accept_multiple_files=True,
            help="Attach clear evidence of the issue when available.",
        )

        submitted = st.form_submit_button("Submit Complaint", type="primary")

        if submitted:
            if not details.strip():
                st.error("Please provide a detailed description.")
            else:
                # Combine date and time
                complaint_dt = datetime.combine(complaint_date, complaint_time)

                # Save photos to disk
                saved_paths: List[str] = []
                for file in photos or []:
                    safe_name = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S%f')}_{file.name}"
                    file_path = os.path.join(UPLOAD_DIR, safe_name)
                    with open(file_path, "wb") as f:
                        f.write(file.getbuffer())
                    saved_paths.append(file_path)

                insert_complaint(
                    bus_number=bus_number,
                    complaint_dt=complaint_dt,
                    problem_type=problem_type,
                    details=details,
                    photo_paths=saved_paths,
                )
                st.success("Complaint submitted successfully.")

    st.markdown("### Recent Complaints")
    rows = fetch_complaints()
    df = complaints_to_df(rows)
    st.dataframe(df.head(10), use_container_width=True)


# -----------------------------
# Organization Page
# -----------------------------


def org_page():
    st.markdown(
        """
        <div style="padding: 0.5rem 0 0.75rem;">
          <h2 style="margin-bottom:0.25rem;">Operations Control – All Complaints</h2>
          <p style="color:#9ca3af;margin:0;">
            Monitor, triage, and close the loop on every school van incident.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    with st.expander("Filters", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            bus = st.selectbox("Bus", ["All"] + list(range(1, 71)))
        with c2:
            problem = st.text_input("Problem contains")
        with c3:
            status = st.selectbox("Status", ["All", "Open", "In Progress", "Resolved"])

    bus_filter = None if bus == "All" else int(bus)
    rows = fetch_complaints(
        bus=bus_filter,
        problem=problem or None,
        status=status if status != "All" else None,
    )
    df = complaints_to_df(rows)

    st.markdown("#### Complaints")
    st.dataframe(df, use_container_width=True)

    if not df.empty:
        st.markdown("#### Update Status / Add Response")
        selected_id = st.selectbox("Select Complaint ID", df["ID"].tolist())
        selected_row = next(r for r in rows if r["id"] == selected_id)

        col1, col2 = st.columns(2)
        with col1:
            new_status = st.selectbox(
                "Status",
                ["Open", "In Progress", "Resolved"],
                index=["Open", "In Progress", "Resolved"].index(
                    selected_row["status"]
                ),
            )
        with col2:
            st.write(
                f"**Bus {selected_row['bus_number']} – {selected_row['problem_type']}**"
            )
            st.caption(
                datetime.fromisoformat(selected_row["complaint_datetime"]).strftime(
                    "%d %b %Y %H:%M"
                )
            )

        response = st.text_area(
            "Organization Response / Action Taken",
            value=selected_row["org_response"] or "",
            height=140,
        )

        if st.button("Save Update", type="primary"):
            update_complaint_status(selected_id, new_status, response.strip() or None)
            st.success("Complaint updated.")
            st.rerun()

        photos = json.loads(selected_row["photo_paths"] or "[]")
        if photos:
            st.markdown("##### Photos")
            pcols = st.columns(min(3, len(photos)))
            for idx, path in enumerate(photos):
                try:
                    with open(path, "rb") as f:
                        img_bytes = f.read()
                    pcols[idx % len(pcols)].image(
                        img_bytes, use_column_width=True, caption=os.path.basename(path)
                    )
                except FileNotFoundError:
                    pass


# -----------------------------
# Chairman Dashboard
# -----------------------------


def compute_resolution_metrics(rows: List[sqlite3.Row]):
    total = len(rows)
    open_count = sum(1 for r in rows if r["status"] == "Open")

    today_str = date.today().isoformat()
    resolved_today = 0
    durations: List[float] = []

    for r in rows:
        if r["resolved_at"]:
            resolved_dt = datetime.fromisoformat(r["resolved_at"])
            created_dt = datetime.fromisoformat(r["created_at"])
            durations.append((resolved_dt - created_dt).total_seconds() / 3600.0)
            if resolved_dt.date().isoformat() == today_str:
                resolved_today += 1

    avg_hours = sum(durations) / len(durations) if durations else None
    return total, open_count, resolved_today, avg_hours


def chairman_page():
    st.markdown(
        """
        <div style="padding: 0.25rem 0 0.75rem;">
          <h2 style="margin-bottom:0.25rem;">Chairman Command Center</h2>
          <p style="color:#9ca3af;margin:0;">
            Executive overview of route safety, escalation hygiene, and organizational responsiveness.
          </p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    rows = fetch_complaints()
    total, open_count, resolved_today, avg_hours = compute_resolution_metrics(rows)

    # Metric cards with gradient styling
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown(
            f"""
            <div class="van-metric-card">
              <div class="van-metric-label">Total Issues</div>
              <div class="van-metric-value">{total}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            f"""
            <div class="van-metric-card alt">
              <div class="van-metric-label">Open</div>
              <div class="van-metric-value">{open_count}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            f"""
            <div class="van-metric-card">
              <div class="van-metric-label">Resolved Today</div>
              <div class="van-metric-value">{resolved_today}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    with c4:
        avg_display = f"{avg_hours:.1f} h" if avg_hours is not None else "—"
        st.markdown(
            f"""
            <div class="van-metric-card alt">
              <div class="van-metric-label">Avg Resolution Time</div>
              <div class="van-metric-value">{avg_display}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("---")

    with st.expander("Analytics Filters", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            bus = st.selectbox("Bus", ["All"] + list(range(1, 71)), key="chair_bus")
        with c2:
            start = st.date_input(
                "From Date",
                value=date.today() - timedelta(days=30),
                key="chair_start",
            )
        with c3:
            end = st.date_input(
                "To Date",
                value=date.today(),
                key="chair_end",
            )

        c4, _ = st.columns([1, 2])
        with c4:
            status = st.selectbox(
                "Status", ["All", "Open", "In Progress", "Resolved"], key="chair_status"
            )

    bus_filter = None if bus == "All" else int(bus)
    filtered_rows = fetch_complaints(
        bus=bus_filter,
        status=status if status != "All" else None,
        start_date=start,
        end_date=end,
    )

    # Pie chart – status breakdown
    if filtered_rows:
        df_chart = pd.DataFrame(
            [
                {
                    "Status": r["status"],
                    "Bus": f"Bus {r['bus_number']}",
                }
                for r in filtered_rows
            ]
        )
        pie = px.pie(
            df_chart,
            names="Status",
            title="Status Breakdown",
            color="Status",
            color_discrete_map={
                "Open": "#f97316",
                "In Progress": "#eab308",
                "Resolved": "#22c55e",
            },
        )
        pie.update_traces(textposition="inside", textinfo="percent+label")
        pie.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#e5e7eb",
        )
        st.plotly_chart(pie, use_container_width=True)
    else:
        st.info("No complaints for the selected filters.")

    # Detailed table
    st.markdown("### Detailed Complaints")

    def detailed_df(rows_: List[sqlite3.Row]) -> pd.DataFrame:
        if not rows_:
            return pd.DataFrame(
                columns=[
                    "ID",
                    "Bus",
                    "Date/Time",
                    "Status",
                    "Problem",
                    "Details",
                    "Org Response",
                    "Photos",
                    "Reaction",
                ]
            )
        data = []
        for r in rows_:
            photos = json.loads(r["photo_paths"] or "[]")
            data.append(
                {
                    "ID": r["id"],
                    "Bus": r["bus_number"],
                    "Date/Time": r["complaint_datetime"],
                    "Status": r["status"],
                    "Problem": r["problem_type"],
                    "Details": r["details"],
                    "Org Response": r["org_response"] or "",
                    "Photos": len(photos),
                    "Reaction": r["chairman_reaction"] or "",
                }
            )
        return pd.DataFrame(data)

    df_full = detailed_df(filtered_rows)

    # Export options
    export_cols = st.columns(2)
    with export_cols[0]:
        csv_data = df_full.to_csv(index=False).encode("utf-8")
        st.download_button(
            "Download CSV",
            csv_data,
            file_name="van_complaints.csv",
            mime="text/csv",
            use_container_width=True,
        )
    with export_cols[1]:
        # Browser-native print dialog for quick PDF export
        print_html = """
        <button onclick="window.print()" style="
          width:100%;
          padding:0.6rem 1rem;
          border-radius:0.75rem;
          border:none;
          background:linear-gradient(135deg,#6366f1,#ec4899);
          color:white;
          font-weight:600;
          cursor:pointer;
        ">
          Print / Save as PDF
        </button>
        """
        components.html(print_html, height=52)

    st.dataframe(
        df_full[
            [
                "ID",
                "Bus",
                "Date/Time",
                "Status",
                "Problem",
                "Org Response",
                "Photos",
                "Reaction",
            ]
        ],
        use_container_width=True,
    )

    if not df_full.empty:
        st.markdown("#### Inspect & React")
        selected_id = st.selectbox("Select Complaint ID", df_full["ID"].tolist())
        row = next(r for r in filtered_rows if r["id"] == selected_id)
        photos = json.loads(row["photo_paths"] or "[]")

        with st.expander(
            f"Bus {row['bus_number']} – {row['problem_type']} (Status: {row['status']})",
            expanded=True,
        ):
            st.write("**Complaint Details**")
            st.write(row["details"])
            st.write("---")
            st.write("**Organization Response**")
            st.write(row["org_response"] or "_No response yet._")

            if photos:
                st.markdown("**Photos**")
                pcols = st.columns(min(3, len(photos)))
                for idx, path in enumerate(photos):
                    try:
                        with open(path, "rb") as f:
                            img_bytes = f.read()
                        pcols[idx % len(pcols)].image(
                            img_bytes,
                            use_column_width=True,
                            caption=os.path.basename(path),
                        )
                    except FileNotFoundError:
                        pass

            st.write("---")
            st.write("**Chairman Reaction**")
            r_cols = st.columns(3)
            if r_cols[0].button("👍 Great", key=f"reaction_great_{selected_id}"):
                set_chairman_reaction(selected_id, "Great")
                st.success("Reaction recorded as Great.")
                st.rerun()
            if r_cols[1].button("👎 Followup", key=f"reaction_followup_{selected_id}"):
                set_chairman_reaction(selected_id, "Followup")
                st.success("Reaction recorded as Followup.")
                st.rerun()
            if r_cols[2].button("💯 Perfect", key=f"reaction_perfect_{selected_id}"):
                set_chairman_reaction(selected_id, "Perfect")
                st.success("Reaction recorded as Perfect.")
                st.rerun()


# -----------------------------
# Main app
# -----------------------------


def main():
    st.set_page_config(
        page_title="School Van Complaint Tracker",
        page_icon="🚌",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    inject_pwa_and_theme()
    init_db()

    st.sidebar.markdown("## School Van Complaint Tracker")
    st.sidebar.caption("Production-ready demo • Streamlit PWA + SQLite")

    if "user" not in st.session_state:
        login()
        st.info("Please log in using principal / org / chairman credentials.")
        return

    user = st.session_state["user"]
    st.sidebar.markdown(
        f"**User:** {user['username']}  \n**Role:** {user['role'].title()}"
    )
    if st.sidebar.button("Logout"):
        logout()

    role = user["role"]

    if role == "principal":
        principal_page()
    elif role == "org":
        org_page()
    elif role == "chairman":
        chairman_page()
    else:
        st.error("Unknown role.")


if __name__ == "__main__":
    main()

