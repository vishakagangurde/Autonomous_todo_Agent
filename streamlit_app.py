"""
streamlit_app.py — Autonomous DOCX Agent UI
Strict layout as specified.
"""

import time
import requests
import streamlit as st

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Autonomous DOCX Agent",
    page_icon="📄",
    layout="centered",
    initial_sidebar_state="collapsed",
)

DEFAULT_API_URL = "http://localhost:8000"

# ---------------------------------------------------------------------------
# CSS
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

.stApp {
    background: linear-gradient(135deg, #0f0c29 0%, #302b63 50%, #24243e 100%);
    color: #e2e8f0;
}

[data-testid="collapsedControl"] { display: none; }

/* Buttons */
.stButton > button {
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    color: white; border: none; border-radius: 8px;
    padding: 10px 28px; font-weight: 600; font-size: 15px;
    transition: all 0.2s ease; width: 100%;
}
.stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(102,126,234,0.45);
    color: white;
}
.stDownloadButton > button {
    background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
    color: #0f0c29; border: none; border-radius: 8px;
    padding: 10px 28px; font-weight: 700; font-size: 15px;
    transition: all 0.2s ease; width: 100%;
}
.stDownloadButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 6px 20px rgba(56,239,125,0.4);
}

/* Text area */
.stTextArea textarea {
    background: rgba(255,255,255,0.05) !important;
    border: 1px solid rgba(255,255,255,0.15) !important;
    border-radius: 8px !important;
    color: #e2e8f0 !important;
    font-family: 'Inter', sans-serif !important;
    font-size: 14px !important;
}

/* Section dividers */
.section-header {
    font-size: 11px;
    font-weight: 700;
    color: #a78bfa;
    text-transform: uppercase;
    letter-spacing: 2px;
    margin: 0 0 14px 0;
    padding-bottom: 8px;
    border-bottom: 1px solid rgba(167,139,250,0.25);
}

/* Step row */
.step-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 7px 0;
    font-size: 14px;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
