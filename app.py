from io import BytesIO
from datetime import datetime, timedelta
import re
import pandas as pd
import plotly.express as px
import streamlit as st
import pdfplumber

st.set_page_config(page_title="ADAM Process Report - Tagwise Extraction", page_icon="📊", layout="wide")
DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+)$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
TAG_RE = re.compile(r"^(?:LSICR|PICR|TICR|TA|TLP|RLS|CP|PT|TT|XV)[A-Z0-9-]*$", re.I)

@st.cache_data(show_spinner=False)
def extract_pdf_pages(raw: bytes):
    with pdfplumber.open(BytesIO(raw)) as pdf:
        return [page.extract_text(layout=True) or "" for page in pdf.pages]

def clean_text(value):
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(value or "")).strip()

def metadata_from_pages(pages):
    first="\n".join(pages[:3])
    def find(pattern, default="Not detected"):
        m=re.search(pattern, first, re.I)
        return clean_text(m.group(1)) if m else default
    return {
        "Equipment ID": find(r"EQUIPMENT ID\s*:?\s*([^\n]+)"),
        "Product name": find(r"PRODUCT NAME\s*:?\s*([^\n]+)"),
        "Product code": find(r"PRODUCT CODE\s*:?\s*([^\n]+)"),
        "Batch number": find(r"BATCH NUMBER\s*:?\s*([A-Z0-9-]+)"),
        "Operator name": find(r"OPERATOR NAME\s*:?\s*([^\n]+)"),
        "Cycle selected": find(r"CYCLE SELECTED\s*:?\s*([^\n]+)"),
        "Start date/time": find(r"START DATE TIME\s*:?\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})"),
        "End date/time": find(r"END DATE TIME\s*:?\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2})"),
        "PDF pages": len(pages),
    }

def header_tags(page_text):
    lines=page_text.splitlines()
    tags=[]; units={}; record_type=None
    for line in lines:
        u=line.upper()
        if "CYCLE RECORD" in u: record_type="Cycle"
        if "EVENT RECORD" in u: record_type="Event"
        if "DATE TIME" in u and ("STEP STATUS" in u or "EVENT STATUS" in u):
            right=re.split(r"DATE TIME", line, flags=re.I, maxsplit=1)[1]
            right=re.sub(r"(?:STEP|EVENT) STATUS.*$", "", right, flags=re.I)
            candidates=[x.strip() for x in re.split(r"\s{2,}", right) if x.strip()]
            tags=[x for x in candidates if TAG_RE.match(x)]
            break
    # Prefer the explicit Tag row, which is authoritative.
    for line in lines:
        if re.match(r"^\s*Tag\s+", line, re.I):
            candidates=[x.strip() for x in re.split(r"\s{2,}", line.strip())[1:] if x.strip()]
            explicit=[x for x in candidates if TAG_RE.match(x)]
            if explicit: tags=explicit
        if re.match(r"^\s*Unit\s+", line, re.I) and tags:
            vals=[x.strip() for x in re.split(r"\s{2,}", line.strip())[1:] if x.strip()]
            for tag,unit in zip(tags,vals): units[tag]=unit
    return tags,units,record_type

def parse_process_report(pages):
    wide_groups={}; long_rows=[]; events=[]; alarms=[]; current_tags=[]; current_units={}; current_type=None
    for page_no,text in enumerate(pages,1):
        tags,units,record_type=header_tags(text)
        if tags:
            current_tags=tags; current_units=units or current_units; current_type=record_type or current_type
        upper=text.upper()
        if "ALARM RECORD" in upper:
            for raw in text.splitlines():
                m=DATE_RE.match(raw.strip())
                if m:
                    alarms.append({"Date time":pd.to_datetime(m.group(1)+" "+m.group(2),dayfirst=True),"Alarm":clean_text(m.group(3)),"Source page":page_no})
            continue
        if not current_tags: continue
        group_name=" + ".join(current_tags)
        wide_groups.setdefault(group_name,[])
        for raw in text.splitlines():
            m=DATE_RE.match(raw.strip())
            if not m: continue
            tokens=m.group(3).split()
            if len(tokens)<len(current_tags): continue
            values=tokens[:len(current_tags)]
            if not all(NUMBER_RE.match(v) for v in values): continue
            status=clean_text(" ".join(tokens[len(current_tags):]))
            dt=pd.to_datetime(m.group(1)+" "+m.group(2),dayfirst=True)
            row={"Date time":dt,**{tag:float(v) for tag,v in zip(current_tags,values)},"Status":status,"Source page":page_no}
            if (current_type or "Cycle")=="Event":
                events.append(row)
            else:
                wide_groups[group_name].append(row)
                for tag,v in zip(current_tags,values):
                    long_rows.append({"Date time":dt,"Instrument tag":tag,"Value":float(v),"Unit":current_units.get(tag,""),"Step status":status,"Instrument group":group_name,"Source page":page_no})
    wide={name:pd.DataFrame(rows).drop_duplicates(subset=["Date time"],keep="first").sort_values("Date time") for name,rows in wide_groups.items() if rows}
    long_df=pd.DataFrame(long_rows)
    if not long_df.empty: long_df=long_df.drop_duplicates(subset=["Date time","Instrument tag"],keep="first").sort_values(["Instrument tag","Date time"])
    return wide,long_df,pd.DataFrame(events),pd.DataFrame(alarms)

