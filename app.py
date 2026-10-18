from pathlib import Path
from io import BytesIO
import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from pypdf import PdfReader

st.set_page_config(page_title="EK25068 ANFD Drying Dashboard", page_icon="📈", layout="wide")
BASE = Path(__file__).parent
SAMPLE = BASE / "data" / "EK25068_ADAM_drying_extracted.xlsx"
TAGS = ["TICR066","TICR067","TICR034","PICR008","PICR043","PICR032","LSICR007","CP011","CP012","CP007","PT01"]
TEMP_TAGS = ["TICR066","TICR067","TICR034"]
PRESSURE_TAGS = ["PICR008","PICR043","PICR032","PT01"]
ROW_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+((?:-?\d+(?:\.\d+)?\s+){10}-?\d+(?:\.\d+)?)\s+(.*\S)\s*$")

@st.cache_data(show_spinner=False)
def read_workbook(raw: bytes):
    xl = pd.ExcelFile(BytesIO(raw), engine="openpyxl")
    sheets = {s: pd.read_excel(xl, sheet_name=s) for s in xl.sheet_names}
    for key in ["Cycle Record", "Event Record", "Alarm Record"]:
        if key in sheets and "Date time" in sheets[key].columns:
            sheets[key]["Date time"] = pd.to_datetime(sheets[key]["Date time"], dayfirst=True, errors="coerce")
    return sheets

@st.cache_data(show_spinner=False)
def parse_pdf(raw: bytes):
    reader = PdfReader(BytesIO(raw))
    pages = []
    for p in reader.pages:
        try:
            text = p.extract_text(extraction_mode="layout") or ""
        except TypeError:
            text = p.extract_text() or ""
        pages.append(text)
    rows, events, alarms = [], [], []
    for page_no, txt in enumerate(pages, 1):
        for line in txt.splitlines():
            s = line.strip()
            m = ROW_RE.match(s)
            if m:
                nums = [float(x) for x in m.group(3).split()]
                row = [pd.to_datetime(m.group(1)+" "+m.group(2), dayfirst=True)] + nums + [m.group(4).strip(), page_no]
                (rows if 5 <= page_no <= 145 else events).append(row)
            elif page_no == 148:
                a = re.match(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+)$", s)
                if a:
                    alarms.append([pd.to_datetime(a.group(1)+" "+a.group(2), dayfirst=True), a.group(3), page_no])
    cycle_cols = ["Date time"] + TAGS + ["Step status","Source page"]
    event_cols = ["Date time","TICR066","TICR067","TICR034","PICR008","PICR036","PICR035","LSICR007","CP011","CP012","CP007","PT01","Event","Source page"]
    result = {"Cycle Record": pd.DataFrame(rows, columns=cycle_cols), "Event Record": pd.DataFrame(events, columns=event_cols), "Alarm Record": pd.DataFrame(alarms, columns=["Date time","Event","Source page"])}
    return result

def to_excel(sheets):
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as writer:
        for name, df in sheets.items():
            df.to_excel(writer, sheet_name=name[:31], index=False)
    return out.getvalue()

def filtered_cycle(df):
    d = df.copy().dropna(subset=["Date time"]).sort_values("Date time")
    lo, hi = d["Date time"].min().to_pydatetime(), d["Date time"].max().to_pydatetime()
    selected = st.sidebar.slider("Date/time window", min_value=lo, max_value=hi, value=(lo, hi), format="DD/MM/YY HH:mm")
    statuses = sorted(d["Step status"].dropna().astype(str).unique())
    chosen = st.sidebar.multiselect("Step status", statuses, default=statuses)
    return d[d["Date time"].between(pd.Timestamp(selected[0]), pd.Timestamp(selected[1])) & d["Step status"].astype(str).isin(chosen)]

st.title("EK25068 ANFD Drying Cycle Dashboard")
st.caption("Explore cycle trends, phase durations, events, alarms, recipe parameters and downloadable filtered data.")

st.sidebar.header("Data source")
upload = st.sidebar.file_uploader("Upload extracted XLSX or original PDF", type=["xlsx","pdf"])
if upload is None:
    sheets = read_workbook(SAMPLE.read_bytes())
    source_name = "Bundled EK25068 extracted workbook"
elif upload.name.lower().endswith(".pdf"):
    with st.spinner("Extracting text-layer records from PDF..."):
        sheets = parse_pdf(upload.getvalue())
    source_name = upload.name
else:
    sheets = read_workbook(upload.getvalue())
    source_name = upload.name

cycle = sheets.get("Cycle Record", pd.DataFrame())
events = sheets.get("Event Record", pd.DataFrame())
alarms = sheets.get("Alarm Record", pd.DataFrame())
if cycle.empty:
    st.error("No cycle records were found. Use the supplied extracted workbook or a text-searchable EK25068-format PDF.")
    st.stop()

f = filtered_cycle(cycle)
st.sidebar.caption(f"Source: {source_name}")

