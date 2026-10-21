"""Streamlit UI: run a web-vs-app parity audit and browse its reports.

    streamlit run app.py
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from parity_agent.config import PROJECT_DIR, REPORTS_DIR
from parity_agent.llm import get_llm

st.set_page_config(page_title="UI Parity Agent", layout="wide")


def list_reports() -> list[Path]:
    if not REPORTS_DIR.exists():
        return []
    return sorted((p for p in REPORTS_DIR.iterdir() if (p / "findings.json").exists()), reverse=True)


def run_audit_subprocess(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the CLI in a subprocess (keeps Playwright's sync API out of Streamlit's script thread)."""
    return subprocess.run(
        [sys.executable, "-m", "parity_agent", "run", *args],
        cwd=PROJECT_DIR, capture_output=True, text=True, timeout=900,
    )


# ---------------------------------------------------------------------------- sidebar: run
llm = get_llm()
st.title("UI Parity Agent")
st.caption("Crawls a website and its mobile app, matches pages, runs happy-path flows and reports every inconsistency.")
if llm.is_mock:
    st.warning(llm.describe())
else:
    st.info(llm.describe())

with st.sidebar:
    st.header("Run an audit")
    target = st.radio("Target", ["Bundled demo sites (Nimbus Wireless)", "Custom URLs"])
    web_url = app_url = flows_path = ""
    if target == "Custom URLs":
        web_url = st.text_input("Website start URL", placeholder="https://www.example.com/")
        app_url = st.text_input("App / mobile web start URL", placeholder="https://m.example.com/")
        flows_path = st.text_input("Flows YAML (optional)", placeholder="flows.yaml")
    max_pages = st.slider("Max pages per platform", 5, 100, 30)
    if st.button("Run audit", type="primary", width="stretch"):
        args = ["--max-pages", str(max_pages)]
        if target == "Custom URLs":
            if not (web_url and app_url):
                st.error("Enter both URLs.")
                st.stop()
            args += ["--web", web_url, "--app", app_url] + (["--flows", flows_path] if flows_path else [])
        else:
            args.append("--demo")
        with st.spinner("Crawling both platforms and running flows..."):
            proc = run_audit_subprocess(args)
        if proc.returncode == 0:
            st.success("Audit complete.")
        else:
            st.error("Audit failed.")
        with st.expander("Run log"):
            st.code((proc.stdout or "") + (proc.stderr or ""))

    reports = list_reports()
    st.header("Browse reports")
    if not reports:
        st.info("No reports yet. Run an audit (or `make demo`).")
        st.stop()
    chosen = st.selectbox("Report", reports, format_func=lambda p: p.name)

# ---------------------------------------------------------------------------- report browser
data = json.loads((chosen / "findings.json").read_text())
pages = json.loads((chosen / "pages.json").read_text())
findings = pd.DataFrame(data["findings"])
summary = data["summary"]

cols = st.columns(5)
cols[0].metric("Pages (web / app)", f"{summary['pages_web']} / {summary['pages_app']}")
cols[1].metric("Matched pairs", summary["matched_pairs"])
cols[2].metric("Findings", summary["findings"])
cols[3].metric("High severity", summary["by_severity"].get("high", 0))
if data.get("evaluation"):
    ev = data["evaluation"]["overall"]
    cols[4].metric(f"Recall vs planted (precision {ev['precision']:.0%})", f"{ev['recall']:.0%}")
else:
    cols[4].metric("Flows compared", len(data["flows"]))

tab_over, tab_find, tab_pages, tab_flows, tab_backlog, tab_eval = st.tabs(
    ["Overview", "Findings", "Pages", "Flows", "Backlog", "Evaluation"]
)

with tab_over:
    st.subheader("Executive summary")
    st.write(data["executive_summary"])
    st.subheader("Prioritised recommendations")
    st.dataframe(pd.DataFrame(data["recommendations"]), width="stretch", hide_index=True)
    st.download_button(
        "Download self-contained HTML report", (chosen / "report.html").read_bytes(),
        file_name=f"ui-parity-{chosen.name}.html", mime="text/html",
    )
    st.caption(f"{data['llm']} · usage: {data['llm_usage']}")

