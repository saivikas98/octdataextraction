from io import BytesIO
from datetime import datetime, timedelta
import re
import pandas as pd
import plotly.express as px
import streamlit as st
from pypdf import PdfReader

st.set_page_config(page_title="ANFD Dual-Report Viewer", page_icon="📊", layout="wide")
ADAM_TAGS=["TICR066","TICR067","TICR034","PICR008","PICR043","PICR032","LSICR007","CP011","CP012","CP007","PT01"]
ADAM_ROW=re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+((?:-?\d+(?:\.\d+)?\s+){10}-?\d+(?:\.\d+)?)\s+(.*\S)\s*$")
PROCESS_ROW=re.compile(r"^\s*(\d+)\s+(\d{2}:\d{2}:\d{2})\s+" + r"\s+".join([r"(-?\d+(?:\.\d+)?)"]*8) + r"\s+(.+?)\s*$")

def pdf_text(raw):
    reader=PdfReader(BytesIO(raw)); pages=[]
    for page in reader.pages:
        try: t=page.extract_text(extraction_mode="layout") or ""
        except TypeError: t=page.extract_text() or ""
        pages.append(t)
    return pages

def detect_report(pages):
    head="\n".join(pages[:3]).upper()
    if "CYCLE RECORD" in head or "ANFD DRYING CYCLE" in head and "TICR067" in "\n".join(pages[:6]).upper(): return "ADAM drying-cycle report"
    if "ANFD-2 PROCESS SYSTEM" in head and "FILTER_POS" in "\n".join(pages[:6]).upper(): return "ANFD process-system report"
    return "Unknown"

def metadata(pages,kind):
    text="\n".join(pages[:3]); out={"Report type":kind,"Pages":len(pages)}
    patterns={"Batch number":r"(?:BATCH NUMBER|BATCH NO\.)\s*:?\s*(EK\d+)","Product":r"(?:PRODUCT NAME|BATCH NAME)\s*:?\s*([A-Z][A-Z ]+(?:SUSPENSION)?)","Equipment ID":r"EQUIPMENT ID\s*:?\s*(\d+)","User/Operator":r"(?:USER NAME|OPERATOR NAME)\s*:?\s*([A-Z0-9 ]+)"}
    for k,p in patterns.items():
        m=re.search(p,text,re.I); out[k]=m.group(1).strip() if m else "Not detected"
    return pd.DataFrame(out.items(),columns=["Field","Value"])

def parse_adam(pages):
    cycle=[]; events=[]; alarms=[]
    for pn,txt in enumerate(pages,1):
        for line in txt.splitlines():
            s=line.strip(); m=ADAM_ROW.match(s)
            if m:
                values=[float(x) for x in m.group(3).split()]
                row=[pd.to_datetime(m.group(1)+" "+m.group(2),dayfirst=True)]+values+[m.group(4).strip(),pn]
                if "EVENT RECORD" in txt.upper() or pn>=146: events.append(row)
                else: cycle.append(row)
            elif "ALARM RECORD" in txt.upper():
                a=re.match(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+)$",s)
                if a: alarms.append([pd.to_datetime(a.group(1)+" "+a.group(2),dayfirst=True),a.group(3),pn])
    cols=["Date time"]+ADAM_TAGS+["Stage","Source page"]
    event_cols=["Date time","TICR066","TICR067","TICR034","PICR008","PICR036","PICR035","LSICR007","CP011","CP012","CP007","PT01","Event","Source page"]
    return pd.DataFrame(cycle,columns=cols),pd.DataFrame(events,columns=event_cols),pd.DataFrame(alarms,columns=["Date time","Alarm","Source page"])

def parse_process(pages):
    head="\n".join(pages[:2]); m=re.search(r"START DATE\s*&?TIME.*?(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})",head,re.I|re.S)
    if not m: m=re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})",head)
    start=pd.to_datetime((m.group(1)+" "+m.group(2)) if m else "12/08/2025 00:00:00",dayfirst=True)
    rows=[]; day=start.normalize(); previous=None
    for pn,txt in enumerate(pages,1):
        for line in txt.splitlines():
            x=PROCESS_ROW.match(line)
            if not x: continue
            tm=datetime.strptime(x.group(2),"%H:%M:%S").time()
            if previous and tm < previous: day += timedelta(days=1)
            previous=tm; dt=pd.Timestamp.combine(day.date(),tm)
            rows.append([int(x.group(1)),dt]+[float(v) for v in x.groups()[2:10]]+[x.group(11).strip(),pn])
    cols=["Record","Date time","TT-01","TT-02","PT-01","PICR32","TICR066","Filter_Pos","Agit_Rpm","Agit_Pos","Stage","Source page"]
    alarms=[]
    for pn,txt in enumerate(pages,1):
        if "ALARM TABLE" not in txt.upper(): continue
        for line in txt.splitlines():
            a=re.match(r"^\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)\s*$",line)
            if a: alarms.append([pd.to_datetime(a.group(1)+" "+a.group(2),dayfirst=True),a.group(3),pn])
    return pd.DataFrame(rows,columns=cols),pd.DataFrame(),pd.DataFrame(alarms,columns=["Date time","Alarm","Source page"])

