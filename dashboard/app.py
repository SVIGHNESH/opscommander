"""Streamlit dashboard for OpsCommander.

A single-file operator console: trigger incidents, watch the agent pipeline,
approve escalated remediations, and read the generated report.

Run with:  streamlit run dashboard/app.py
"""

from __future__ import annotations

import os
import sys

# Make the src/ package importable when run directly via `streamlit run`.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import streamlit as st  # noqa: E402

from opscommander.config import get_settings  # noqa: E402
from opscommander.models import IncidentStatus  # noqa: E402
from opscommander.orchestrator import Orchestrator  # noqa: E402
from opscommander.reporting.report_builder import ReportBuilder  # noqa: E402
from opscommander.storage import get_repository  # noqa: E402

st.set_page_config(page_title="OpsCommander", page_icon="🛡️", layout="wide")

settings = get_settings()
repo = get_repository(settings)
orch = Orchestrator(settings, repo)
builder = ReportBuilder(settings)

SEV_COLOR = {
    "Critical": "🔴",
    "High": "🟠",
    "Medium": "🟡",
    "Low": "🟢",
    "Info": "⚪",
}
STAGES = [
    "detection",
    "log_analysis",
    "infrastructure",
    "recommendation",
    "approval",
    "remediation",
    "reporting",
]

st.title("🛡️ OpsCommander")
st.caption(f"Multi-agent incident response · mode: **{settings.mode}**")

# --------------------------------------------------------------------------- #
# Sidebar: trigger a new incident
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Trigger incident")
    with st.form("new_incident"):
        service = st.text_input("Service", "orders-api")
        alarm = st.text_input("Alarm", "Database Timeout")
        severity = st.selectbox(
            "Severity (blank = auto)",
            ["", "Critical", "High", "Medium", "Low"],
        )
        submitted = st.form_submit_button("Run pipeline", type="primary")
    if submitted:
        inc = orch.handle_incident(service, alarm, severity or None)
        st.session_state["selected"] = inc.id
        st.success(f"Ran incident {inc.id}")

    st.divider()
    st.subheader("Presets")
    presets = {
        "Lambda DB timeout": ("orders-api", "Database Timeout", "Critical"),
        "High CPU": ("checkout-svc", "High CPU Utilization", "High"),
        "OOM kill": ("image-worker", "Out Of Memory", "Critical"),
        "API 5xx spike": ("gateway", "5xx Error Spike", "High"),
    }
    for label, (svc, alr, sev) in presets.items():
        if st.button(label, use_container_width=True):
            inc = orch.handle_incident(svc, alr, sev)
            st.session_state["selected"] = inc.id
            st.rerun()

# --------------------------------------------------------------------------- #
# Main: incident list + detail
# --------------------------------------------------------------------------- #
incidents = repo.list(limit=50)
if not incidents:
    st.info("No incidents yet. Trigger one from the sidebar.")
    st.stop()

left, right = st.columns([1, 2])

with left:
    st.subheader("Incidents")
    for inc in incidents:
        sev = SEV_COLOR.get(inc.severity.value, "⚪")
        if st.button(
            f"{sev} {inc.title or inc.service}\n{inc.status.value} · {inc.id}",
            key=inc.id,
            use_container_width=True,
        ):
            st.session_state["selected"] = inc.id

selected_id = st.session_state.get("selected", incidents[0].id)
incident = repo.get(selected_id)

with right:
    if incident is None:
        st.warning("Incident not found.")
        st.stop()

    st.subheader(f"{SEV_COLOR.get(incident.severity.value, '⚪')} {incident.title}")
    c1, c2, c3 = st.columns(3)
    c1.metric("Severity", incident.severity.value)
    c2.metric("Status", incident.status.value)
    c3.metric("Service", incident.service)

    st.markdown(f"**Root cause:** {incident.root_cause or '_undetermined_'}")

    # Pipeline progress
    st.markdown("#### Agent pipeline")
    cols = st.columns(len(STAGES))
    for col, stage in zip(cols, STAGES):
        res = incident.agent_results.get(stage)
        icon = "⚪"
        if res is not None:
            icon = "✅" if res.ok else "⚠️"
        col.markdown(f"<div style='text-align:center'>{icon}<br><small>{stage}</small></div>",
                     unsafe_allow_html=True)

    # Approval action
    if incident.status in (IncidentStatus.AWAITING_APPROVAL, IncidentStatus.ESCALATED):
        st.warning(
            f"⏳ Awaiting human approval for action "
            f"`{incident.approval.action if incident.approval else 'n/a'}` — "
            f"{incident.approval.reason if incident.approval else ''}"
        )
        approver = st.text_input("Approver", "operator")
        if st.button("✅ Approve & remediate", type="primary"):
            orch.resume_after_approval(incident.id, approver)
            st.rerun()

    # Recommendations
    if incident.recommendations:
        st.markdown("#### Recommendations")
        for r in incident.recommendations:
            st.markdown(
                f"- **{r.title}** · `{r.action}` · confidence {r.confidence:.0%}\n"
                f"  \n  {r.rationale}"
            )

    # Timeline + report
    with st.expander("Timeline", expanded=False):
        for t in incident.timeline:
            st.markdown(f"`{t.timestamp}` **[{t.stage}]** {t.message}")

    with st.expander("Full report (Markdown)", expanded=False):
        st.markdown(builder.render_markdown(incident))