with tab_find:
    if findings.empty:
        st.success("No differences found.")
    else:
        c1, c2 = st.columns(2)
        cats = c1.multiselect("Category", sorted(findings["category"].unique()), default=sorted(findings["category"].unique()))
        sevs = c2.multiselect("Severity", ["high", "medium", "low"], default=["high", "medium", "low"])
        view = findings[findings["category"].isin(cats) & findings["severity"].isin(sevs)]
        st.dataframe(
            view[["id", "severity", "category", "page", "description", "web_value", "app_value", "action", "proposed_fix"]],
            width="stretch", hide_index=True,
        )

with tab_pages:
    web_by_path = {p["path"]: p for p in pages["web"]}
    app_by_path = {p["path"]: p for p in pages["app"]}
    options = [f"{pr['web_name']}  <->  {pr['app_name']}" for pr in data["pairs"]]
    if options:
        idx = st.selectbox("Page pair", range(len(options)), format_func=lambda i: options[i])
        pr = data["pairs"][idx]
        web_page, app_page = web_by_path[pr["web"]], app_by_path[pr["app"]]
        st.caption(f"{pr['web']} <-> {pr['app']} · match score {pr['score']:.2f} ({pr['method']})")
        pf = findings[(findings["web_path"] == pr["web"]) & (findings["app_path"] == pr["app"])] if not findings.empty else findings
        for _, f in pf.iterrows():
            st.markdown(f"- **{f['severity']}** · `{f['category']}` · {f['description']}")
        if pf.empty:
            st.success("No differences on this page.")
        left, right = st.columns([2, 1])
        with left:
            st.markdown(f"**Web** · assistant: `{web_page['chat']['position']}`")
            st.image(str(chosen / web_page["screenshot"]), width="stretch")
        with right:
            st.markdown(f"**App** · assistant: `{app_page['chat']['position']}`")
            st.image(str(chosen / app_page["screenshot"]), width="stretch")

with tab_flows:
    for runs in data["flows"].values():
        web_run, app_run = runs["web"], runs["app"]
        st.subheader(f"{web_run['flow_name']} ({web_run['mode']})")
        rows = max(web_run["step_count"], app_run["step_count"])
        table = pd.DataFrame(
            {
                "web": [f"{s['page_name']}  ({s['action']})" for s in web_run["steps"]] + [""] * (rows - web_run["step_count"]),
                "app": [f"{s['page_name']}  ({s['action']})" for s in app_run["steps"]] + [""] * (rows - app_run["step_count"]),
            },
            index=range(1, rows + 1),
        )
        st.table(table)
        st.caption(
            f"web: {web_run['step_count']} steps ({'ok' if web_run['success'] else 'failed'}) · "
            f"app: {app_run['step_count']} steps ({'ok' if app_run['success'] else 'failed'})"
        )

with tab_backlog:
    backlog = chosen / "standardization_backlog.csv"
    st.dataframe(pd.read_csv(backlog), width="stretch", hide_index=True)
    st.download_button("Download backlog CSV", backlog.read_bytes(), file_name="standardization_backlog.csv", mime="text/csv")

with tab_eval:
    if data.get("evaluation"):
        st.dataframe(pd.DataFrame(data["evaluation"]["per_category"] + [data["evaluation"]["overall"]]),
                     width="stretch", hide_index=True)
        if data["evaluation"]["missed"]:
            st.write("Missed planted differences", data["evaluation"]["missed"])
        if data["evaluation"]["false_positives"]:
            st.write("Findings not in the ground truth", data["evaluation"]["false_positives"])
    else:
        st.info("Evaluation is available for runs against the bundled demo sites (ground truth: demo_sites/PLANTED_DIFFERENCES.yaml).")