def detect_report_type(pages):
    """Automatically classify supported PDF layouts using multiple independent markers."""
    probe="\n".join(pages[:6])
    normalized=re.sub(r"\s+", " ", probe).upper()

    adam_markers={
        "process_cycle": "PROCESS CYCLE" in normalized,
        "cycle_record": "CYCLE RECORD" in normalized,
        "dated_rows": bool(re.search(r"\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}:\d{2}", probe)),
        "adam_tags": bool(re.search(r"LSICR\d+|PICR00\d|TA00\d|TLP00\d|RLS00\d", normalized)),
        "octreotide_skid": "OCTREOTIDE SKID" in normalized,
    }
    omca_markers={
        "anfd2_system": "ANFD-2 PROCESS SYSTEM" in normalized,
        "drying": "DRYING" in normalized,
        "time_header": bool(re.search(r"TIME\s+TT-?01\s+TT-?02\s+PT-?01", normalized)),
        "motion_tags": all(x in normalized for x in ["FILTER_POS","AGIT_RPM","AGIT_POS"]),
        "progressive": "PROGRESSIVE" in normalized,
    }
    adam_score=sum(adam_markers.values())
    omca_score=sum(omca_markers.values())

    if adam_score >= 3 and adam_score > omca_score:
        return "ADAM Skid Process Report", adam_score, omca_score, adam_markers, omca_markers
    if omca_score >= 3 and omca_score > adam_score:
        return "OMCA ANFDA Drying Report", adam_score, omca_score, adam_markers, omca_markers
    return "Unknown", adam_score, omca_score, adam_markers, omca_markers

def parse_omca_anfd_report(pages):
    """Parse OMCA ANFDA/ANFD-2 reports with sequence + time-only rows."""
    text="\n".join(pages[:3])
    start_match=re.search(r"START DATE\s*&?TIME\s*:?\s*(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})",text,re.I)
    if not start_match:
        raise ValueError("Start date/time was not found in the OMCA ANFDA report.")
    start=datetime.strptime(start_match.group(1)+" "+start_match.group(2),"%d/%m/%Y %H:%M:%S")
    tags=["TT-01","TT-02","PT-01","PICR32","TICR066","Filter_Pos","Agit_Rpm","Agit_Pos"]
    units={"TT-01":"°C","TT-02":"°C","PT-01":"barg","PICR32":"barg","TICR066":"°C","Filter_Pos":"°","Agit_Rpm":"rpm","Agit_Pos":"mm"}
    row_re=re.compile(r"^\s*(\d+)\s+(\d{2}:\d{2}:\d{2})\s+"+r"\s+".join([r"(-?\d+(?:\.\d+)?)"]*8)+r"\s+(.+?)\s*$")
    rows=[]; long_rows=[]; current_date=start.date(); previous_dt=None
    for page_no,page in enumerate(pages,1):
        for line in page.splitlines():
            m=row_re.match(line)
            if not m: continue
            sequence=int(m.group(1)); tm=datetime.strptime(m.group(2),"%H:%M:%S").time()
            candidate=datetime.combine(current_date,tm)
            if previous_dt is not None and candidate < previous_dt-timedelta(hours=12):
                current_date += timedelta(days=1)
                candidate=datetime.combine(current_date,tm)
            previous_dt=candidate
            values=[float(x) for x in m.groups()[2:10]]
            stage=clean_text(m.group(11))
            row={"Record":sequence,"Date time":pd.Timestamp(candidate),**dict(zip(tags,values)),"Stage":stage,"Source page":page_no}
            rows.append(row)
            for tag,value in zip(tags,values):
                long_rows.append({"Date time":pd.Timestamp(candidate),"Instrument tag":tag,"Value":value,"Unit":units[tag],"Step status":stage,"Instrument group":"OMCA ANFDA Drying","Source page":page_no})
    wide_df=pd.DataFrame(rows).drop_duplicates(subset=["Record"],keep="first").sort_values("Record")
    long_df=pd.DataFrame(long_rows).drop_duplicates(subset=["Date time","Instrument tag"],keep="first").sort_values(["Instrument tag","Date time"])
    alarms=[]
    alarm_re=re.compile(r"^\s*\d+\s+(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)\s*$")
    for page_no,page in enumerate(pages,1):
        if "ALARM TABLE" not in page.upper(): continue
        for line in page.splitlines():
            m=alarm_re.match(line)
            if m:
                alarms.append({"Date time":pd.to_datetime(m.group(1)+" "+m.group(2),dayfirst=True),"Alarm":clean_text(m.group(3)),"Source page":page_no})
    groups={"OMCA ANFDA Drying":wide_df}
    return groups,long_df,pd.DataFrame(),pd.DataFrame(alarms)

