import pandas as pd
import plotly.express as px
import streamlit as st
from parser_engine import parse_pdf

st.set_page_config(page_title="ANFD Dual Report Viewer",page_icon="📊",layout="wide")

def display_table(df, key, height=520, page_size=500):
    """Render large tables safely and show dates as DD/MM/YYYY HH:MM:SS."""
    view = df.copy().reset_index(drop=True)
    total = len(view)
    if total == 0:
        st.info("No records available for the selected filters.")
        return
    pages = max(1, (total + page_size - 1) // page_size)
    page = st.number_input(
        "Table page",
        min_value=1,
        max_value=pages,
        value=1,
        step=1,
        key=f"page_{key}",
    ) if pages > 1 else 1
    start = (int(page) - 1) * page_size
    page_df = view.iloc[start:start + page_size].copy()
    for col in page_df.columns:
        if pd.api.types.is_datetime64_any_dtype(page_df[col]):
            page_df[col] = page_df[col].dt.strftime("%d/%m/%Y %H:%M:%S")
        elif page_df[col].dtype == "object":
            page_df[col] = page_df[col].fillna("").astype(str)
    st.caption(f"Showing rows {start + 1:,} to {start + len(page_df):,} of {total:,}")
    st.dataframe(page_df, use_container_width=True, hide_index=True, height=height)

st.title("ANFD Drying Report Viewer")
st.caption("Supports both the ANFD Drying Cycle report and the ADAM Process System drying report. Data is displayed in memory only.")
files=st.sidebar.file_uploader("Upload one or both PDF reports",type=["pdf"],accept_multiple_files=True)
if not files:
    st.info("Upload either report type, or upload both reports together for side-by-side selection. No Excel or CSV file is created.")
    st.stop()

@st.cache_data(show_spinner=False)
def load(name,raw,report_choice):
    return parse_pdf(raw, report_choice)

reports={}
st.sidebar.subheader("Select report type")
for i,uploaded in enumerate(files):
    choice=st.sidebar.selectbox(
        f"Format for {uploaded.name}",
        ["Auto-detect","ADAM drying-cycle report","OMCA ANFDA process-system report"],
        key=f"format_{i}_{uploaded.name}",
        help="If auto-detect gives an unsupported-layout error, choose the report source manually."
    )
    try:
        with st.spinner(f"Reading {uploaded.name} as {choice}..."):
            reports[uploaded.name]=load(uploaded.name,uploaded.getvalue(),choice)
    except Exception as e:
        st.error(f"{uploaded.name}: {e}")
if not reports:
    st.warning("No report could be loaded. Select the correct report type beside each uploaded file.")
    st.stop()

name=st.sidebar.selectbox("Active report",list(reports))
r=reports[name]; data=r["Process Data"].copy(); tags=[x for x in r["tags"] if x in data]
st.sidebar.success(f"Loaded as: {r["report_type"]}")

lo=data["Date time"].min().to_pydatetime(); hi=data["Date time"].max().to_pydatetime()
window=st.sidebar.slider("Date/time window",lo,hi,(lo,hi),format="DD/MM/YY HH:mm")
stages=sorted(data["Stage"].dropna().astype(str).unique())
chosen=st.sidebar.multiselect("Stage",stages,default=stages)
f=data[data["Date time"].between(pd.Timestamp(window[0]),pd.Timestamp(window[1])) & data["Stage"].astype(str).isin(chosen)]

st.subheader(name)
a,b,c,d=st.columns(4)
a.metric("Report type",r["report_type"]); b.metric("Rows",f"{len(f):,}")
c.metric("Start",f["Date time"].min().strftime("%d %b %Y %H:%M") if len(f) else "-")
d.metric("End",f["Date time"].max().strftime("%d %b %Y %H:%M") if len(f) else "-")

tabs=st.tabs(["Overview","Trends","Stages","Events & alarms","All data","Metadata"])
with tabs[0]:
    default=[x for x in ["TICR066","TT-01","TT-02","TICR067","TICR034","PT01","PT-01"] if x in tags]
    long=f.melt(id_vars="Date time",value_vars=default,var_name="Tag",value_name="Value") if default else pd.DataFrame()
    if not long.empty: st.plotly_chart(px.line(long,x="Date time",y="Value",color="Tag",title="Key process trends"),use_container_width=True)
    counts=f["Stage"].value_counts().rename_axis("Stage").reset_index(name="Records")
    st.plotly_chart(px.bar(counts.head(20),x="Records",y="Stage",orientation="h",title="Records by stage"),use_container_width=True)
with tabs[1]:
    selected=st.multiselect("Select process tags",tags,default=default)
    if selected:
        long=f.melt(id_vars="Date time",value_vars=selected,var_name="Tag",value_name="Value")
        st.plotly_chart(px.line(long,x="Date time",y="Value",color="Tag",title="Interactive process trends"),use_container_width=True)
with tabs[2]:
    trans=f.loc[f["Stage"].astype(str).ne(f["Stage"].astype(str).shift()),["Date time","Stage"]].copy()
    trans["Duration to next transition (min)"]=(trans["Date time"].shift(-1)-trans["Date time"]).dt.total_seconds()/60
    display_table(trans, "transitions", height=520, page_size=300)
with tabs[3]:
    col1,col2=st.columns(2)
    with col1: st.subheader("Events"); display_table(r["Events"], "events", height=520, page_size=300)
    with col2: st.subheader("Alarms"); display_table(r["Alarms"], "alarms", height=520, page_size=300)
with tabs[4]:
    search=st.text_input("Search displayed process rows")
    view=f
    if search: view=view[view.astype(str).apply(lambda x:x.str.contains(search,case=False,na=False)).any(axis=1)]
    display_table(view, "all_data", height=650, page_size=500)
with tabs[5]: display_table(r["Metadata"], "metadata", height=420, page_size=100)

if len(reports)>1:
    st.divider(); st.subheader("Uploaded report comparison")
    comparison=[]
    for n,x in reports.items():
        q=x["Process Data"]
        comparison.append({"File":n,"Report type":x["report_type"],"Rows":len(q),"Start":q["Date time"].min(),"End":q["Date time"].max(),"Alarms":len(x["Alarms"]),"Events":len(x["Events"])})
    display_table(pd.DataFrame(comparison), "comparison", height=300, page_size=100)
st.caption("Privacy mode: PDFs are parsed in memory for the active Streamlit session. The app does not create or save Excel/CSV files.")