st.title("ANFD Drying Report Viewer")
st.caption("Supports both ADAM drying-cycle reports and ANFD process-system drying reports. All processing is in memory; no Excel/CSV is created or saved.")
upload=st.sidebar.file_uploader("Upload either report PDF",type=["pdf"])
if not upload:
    st.info("Upload either report type from the sidebar."); st.stop()
with st.spinner("Detecting report format and extracting records..."):
    pages=pdf_text(upload.getvalue()); kind=detect_report(pages)
    if kind=="ADAM drying-cycle report": data,events,alarms=parse_adam(pages)
    elif kind=="ANFD process-system report": data,events,alarms=parse_process(pages)
    else: st.error("Unsupported report layout. Expected either the ADAM drying-cycle or ANFD process-system format."); st.stop()
if data.empty: st.error("The report type was detected, but no process rows were extracted."); st.stop()
st.sidebar.success(kind)
d=data.dropna(subset=["Date time"]).sort_values("Date time")
lo,hi=d["Date time"].min().to_pydatetime(),d["Date time"].max().to_pydatetime()
window=st.sidebar.slider("Date/time range",lo,hi,(lo,hi),format="DD/MM/YY HH:mm")
stages=sorted(d["Stage"].dropna().astype(str).unique())
chosen=st.sidebar.multiselect("Stage",stages,default=stages)
f=d[d["Date time"].between(pd.Timestamp(window[0]),pd.Timestamp(window[1])) & d["Stage"].astype(str).isin(chosen)]

c1,c2,c3,c4=st.columns(4)
c1.metric("Report format",kind.replace(" report","")); c2.metric("Records",f"{len(f):,}")
c3.metric("Start",f["Date time"].min().strftime("%d %b %H:%M") if len(f) else "-")
c4.metric("End",f["Date time"].max().strftime("%d %b %H:%M") if len(f) else "-")

t1,t2,t3,t4,t5=st.tabs(["Overview","Trends","Stages","Events & alarms","All data"])
with t1:
    st.subheader("Detected report metadata"); st.dataframe(metadata(pages,kind),hide_index=True,use_container_width=True)
    numeric=[c for c in f.select_dtypes(include="number").columns if c not in ["Record","Source page"]]
    defaults=[x for x in (["TICR066","TICR067","TICR034","PT01"] if kind.startswith("ADAM") else ["TT-01","TT-02","TICR066","PT-01"]) if x in numeric]
    long=f.melt(id_vars="Date time",value_vars=defaults,var_name="Tag",value_name="Value")
    st.plotly_chart(px.line(long,x="Date time",y="Value",color="Tag",title="Primary process trends"),use_container_width=True)
with t2:
    numeric=[c for c in f.select_dtypes(include="number").columns if c not in ["Record","Source page"]]
    selected=st.multiselect("Select tags",numeric,default=[x for x in numeric[:4]])
    if selected:
        long=f.melt(id_vars="Date time",value_vars=selected,var_name="Tag",value_name="Value")
        st.plotly_chart(px.line(long,x="Date time",y="Value",color="Tag",title="Selected trends",hover_data={"Value":":.3f"}),use_container_width=True)
with t3:
    trans=f.loc[f["Stage"].astype(str).ne(f["Stage"].astype(str).shift()),["Date time","Stage"]].copy()
    trans["Duration to next transition (min)"]=(trans["Date time"].shift(-1)-trans["Date time"]).dt.total_seconds()/60
    st.dataframe(trans,hide_index=True,use_container_width=True)
    counts=f["Stage"].value_counts().rename_axis("Stage").reset_index(name="Records")
    st.plotly_chart(px.bar(counts.head(25),x="Records",y="Stage",orientation="h",title="Stage frequency"),use_container_width=True)
with t4:
    a,b=st.columns(2)
    with a: st.subheader(f"Events ({len(events):,})"); st.dataframe(events,hide_index=True,use_container_width=True)
    with b: st.subheader(f"Alarms ({len(alarms):,})"); st.dataframe(alarms,hide_index=True,use_container_width=True)
with t5:
    q=st.text_input("Search displayed rows")
    view=f
    if q: view=view[view.astype(str).apply(lambda c:c.str.contains(q,case=False,na=False)).any(axis=1)]
    st.dataframe(view,hide_index=True,use_container_width=True,height=650)
st.caption("Uploaded report data remains in session memory only. This app does not generate or store Excel/CSV files.")