def safe_table(df,height=650):
    view=df.copy().reset_index(drop=True)
    for c in view.columns:
        if pd.api.types.is_datetime64_any_dtype(view[c]): view[c]=view[c].dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")
        elif view[c].dtype=="object": view[c]=view[c].fillna("").astype(str)
    st.dataframe(view,use_container_width=True,hide_index=True,height=height,row_height=31)

st.title("Universal ADAM and OMCA ANFDA Report Extractor")
st.caption("Automatically detects ADAM Skid Process and OMCA ANFDA/ANFD-2 drying reports, then bifurcates data by instrument tag number.")
upload=st.sidebar.file_uploader("Upload report PDF",type=["pdf"])
if not upload:
    st.info("Upload a supported ADAM or OMCA ANFDA PDF. The report format will be detected automatically.")
    st.stop()
with st.spinner("Detecting report type and extracting instrument tags..."):
    pages=extract_pdf_pages(upload.getvalue())
    detected_type,adam_score,omca_score,adam_markers,omca_markers=detect_report_type(pages)
    meta=metadata_from_pages(pages)

if detected_type=="Unknown":
    st.error("The report type could not be identified reliably.")
    with st.expander("Detection details"):
        st.write({"ADAM score":adam_score,"OMCA score":omca_score,"ADAM markers":adam_markers,"OMCA markers":omca_markers})
    manual_type=st.selectbox("Select the report type manually",["ADAM Skid Process Report","OMCA ANFDA Drying Report"])
    if not st.button("Extract using selected type",type="primary"):
        st.stop()
    detected_type=manual_type

st.sidebar.success(f"Detected: {detected_type}")
with st.spinner(f"Extracting as {detected_type}..."):
    if detected_type=="ADAM Skid Process Report":
        groups,long_df,events,alarms=parse_process_report(pages)
    else:
        groups,long_df,events,alarms=parse_omca_anfd_report(pages)

if long_df.empty:
    st.error(f"{detected_type} was detected, but no tagwise rows were extracted. Check that the PDF has a searchable text layer.")
    st.stop()
meta["Detected report type"]=detected_type
meta["Detection score"]=f"ADAM {adam_score}/5 | OMCA {omca_score}/5"

tags=sorted(long_df["Instrument tag"].unique())
selected_tag=st.sidebar.selectbox("Instrument tag number",tags)
tag_df=long_df[long_df["Instrument tag"]==selected_tag].sort_values("Date time")
statuses=sorted(tag_df["Step status"].dropna().astype(str).unique())
chosen=st.sidebar.multiselect("Step status",statuses,default=statuses)
tag_df=tag_df[tag_df["Step status"].astype(str).isin(chosen)]

m1,m2,m3,m4=st.columns(4)
m1.metric("Instrument tags",len(tags)); m2.metric("Total tagwise readings",f"{len(long_df):,}")
m3.metric(f"{selected_tag} readings",f"{len(tag_df):,}"); m4.metric("Instrument groups",len(groups))

summary=long_df.groupby(["Instrument tag","Unit"],dropna=False).agg(Records=("Value","size"),Start=("Date time","min"),End=("Date time","max"),Minimum=("Value","min"),Maximum=("Value","max"),Mean=("Value","mean")).reset_index()

tabs=st.tabs(["Selected tag","Tag summary","Instrument groups","All tagwise data","Events & alarms","Metadata"])
with tabs[0]:
    st.subheader(f"Instrument tag: {selected_tag}")
    unit=tag_df["Unit"].dropna().astype(str).replace("",pd.NA).dropna().iloc[0] if tag_df["Unit"].astype(str).str.len().gt(0).any() else ""
    plot_df=tag_df.iloc[::max(1,len(tag_df)//3000)]
    fig=px.line(plot_df,x="Date time",y="Value",title=f"{selected_tag} trend",labels={"Value":f"Value ({unit})" if unit else "Value"})
    st.plotly_chart(fig,use_container_width=True)
    safe_table(tag_df[["Date time","Instrument tag","Value","Unit","Step status","Source page"]])
with tabs[1]:
    safe_table(summary,height=600)
with tabs[2]:
    group_name=st.selectbox("Instrument group",list(groups.keys()))
    st.caption("One combined table for the selected instrument group.")
    safe_table(groups[group_name])
with tabs[3]:
    search=st.text_input("Search tag, status, unit or timestamp")
    view=long_df
    if search: view=view[view.astype(str).apply(lambda x:x.str.contains(search,case=False,na=False)).any(axis=1)]
    safe_table(view)
with tabs[4]:
    a,b=st.columns(2)
    with a:
        st.subheader(f"Event records ({len(events):,})")
        safe_table(events,height=520) if not events.empty else st.info("No event records extracted.")
    with b:
        st.subheader(f"Alarm records ({len(alarms):,})")
        safe_table(alarms,height=520) if not alarms.empty else st.info("No alarm records extracted.")
with tabs[5]:
    safe_table(pd.DataFrame(meta.items(),columns=["Field","Value"]),height=430)

st.caption("The app does not save Excel/CSV files. It keeps parsed data only for the active Streamlit session.")
