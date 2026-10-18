import pandas as pd
import plotly.express as px
import streamlit as st
from parsers import parse_report

st.set_page_config(page_title="ANFD Drying Report Viewer",page_icon="📈",layout="wide")
st.title("ANFD Drying Report Viewer")
st.caption("Supports both EK25068 report layouts and displays extracted data in memory only.")
upload=st.sidebar.file_uploader("Upload either drying-report PDF",type=["pdf"])
if upload is None:
    st.info("Upload either report type: ADAM drying-cycle report or ANFD-2 Process System drying report.")
    st.stop()
try:
    with st.spinner("Detecting report type and extracting data..."):
        report_type,sheets,tags,page_count=parse_report(upload.getvalue())
except Exception as e:
    st.error(str(e)); st.stop()
cycle=sheets["Cycle Record"].dropna(subset=["Date time"]).sort_values("Date time")
if cycle.empty:
    st.error("The report was detected, but no cycle rows were extracted from its text layer."); st.stop()
st.sidebar.success(report_type)
st.sidebar.caption(f"{page_count} pages | {len(cycle):,} cycle rows")
lo,hi=cycle["Date time"].min().to_pydatetime(),cycle["Date time"].max().to_pydatetime()
window=st.sidebar.slider("Date/time window",min_value=lo,max_value=hi,value=(lo,hi),format="DD/MM/YY HH:mm")
stages=sorted(cycle["Stage"].dropna().astype(str).unique())
chosen=st.sidebar.multiselect("Stage/status",stages,default=stages)
f=cycle[cycle["Date time"].between(pd.Timestamp(window[0]),pd.Timestamp(window[1])) & cycle["Stage"].astype(str).isin(chosen)]

m1,m2,m3,m4=st.columns(4)
m1.metric("Report type",report_type.replace(" report","")); m2.metric("Rows",f"{len(f):,}")
m3.metric("Start",f["Date time"].min().strftime("%d %b %Y %H:%M") if len(f) else "-")
m4.metric("End",f["Date time"].max().strftime("%d %b %Y %H:%M") if len(f) else "-")

t1,t2,t3,t4,t5=st.tabs(["Overview","Custom trends","Stages","Events & alarms","All data"])
with t1:
    temp_tags=[x for x in ["TICR066","TICR067","TICR034","TT-01","TT-02"] if x in f.columns]
    pressure_tags=[x for x in ["PT01","PT-01","PICR008","PICR043","PICR032","PICR32"] if x in f.columns]
    if temp_tags:
        long=f.melt(id_vars="Date time",value_vars=temp_tags,var_name="Tag",value_name="Value")
        st.plotly_chart(px.line(long,x="Date time",y="Value",color="Tag",title="Temperature trends",labels={"Value":"Temperature (°C)"}),use_container_width=True)
    if pressure_tags:
        long=f.melt(id_vars="Date time",value_vars=pressure_tags,var_name="Tag",value_name="Value")
        st.plotly_chart(px.line(long,x="Date time",y="Value",color="Tag",title="Pressure and vacuum trends",labels={"Value":"Pressure (bar/barg)"}),use_container_width=True)
    motion=[x for x in ["Filter_Pos","Agit_Rpm","Agit_Pos","CP011","CP012","CP007"] if x in f.columns]
    if motion:
        long=f.melt(id_vars="Date time",value_vars=motion,var_name="Tag",value_name="Value")
        st.plotly_chart(px.line(long,x="Date time",y="Value",color="Tag",title="Agitator, filter and pump trends"),use_container_width=True)
with t2:
    selected=st.multiselect("Select tags",[x for x in tags if x in f.columns],default=[x for x in tags if x in f.columns][:4])
    if selected:
        long=f.melt(id_vars="Date time",value_vars=selected,var_name="Tag",value_name="Value")
        st.plotly_chart(px.line(long,x="Date time",y="Value",color="Tag",title="Selected trends"),use_container_width=True)
with t3:
    transitions=f.loc[f["Stage"].astype(str).ne(f["Stage"].astype(str).shift()),["Date time","Stage"]].copy()
    transitions["Duration to next transition (min)"]=(transitions["Date time"].shift(-1)-transitions["Date time"]).dt.total_seconds()/60
    st.dataframe(transitions,use_container_width=True,hide_index=True)
    counts=f["Stage"].value_counts().rename_axis("Stage").reset_index(name="Records")
    st.plotly_chart(px.bar(counts.head(20),x="Records",y="Stage",orientation="h",title="Stage/status frequency"),use_container_width=True)
with t4:
    for name in ["Event Record","Alarm Record"]:
        if name in sheets:
            st.subheader(f"{name} ({len(sheets[name]):,})")
            st.dataframe(sheets[name],use_container_width=True,hide_index=True)
with t5:
    name=st.selectbox("Dataset",list(sheets.keys()))
    q=st.text_input("Search displayed rows")
    view=sheets[name].copy()
    if q: view=view[view.astype(str).apply(lambda c:c.str.contains(q,case=False,na=False)).any(axis=1)]
    st.dataframe(view,use_container_width=True,hide_index=True)
st.caption("Data is processed in memory only. This app does not create, save, bundle, or export Excel/CSV files.")
