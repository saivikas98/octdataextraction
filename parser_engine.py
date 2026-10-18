from io import BytesIO
from datetime import datetime, timedelta
import re
import pandas as pd
from pypdf import PdfReader
try:
    import pdfplumber
except ModuleNotFoundError:
    pdfplumber = None

TYPE1_TAGS=["TICR066","TICR067","TICR034","PICR008","PICR043","PICR032","LSICR007","CP011","CP012","CP007","PT01"]
TYPE2_TAGS=["TT-01","TT-02","PT-01","PICR32","TICR066","Filter_Pos","Agit_Rpm","Agit_Pos"]
D1=re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+((?:-?\d+(?:\.\d+)?\s+){10}-?\d+(?:\.\d+)?)\s+(.*\S)$")
D2=re.compile(r"^(\d+)\s+(\d{2}:\d{2}:\d{2})\s+((?:-?\d+(?:\.\d+)?\s+){7}-?\d+(?:\.\d+)?)\s+(.*\S)$")

def pages_from_pdf(raw):
    reader=PdfReader(BytesIO(raw))
    probe="\n".join((p.extract_text() or "") for p in reader.pages[:5]).upper()
    use_layout = "ANFD DRYING CYCLE" in probe and "CYCLE RECORD" in probe
    kind = "ANFD Drying Cycle report" if use_layout else ("ADAM Process System report" if "ANFD-2 PROCESS SYSTEM" in probe and "FILTER_POS" in probe else "Unknown report")
    if use_layout:
        if pdfplumber is None:
            raise RuntimeError("The pdfplumber package is not installed. Ensure requirements.txt is in the same GitHub folder as app.py, then reboot the Streamlit app.")
        with pdfplumber.open(BytesIO(raw)) as pdf:
            pages=[p.extract_text(layout=True) or "" for p in pdf.pages]
    else:
        pages=[p.extract_text() or "" for p in reader.pages]
    return pages, kind

def detect_type(text):
    u=text.upper()
    if "ANFD-2 PROCESS SYSTEM" in u and "FILTER_POS" in u: return "ADAM Process System report"
    if "ANFD DRYING CYCLE" in u and "CYCLE RECORD" in u: return "ANFD Drying Cycle report"
    return "Unknown report"

def field(text,label,pattern=r"([^\n]+)"):
    m=re.search(re.escape(label)+r"\s*:?\s*"+pattern,text,re.I)
    return m.group(1).strip() if m else None

def parse_type1(pages):
    rows=[]; events=[]; alarms=[]
    for pn,t in enumerate(pages,1):
        for line in t.splitlines():
            s=line.strip()
            s=re.sub(r"(?<=\d)\.\s+(?=\d)", ".", s)
            m=D1.match(s)
            if m:
                nums=[float(x) for x in m.group(3).split()]
                rec=[pd.to_datetime(m.group(1)+" "+m.group(2),dayfirst=True)]+nums+[m.group(4).strip(),pn]
                if "EVENT RECORD" in t or pn>=146: events.append(rec)
                else: rows.append(rec)
            elif "ALARM RECORD" in t:
                a=re.match(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+)$",s)
                if a: alarms.append([pd.to_datetime(a.group(1)+" "+a.group(2),dayfirst=True),a.group(3),pn])
    cols=["Date time"]+TYPE1_TAGS+["Stage","Source page"]
    ecols=["Date time","TICR066","TICR067","TICR034","PICR008","PICR036","PICR035","LSICR007","CP011","CP012","CP007","PT01","Event","Source page"]
    full="\n".join(pages[:4])
    meta={"Report type":"ANFD Drying Cycle report","Batch number":field(full,"BATCH NUMBER",r"([A-Z0-9-]+)"),"Product":field(full,"PRODUCT NAME",r"([^\n]+)"),"Equipment ID":field(full,"EQUIPMENT ID",r"([A-Z0-9-]+)"),"Pages":len(pages)}
    return {"Process Data":pd.DataFrame(rows,columns=cols),"Events":pd.DataFrame(events,columns=ecols),"Alarms":pd.DataFrame(alarms,columns=["Date time","Alarm","Source page"]),"Metadata":pd.DataFrame(meta.items(),columns=["Field","Value"]),"report_type":meta["Report type"],"tags":TYPE1_TAGS}