.step-check { color: #38ef7d; font-weight: 700; width: 18px; }
.step-spin  { color: #fbbf24; width: 18px; }
.step-label { flex: 1; color: #e2e8f0; }
.step-time  {
    font-size: 11px; color: #a78bfa; font-weight: 600;
    background: rgba(167,139,250,0.1);
    padding: 2px 8px; border-radius: 12px;
}

/* Task list item */
.task-item {
    display: flex; gap: 10px; align-items: flex-start;
    padding: 6px 0; font-size: 13px; color: #cbd5e1;
    border-bottom: 1px solid rgba(255,255,255,0.04);
}
.task-num { color: #a78bfa; font-weight: 600; width: 20px; }

/* Log row */
.log-row {
    display: flex; justify-content: space-between; align-items: center;
    padding: 8px 12px;
    background: rgba(255,255,255,0.03);
    border-radius: 6px; margin-bottom: 6px;
    font-size: 13px;
}
.log-ok   { color: #38ef7d; font-weight: 700; }
.log-fail { color: #f87171; font-weight: 700; }

/* Info box */
.info-box {
    background: rgba(167,139,250,0.07);
    border: 1px solid rgba(167,139,250,0.2);
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 6px;
}
.info-label { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
.info-value { font-size: 15px; font-weight: 600; color: #e2e8f0; }

/* Stat grid */
.stat-box {
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 10px;
    padding: 14px 16px;
    text-align: center;
}
.stat-label { font-size: 11px; color: #94a3b8; margin-bottom: 4px; }
.stat-value { font-size: 22px; font-weight: 700; color: #a78bfa; }

hr { border-color: rgba(255,255,255,0.07) !important; }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_api_url() -> str:
    return st.session_state.get("api_url", DEFAULT_API_URL).rstrip("/")

def api_health(base: str) -> dict | None:
    try:
        r = requests.get(f"{base}/health", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None

def api_generate(base: str, prompt: str) -> dict:
    r = requests.post(f"{base}/agent", json={"request": prompt}, timeout=300)
    r.raise_for_status()
    return r.json()

def api_download(base: str, filename: str) -> bytes:
    r = requests.get(f"{base}/download/{filename}", timeout=30)
    r.raise_for_status()
    return r.content

def section_header(title: str):
    st.markdown(f'<p class="section-header">{title}</p>', unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# ① HEADER
# ---------------------------------------------------------------------------
st.markdown("""
<div style="text-align:center; padding: 32px 0 24px 0;">
    <h1 style="font-size:2.2rem; font-weight:700; margin:0;
               background:linear-gradient(135deg,#a78bfa,#67e8f9);
               -webkit-background-clip:text; -webkit-text-fill-color:transparent;">
        📄 Autonomous DOCX Agent
    </h1>
</div>
""", unsafe_allow_html=True)

# Backend badge
health = api_health(get_api_url())
status_badge = (
    '<span style="color:#38ef7d;font-size:12px;">● Online</span>'
    if health else
    '<span style="color:#f87171;font-size:12px;">● Offline — run: uvicorn app:app --reload</span>'
)
st.markdown(f'<p style="text-align:center;margin-bottom:24px;">{status_badge}</p>',
            unsafe_allow_html=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# ② INPUT
# ---------------------------------------------------------------------------
section_header("Describe Your Request")

prompt = st.text_area(
    "request",
    value=st.session_state.get("prompt_text", ""),
    height=110,
    placeholder="e.g. Create a quarterly product review meeting minutes for the engineering team...",
    label_visibility="collapsed",
    key="prompt_input",
)

with st.expander("💡 Example prompts"):
    examples = [
        "Create a quarterly product review meeting minutes for the engineering team",
        "Write a business proposal for a SaaS startup targeting small retailers",
        "Generate a technical design document for a real-time notification system",
        "Write a project plan for migrating our backend to microservices",
    ]
    for ex in examples:
        if st.button(ex, key=f"ex_{ex[:30]}"):
            st.session_state["prompt_text"] = ex
            st.rerun()

generate_clicked = st.button("⚡ Generate Document", use_container_width=True)

st.markdown("---")

# ---------------------------------------------------------------------------
# ③ GENERATION — live pipeline steps
# ---------------------------------------------------------------------------
PIPELINE_STEPS = [
    ("Analyze Request",      None),
    ("Detect Document Type", "planning_secs"),
    ("Extract Requirements", None),
    ("Generate Task List",   None),
    ("Generate Sections",    "generation_secs"),
    ("Review Document",      "review_secs"),
    ("Generate DOCX",        "docx_secs"),
]

AGENT_LOGS = [
    "Planner Agent",
    "Content Agent",
    "Review Agent",
    "Document Generator",
]

if generate_clicked:
    if not prompt.strip():
        st.error("⚠️ Please enter a document description.")
    elif not health:
        st.error("❌ Backend is offline.")
    else:
        section_header("Agent Execution Plan")

        # Render pending steps
        step_cols = []
        for label, _ in PIPELINE_STEPS:
            c1, c2, c3 = st.columns([0.4, 5, 1.5])
            c1.markdown('<span class="step-spin">⏳</span>', unsafe_allow_html=True)
            c2.markdown(f'<span style="color:#64748b;font-size:14px;">{label}</span>',
                        unsafe_allow_html=True)
            step_cols.append((c1, c2, c3))

        st.markdown("---")

        try:
            t_start = time.time()
            result = api_generate(get_api_url(), prompt.strip())
            elapsed = time.time() - t_start

            timings = result.get("plan_summary", {}).get("stage_timings", {})

            # Update steps to ✓
            for i, (c1, c2, c3) in enumerate(step_cols):
                _, timing_key = PIPELINE_STEPS[i]
                t = timings.get(timing_key) if timing_key else None
                c1.markdown('<span class="step-check">✓</span>', unsafe_allow_html=True)
                c2.markdown(f'<b>{PIPELINE_STEPS[i][0]}</b>', unsafe_allow_html=True)
                if t:
                    c3.markdown(f'<span class="step-time">{t:.1f}s</span>',
                                unsafe_allow_html=True)

            st.session_state["last_result"] = result
            st.session_state["last_elapsed"] = elapsed
            st.session_state["agent_logs_ok"] = True

        except requests.HTTPError as e:
            st.error(f"❌ API Error {e.response.status_code}: {e.response.text}")
            st.session_state["agent_logs_ok"] = False
        except requests.ConnectionError:
            st.error("❌ Could not connect to the backend.")
            st.session_state["agent_logs_ok"] = False
        except Exception as e:
            st.error(f"❌ Unexpected error: {e}")
            st.session_state["agent_logs_ok"] = False

# ---------------------------------------------------------------------------
# ④ RESULTS
# ---------------------------------------------------------------------------
result = st.session_state.get("last_result")

if result:
    status   = result.get("status", "")
    elapsed  = st.session_state.get("last_elapsed", 0)
    plan     = result.get("plan_summary") or {}
    timings  = plan.get("stage_timings", {})
    sections = plan.get("sections", [])
    assump   = plan.get("assumptions_made", [])
    doc_type = plan.get("document_type", "—").replace("_", " ").title()

    # ── If page was reloaded (not just generated) replay the steps ──
    if not generate_clicked:
        section_header("Agent Execution Plan")
        for i, (label, timing_key) in enumerate(PIPELINE_STEPS):
            t = timings.get(timing_key) if timing_key else None
            c1, c2, c3 = st.columns([0.4, 5, 1.5])
            c1.markdown('<span class="step-check">✓</span>', unsafe_allow_html=True)
            c2.markdown(f"**{label}**")
            if t:
                c3.markdown(f'<span class="step-time">{t:.1f}s</span>',
                            unsafe_allow_html=True)
        st.markdown("---")

    # ── Planner Output ──────────────────────────────────────────────
    section_header("Planner Output")

    st.markdown(f"""
    <div class="info-box">
        <div class="info-label">Document Type</div>
        <div class="info-value">{doc_type}</div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("**Task List**")

    # Build numbered task list from pipeline + section names
    task_list = ["Understand request", "Create outline"]
    for s in sections:
        task_list.append(f"Generate {s['section_name']}")
    task_list += ["Review content", "Export DOCX"]

    task_html = ""
    for i, task in enumerate(task_list, 1):
        task_html += (
            f'<div class="task-item">'
            f'<span class="task-num">{i}.</span>'
            f'<span>{task}</span>'
            f'</div>'
        )
    st.markdown(task_html, unsafe_allow_html=True)

    st.markdown("---")

    # ── Engineering Improvement ─────────────────────────────────────
    section_header("Engineering Improvement")

    st.markdown("""
    <div class="info-box">
        <div class="info-label">Implemented</div>
        <div class="info-value" style="color:#38ef7d;">✓ Multi-step Planning</div>
        <div style="margin-top:10px;">
            <div class="info-label">Reason</div>
            <div style="color:#cbd5e1;font-size:13px;">
                Breaks one complex request into smaller executable tasks,
                enabling per-section generation, independent review, and
                targeted revision without reprocessing the whole document.
            </div>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    # ── Execution Summary ───────────────────────────────────────────
    section_header("Execution Summary")

    status_color = "#38ef7d" if status == "success" else "#fbbf24" if status == "partial_success" else "#f87171"
    status_label = {"success": "Success ✓", "partial_success": "Partial ⚠️", "failed": "Failed ✗"}.get(status, status)

    c1, c2, c3, c4 = st.columns(4)
    for col, label, value, color in [
        (c1, "Status",             status_label,              status_color),
        (c2, "Sections Generated", str(plan.get("total_sections", len(sections))), "#a78bfa"),
        (c3, "Generation Time",    f"{elapsed:.1f}s",         "#67e8f9"),
        (c4, "Assumptions",        str(len(assump)),          "#fbbf24"),
    ]:
        col.markdown(
            f'<div class="stat-box">'
            f'<div class="stat-label">{label}</div>'
            f'<div class="stat-value" style="color:{color};font-size:{"15px" if label=="Status" else "22px"};">{value}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    if timings:
        st.markdown("<br>**Stage Timings**", unsafe_allow_html=True)
        tc1, tc2, tc3, tc4 = st.columns(4)
        for col, label, key in [
            (tc1, "Planning",   "planning_secs"),
            (tc2, "Generation", "generation_secs"),
            (tc3, "Review",     "review_secs"),
            (tc4, "DOCX",       "docx_secs"),
        ]:
            val = timings.get(key)
            col.metric(label, f"{val:.1f}s" if val is not None else "—")

    # Show assumptions if any
    if assump:
        st.markdown("<br>**AI Assumptions**", unsafe_allow_html=True)
        for a in assump:
            field = a.get("field", "")
            value = a.get("value", "")
            reasoning = a.get("reasoning", "")
            st.markdown(
                f'<div style="background:rgba(167,139,250,0.07);border-left:3px solid #a78bfa;'
                f'border-radius:0 6px 6px 0;padding:9px 14px;margin-bottom:6px;font-size:13px;">'
                f'<span style="color:#a78bfa;font-weight:600;">{field}</span>'
                f'<span style="color:#e2e8f0;"> → {value}</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown("---")

    # ── Download ────────────────────────────────────────────────────
    file_path = result.get("file_path")
    if file_path and status in ("success", "partial_success"):
        section_header("Download")
        filename = file_path.replace("\\", "/").split("/")[-1]
        st.markdown(
            f'<p style="color:#94a3b8;font-size:13px;margin-bottom:12px;">'
            f'📎 <code>{filename}</code></p>',
            unsafe_allow_html=True,
        )
        try:
            docx_bytes = api_download(get_api_url(), filename)
            st.download_button(
                label="⬇️ Download DOCX",
                data=docx_bytes,
                file_name=filename,
                mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                use_container_width=True,
            )
        except Exception as e:
            st.warning(f"Could not fetch file: {e}")

        st.markdown("---")

    # ── Logs ────────────────────────────────────────────────────────
    with st.expander("📋 Logs (Optional)", expanded=False):
        logs_ok = st.session_state.get("agent_logs_ok", status in ("success", "partial_success"))
        for agent in AGENT_LOGS:
            mark = '<span class="log-ok">✔</span>' if logs_ok else '<span class="log-fail">✗</span>'
            st.markdown(
                f'<div class="log-row"><span>{agent}</span>{mark}</div>',
                unsafe_allow_html=True,
            )
        if result.get("error_detail"):
            st.code(result["error_detail"], language="text")