c1,c2,c3,c4 = st.columns(4)
c1.metric("Filtered records", f"{len(f):,}")
c2.metric("Cycle start", f["Date time"].min().strftime("%d %b %Y %H:%M") if len(f) else "-")
c3.metric("Cycle end", f["Date time"].max().strftime("%d %b %Y %H:%M") if len(f) else "-")
duration = (f["Date time"].max()-f["Date time"].min()).total_seconds()/3600 if len(f)>1 else 0
c4.metric("Selected duration", f"{duration:.2f} h")

tabs = st.tabs(["Overview","Trends","Phase analysis","Events & alarms","Recipe & metadata","Data explorer"])
with tabs[0]:
    a,b = st.columns([1.4,1])
    with a:
        long = f.melt(id_vars=["Date time"], value_vars=[x for x in TEMP_TAGS if x in f], var_name="Tag", value_name="Value")
        fig=px.line(long,x="Date time",y="Value",color="Tag",title="Temperature trends",labels={"Value":"Temperature (°C)"})
        st.plotly_chart(fig,use_container_width=True)
    with b:
        counts=f["Step status"].value_counts().rename_axis("Step status").reset_index(name="Records")
        fig=px.bar(counts.head(15),x="Records",y="Step status",orientation="h",title="Most frequent step statuses")
        fig.update_layout(yaxis={"categoryorder":"total ascending"})
        st.plotly_chart(fig,use_container_width=True)
    if "PT01" in f:
        fig=px.line(f,x="Date time",y="PT01",title="ANFD pressure/vacuum trend",labels={"PT01":"PT01 (bar)"})
        st.plotly_chart(fig,use_container_width=True)

with tabs[1]:
    available=[x for x in TAGS if x in f.columns]
    selected_tags=st.multiselect("Tags to plot",available,default=[x for x in ["TICR066","TICR067","TICR034","PT01"] if x in available])
    if selected_tags:
        long=f.melt(id_vars=["Date time"],value_vars=selected_tags,var_name="Tag",value_name="Value")
        separate=st.toggle("Separate vertical scales",value=True)
        if separate:
            fig=go.Figure()
            for i,tag in enumerate(selected_tags):
                axis="y" if i==0 else f"y{i+1}"
                fig.add_trace(go.Scatter(x=f["Date time"],y=f[tag],name=tag,yaxis=axis,mode="lines"))
                if i>0:
                    fig.update_layout(**{f"yaxis{i+1}":dict(overlaying="y",side="right",position=max(0.55,1-(i-1)*0.06),showgrid=False,title=tag)})
            fig.update_layout(title="Selected process trends",height=600,hovermode="x unified",xaxis_title="Date/time",yaxis_title=selected_tags[0])
        else:
            fig=px.line(long,x="Date time",y="Value",color="Tag",title="Selected process trends")
        st.plotly_chart(fig,use_container_width=True)

with tabs[2]:
    phase=f.groupby("Step status",dropna=False).agg(Start=("Date time","min"),End=("Date time","max"),Records=("Date time","size")).reset_index()
    phase["Observed span (h)"]=(phase["End"]-phase["Start"]).dt.total_seconds()/3600
    st.dataframe(phase.sort_values("Start"),use_container_width=True,hide_index=True)
    transitions=f.loc[f["Step status"].astype(str).ne(f["Step status"].astype(str).shift()),["Date time","Step status"]].copy()
    transitions["Duration to next transition (min)"]=(transitions["Date time"].shift(-1)-transitions["Date time"]).dt.total_seconds()/60
    st.subheader("Sequential phase transitions")
    st.dataframe(transitions,use_container_width=True,hide_index=True)

with tabs[3]:
    c1,c2=st.columns(2)
    with c1:
        st.subheader(f"Event record ({len(events):,})")
        st.dataframe(events,use_container_width=True,hide_index=True)
    with c2:
        st.subheader(f"Alarm record ({len(alarms):,})")
        st.dataframe(alarms,use_container_width=True,hide_index=True)

with tabs[4]:
    for name in ["Summary","Recipe Parameters","Production Parameters","Tag Units","Abbreviations","Trend Legends"]:
        if name in sheets:
            st.subheader(name)
            st.dataframe(sheets[name],use_container_width=True,hide_index=True)

with tabs[5]:
    selected_sheet=st.selectbox("Sheet",list(sheets.keys()))
    query=st.text_input("Search rows")
    view=sheets[selected_sheet].copy()
    if query:
        mask=view.astype(str).apply(lambda c:c.str.contains(query,case=False,na=False)).any(axis=1)
        view=view[mask]
    st.dataframe(view,use_container_width=True,hide_index=True)
    st.download_button("Download displayed data as CSV",view.to_csv(index=False).encode("utf-8-sig"),f"{selected_sheet.replace(' ','_')}.csv","text/csv")

st.divider()
d1,d2=st.columns(2)
d1.download_button("Download filtered cycle CSV",f.to_csv(index=False).encode("utf-8-sig"),"EK25068_filtered_cycle.csv","text/csv",use_container_width=True)
d2.download_button("Download all loaded sheets as Excel",to_excel(sheets),"EK25068_app_export.xlsx","application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",use_container_width=True)