def parse_type2(pages):
    head="\n".join(pages[:2]); alltext="\n".join(pages)
    candidates=[datetime.strptime(d+" "+t,"%d/%m/%Y %H:%M:%S") for d,t in re.findall(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})",head)]
    start=min(candidates) if candidates else datetime(2000,1,1)
    current_date=start.date(); previous=None; rows=[]
    for pn,t in enumerate(pages,1):
        if "Time" not in t or "STAGE" not in t: continue
        for line in t.splitlines():
            m=D2.match(line.strip())
            if not m: continue
            tm=datetime.strptime(m.group(2),"%H:%M:%S").time()
            if previous and (datetime.combine(current_date,tm)-previous).total_seconds() < -12*3600: current_date+=timedelta(days=1)
            dt=datetime.combine(current_date,tm); previous=dt
            nums=[float(x) for x in m.group(3).split()]
            rows.append([int(m.group(1)),dt]+nums+[m.group(4).strip(),pn])
    alarms=[]
    for pn,t in enumerate(pages,1):
        if "ALARM TABLE" not in t: continue
        for line in t.splitlines():
            m=re.match(r"^\s*(\d+)\s+(\d{2}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.+?)\s*$",line)
            if m: alarms.append([int(m.group(1)),pd.to_datetime(m.group(2)+" "+m.group(3),dayfirst=True),m.group(4),pn])
    cols=["Record","Date time"]+TYPE2_TAGS+["Stage","Source page"]
    meta={"Report type":"ADAM Process System report","Batch number":field(head,"BATCH NO.",r"([A-Z0-9-]+)"),"Batch name":field(head,"BATCH NAME",r"([^\n]+)"),"User name":field(head,"USER NAME",r"([A-Z0-9-]+)"),"Test result":field(head,"TEST RESULT",r"([^\n]+)"),"Pages":len(pages)}
    return {"Process Data":pd.DataFrame(rows,columns=cols),"Events":pd.DataFrame(columns=["Date time","Event"]),"Alarms":pd.DataFrame(alarms,columns=["Record","Date time","Alarm","Source page"]),"Metadata":pd.DataFrame(meta.items(),columns=["Field","Value"]),"report_type":meta["Report type"],"tags":TYPE2_TAGS}

def parse_pdf(raw, report_choice="Auto-detect"):
    pages, detected=pages_from_pdf(raw)
    choice_map={
        "ADAM drying-cycle report":"ANFD Drying Cycle report",
        "OMCA ANFDA process-system report":"ADAM Process System report",
    }
    kind=choice_map.get(report_choice, detected)
    if kind=="ANFD Drying Cycle report":
        # The ADAM drying-cycle layout requires positional text extraction.
        if detected != "ANFD Drying Cycle report":
            with pdfplumber.open(BytesIO(raw)) as pdf:
                pages=[p.extract_text(layout=True) or "" for p in pdf.pages]
        result=parse_type1(pages)
    elif kind=="ADAM Process System report":
        # The OMCA ANFDA layout is most reliable with standard PDF text extraction.
        reader=PdfReader(BytesIO(raw))
        pages=[p.extract_text() or "" for p in reader.pages]
        result=parse_type2(pages)
    else:
        raise ValueError("Auto-detection was inconclusive. Select ADAM drying-cycle or OMCA ANFDA process-system manually.")
    if result["Process Data"].empty:
        raise ValueError(f"No process rows were extracted using '{report_choice}'. Select the other report type and retry.")
    result["selected_format"]=report_choice
    result["detected_format"]=detected
    return result

