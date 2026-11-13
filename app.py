from io import BytesIO
from datetime import datetime, timedelta
import os
os.environ.setdefault("OMP_THREAD_LIMIT","1")
os.environ.setdefault("OMP_NUM_THREADS","1")
os.environ.setdefault("OPENBLAS_NUM_THREADS","1")
os.environ.setdefault("MKL_NUM_THREADS","1")
os.environ.setdefault("NUMEXPR_NUM_THREADS","1")
import subprocess
import tempfile
import time
import gc
import re
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import pdfplumber
import shutil
from pathlib import Path


def clear_application_cache():
    \"\"\"Clear parsed-report caches and temporary selection state.\"\"\"
    st.cache_data.clear()
    st.cache_resource.clear()
    for key in list(st.session_state.keys()):
        if key=="processed_reports" or key.startswith(("report_type_", "combined_", "flow_", "page_")):
            del st.session_state[key]
    st.session_state["cache_cleared_notice"] = True

st.set_page_config(page_title="ADAM Process Report - Tagwise Extraction", page_icon="📊", layout="wide")

st.sidebar.header("Application controls")
if st.sidebar.button("Clear application cache", type="primary", width="stretch", help="Clears parsed-report data, Streamlit resources, and temporary report selections, then reloads the app."):
    clear_application_cache()
    st.rerun()
if st.session_state.pop("cache_cleared_notice", False):
    st.sidebar.success("Application cache cleared. Please upload the PDF again.")
st.sidebar.caption("Use after updating app.py, changing report type, or seeing an old cached parsing error.")

st.sidebar.subheader("Graph font controls")
plot_title_font=st.sidebar.slider("Graph title font size",12,40,23,1,key="graph_title_font_v11")
plot_axis_title_font=st.sidebar.slider("Axis-title font size",10,32,16,1,key="axis_title_font_v11")
plot_tick_font=st.sidebar.slider("Axis tick-label font size",8,26,12,1,key="tick_font_v11")
plot_legend_font=st.sidebar.slider("Legend font size",8,26,11,1,key="legend_font_v11")
plot_hover_font=st.sidebar.slider("Hover-label font size",8,26,12,1,key="hover_font_v11")

DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+)$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
TAG_RE = re.compile(r"^(?:(?:LSICR|PICR|TICR|TA|TLP|RLS|CP|PT|TT|XV|DP|QI?CR|CI?CR|MFM)[A-Z0-9_-]*|CV[45](?:WICR|TT|PT|AG)-01)$", re.I)
TAG_TOKEN_RE = re.compile(r"(?:CV[45](?:WICR|TT|PT|AG)-01|(?:LSICR|PICR|TICR|TA|TLP|RLS|CP|PT|TT|XV|DP|QICR|CICR|MFM)[A-Z0-9_-]*)", re.I)


# HMI tag naming derived from the supplied Octreotide Skid HMI screens.
# Raw report tags are retained for traceability; HMI labels are added for readability.
HMI_TAG_MAP = {
    # MV-01 Polymer Mixing Tank
    "LSICR001": ("MV-01 Polymer Mixing Tank", "Vessel weight / load-cell indication", "kg"),
    "PICR002": ("MV-01 Polymer Mixing Tank", "Vessel pressure", "bar"),
    "TICR004": ("MV-01 Polymer Mixing Tank", "Vessel temperature", "°C"),
    "TA001": ("MV-01 Polymer Mixing Tank", "Agitator speed", "RPM"),
    "PICR15": ("MV-01 area", "Pressure indication PICR15", "bar"),
    "PICR16": ("MV-01 area", "Pressure indication PICR16", "bar"),
    "PICR011": ("MV-01 area", "Pressure indication PICR011", "bar"),
    "TICR010": ("MV-01 utility line", "Temperature indication TICR010", "°C"),
    "TICR011": ("MV-01 utility line", "Temperature indication TICR011", "°C"),
    "TICR012": ("MV-01 utility line", "Temperature indication TICR012", "°C"),
    "TICR013": ("MV-01 utility line", "Temperature indication TICR013", "°C"),
    "TICR014": ("MV-01 utility line", "Temperature indication TICR014", "°C"),
    "TICR021": ("MV-01 utility line", "Temperature indication TICR021", "°C"),

    # MV-02 Dimethicone Collection Tank
    "LSICR002": ("MV-02 Dimethicone Collection Tank", "Vessel weight / load-cell indication", "kg"),
    "PICR003": ("MV-02 Dimethicone Collection Tank", "Vessel pressure", "bar"),
    "TICR005": ("MV-02 Dimethicone Collection Tank", "Vessel temperature", "°C"),
    "TA002": ("MV-02 Dimethicone Collection Tank", "Agitator speed", "RPM"),
    "PICR17": ("MV-02 area", "Pressure indication PICR17", "bar"),
    "PICR18": ("MV-02 area", "Pressure indication PICR18", "bar"),
    "PICR19": ("MV-02 area", "Pressure indication PICR19", "bar"),
    "TICR015": ("MV-02 utility line", "Temperature indication TICR015", "°C"),
    "TICR016": ("MV-02 utility line", "Temperature indication TICR016", "°C"),
    "TICR071": ("MV-02 utility line", "Temperature indication TICR071", "°C"),
    "TICR074": ("MV-02 utility line", "Temperature indication TICR074", "°C"),

    # SFV-01 Sterile Filtration Vessel
    "LSICR003": ("SFV-01 Sterile Filtration Vessel", "Vessel weight / load-cell indication", "kg"),
    "PICR004": ("SFV-01 Sterile Filtration Vessel", "Vessel pressure", "bar"),
    "TICR006": ("SFV-01 Sterile Filtration Vessel", "Vessel temperature", "°C"),
    "TA003": ("SFV-01 Sterile Filtration Vessel", "Agitator speed", "RPM"),
    "TLP001": ("SFV-01 transfer line", "Transfer-line pump 1 speed", "RPM"),
    "TLP002": ("SFV-01 transfer line", "Transfer-line pump 2 speed", "RPM"),
    "TLP01": ("SFV-01 transfer line", "Transfer-line pump 1 speed", "RPM"),
    "TLP02": ("SFV-01 transfer line", "Transfer-line pump 2 speed", "RPM"),
    "PICR12": ("SFV-01 area", "Pressure indication PICR12", "bar"),
    "PICR012": ("SFV-01 area", "Pressure indication PICR012", "bar"),
    "TICR017": ("SFV-01 utility line", "Temperature indication TICR017", "°C"),
    "TICR018": ("SFV-01 utility line", "Temperature indication TICR018", "°C"),
    "TICR019": ("SFV-01 utility line", "Temperature indication TICR019", "°C"),
    "TICR020": ("SFV-01 utility line", "Temperature indication TICR020", "°C"),

    # MV-04 Coacervation Vessel 100 L
    "LSICR004": ("MV-04 Coacervation Vessel 100 L", "Vessel weight / load-cell indication", "kg"),
    "PICR005": ("MV-04 Coacervation Vessel 100 L", "Vessel pressure", "bar"),
    "TICR007": ("MV-04 Coacervation Vessel 100 L", "Vessel temperature", "°C"),
    "TA004": ("MV-04 Coacervation Vessel 100 L", "Agitator speed", "RPM"),
    "PICR20": ("MV-04 area", "Pressure indication PICR20", "bar"),
    "PICR21": ("MV-04 area", "Pressure indication PICR21", "bar"),
    "PICR22": ("MV-04 area", "Pressure indication PICR22", "bar"),
    "PICR23": ("MV-04 area", "Pressure indication PICR23", "bar"),
    "PICR24": ("MV-04 / MV-05 transfer area", "Pressure indication PICR24", "bar"),
    "XV242": ("MV-04 CIP line", "Control valve position XV242", "%"),
    "TICR022": ("MV-04 utility line", "Temperature indication TICR022", "°C"),
    "TICR023": ("MV-04 utility line", "Temperature indication TICR023", "°C"),
    "TICR024": ("MV-04 utility line", "Temperature indication TICR024", "°C"),
    "TICR025": ("MV-04 utility line", "Temperature indication TICR025", "°C"),
    "TICR026": ("MV-04 utility line", "Temperature indication TICR026", "°C"),
    "TICR027": ("MV-04 / MV-05 utility line", "Temperature indication TICR027", "°C"),

    # MV-05 Hardening Vessel 1000 L
    "LSICR005": ("MV-05 Hardening Vessel 1000 L", "Vessel weight / load-cell indication", "kg"),
    "PICR006": ("MV-05 Hardening Vessel 1000 L", "Vessel pressure", "bar"),
    "TICR008": ("MV-05 Hardening Vessel 1000 L", "Vessel temperature", "°C"),
    "TA005": ("MV-05 Hardening Vessel 1000 L", "Agitator speed", "RPM"),
    "TICR028": ("MV-05 utility line", "Temperature indication TICR028", "°C"),
    "TICR029": ("MV-05 utility line", "Temperature indication TICR029", "°C"),
    "TICR048": ("ANFD-02 transfer utility line", "Temperature indication TICR048", "°C"),
    "TICR054": ("ANFD-02 transfer utility line", "Temperature indication TICR054", "°C"),

    # BV-01 Bed Wash Vessel-01 Ethanol 100 L
    "LSICR006": ("BV-01 Bed Wash Vessel-01 Ethanol 100 L", "Vessel weight / load-cell indication", "kg"),
    "PICR007": ("BV-01 Bed Wash Vessel-01 Ethanol 100 L", "Vessel pressure", "bar"),
    "TICR009": ("BV-01 Bed Wash Vessel-01 Ethanol 100 L", "Vessel temperature", "°C"),
    "CP005": ("BV-01 Bed Wash Vessel-01 Ethanol 100 L", "Centrifugal pump speed", "RPM"),
    "DP001": ("BV-01 Bed Wash Vessel-01 Ethanol 100 L", "Pump/control output DP001", "%"),
    "PICR25": ("BV-01 feed line", "Pressure indication PICR25", "bar"),
    "PICR26": ("BV-01 feed line", "Pressure indication PICR26", "bar"),
    "PICR27": ("BV-01 feed line", "Pressure indication PICR27", "bar"),
    "XV306": ("BV-01 collection/transfer line", "Control valve position XV306", "%"),
    "TICR030": ("BV-01 utility line", "Temperature indication TICR030", "°C"),
    "TICR031": ("BV-01 utility line", "Temperature indication TICR031", "°C"),
    "TICR032": ("BV-01 utility line", "Temperature indication TICR032", "°C"),
    "TICR033": ("BV-01 utility line", "Temperature indication TICR033", "°C"),
    "TICR067": ("BV-01 wash-solvent collection line", "Temperature indication TICR067", "°C"),
    "TICR070": ("BV-01 feed utility line", "Temperature indication TICR070", "°C"),

    # BV-02 Bed Wash Vessel-02 Heptane 100 L
    "LSICR007": ("BV-02 Bed Wash Vessel-02 Heptane 100 L", "Vessel weight / load-cell indication", "kg"),
    "PICR008": ("BV-02 Bed Wash Vessel-02 Heptane 100 L", "Vessel pressure", "bar"),
    "TICR034": ("BV-02 Bed Wash Vessel-02 Heptane 100 L", "Vessel temperature", "°C"),
    "CP007": ("BV-02 Bed Wash Vessel-02 Heptane 100 L", "Centrifugal pump speed", "RPM"),
    "PICR28": ("BV-02 feed / transfer line", "Pressure indication PICR28", "bar"),
    "PICR29": ("BV-02 feed / transfer line", "Pressure indication PICR29", "bar"),
    "PICR30": ("BV-02 feed / transfer line", "Pressure indication PICR30", "bar"),
    "PICR31": ("BV-02 feed / transfer line", "Pressure indication PICR31", "bar"),
    "TICR037": ("BV-02 utility line", "Temperature indication TICR037", "°C"),
    "TICR038": ("BV-02 utility line", "Temperature indication TICR038", "°C"),
    "TICR039": ("BV-02 utility line", "Temperature indication TICR039", "°C"),
    "TICR040": ("BV-02 utility line", "Temperature indication TICR040", "°C"),
    "TICR041": ("BV-02 utility line", "Temperature indication TICR041", "°C"),
    "TICR042": ("BV-02 utility line", "Temperature indication TICR042", "°C"),

    # MLT-01 Mother Liquor Tank-01 100 L
    "RLS001": ("MLT-01 Mother Liquor Tank-01 100 L", "Vessel level / volume indication", "L"),
    "PICR009": ("MLT-01 Mother Liquor Tank-01 100 L", "Vessel pressure", "bar"),
    "TICR035": ("MLT-01 Mother Liquor Tank-01 100 L", "Vessel temperature", "°C"),
    "PICR37": ("MLT-01 area", "Pressure indication PICR37", "bar"),
    "PICR38": ("MLT-01 area", "Pressure indication PICR38", "bar"),
    "PICR39": ("MLT-01 area", "Pressure indication PICR39", "bar"),
    "TICR055": ("MLT-01 utility line", "Temperature indication TICR055", "°C"),
    "TICR056": ("MLT-01 utility line", "Temperature indication TICR056", "°C"),
    "TICR057": ("MLT-01 utility line", "Temperature indication TICR057", "°C"),
    "TICR068": ("MLT-01 heat-exchanger utility line", "Temperature indication TICR068", "°C"),
    "DP002": ("MLT-01 utility / condensate line", "DP002 indication", ""),

    # MLT-02 Mother Liquor Tank-02 100 L
    "RLS002": ("MLT-02 Mother Liquor Tank-02 100 L", "Vessel level / volume indication", "L"),
    "PICR010": ("MLT-02 Mother Liquor Tank-02 100 L", "Vessel pressure", "bar"),
    "TICR036": ("MLT-02 Mother Liquor Tank-02 100 L", "Vessel temperature", "°C"),
    "PICR40": ("MLT-02 area", "Pressure indication PICR40", "bar"),
    "PICR41": ("MLT-02 area", "Pressure indication PICR41", "bar"),
    "PICR42": ("MLT-02 area", "Pressure indication PICR42", "bar"),
    "TICR058": ("MLT-02 utility line", "Temperature indication TICR058", "°C"),
    "TICR061": ("MLT-02 utility line", "Temperature indication TICR061", "°C"),
    "TICR062": ("MLT-02 utility line", "Temperature indication TICR062", "°C"),
    "TICR065": ("MLT-02 heat-exchanger utility line", "Temperature indication TICR065", "°C"),

    # Shared mother-liquor transfer system
    "CP006": ("MLT-01 / MLT-02 Mother Liquor Transfer System", "Centrifugal pump speed", "RPM"),

    # Heptane Tank 10,000 L and recirculation / transfer pumps
    "PICR001": ("Heptane Tank 10,000 L", "Tank pressure", "bar"),
    "RLS005": ("Heptane Tank 10,000 L", "Tank level / volume indication", "L"),
    "CP011": ("Heptane Tank recirculation / transfer system", "Centrifugal pump CP011 speed", "RPM"),
    "CP012": ("Heptane Tank recirculation / transfer system", "Centrifugal pump CP012 speed", "RPM"),
    "MFM": ("Heptane Tank transfer line", "Mass flow rate", "kg/h"),

    # ANFD-1
    "PICR34": ("ANFD-1", "Mechanical-seal pressure PICR34", "bar"),
    "PICR35": ("ANFD-1", "Mechanical-seal pressure PICR35", "bar"),
    "PICR36": ("ANFD-1", "Mechanical-seal pressure PICR36", "bar"),
    "TICR049": ("ANFD-1 utility line", "Temperature indication TICR049", "°C"),
    "TICR050": ("ANFD-1 utility line", "Temperature indication TICR050", "°C"),
    "TICR051": ("ANFD-1 utility line", "Temperature indication TICR051", "°C"),
    "TICR052": ("ANFD-1 utility line", "Temperature indication TICR052", "°C"),
    "TICR053": ("ANFD-1 utility line", "Temperature indication TICR053", "°C"),
    "TICR054": ("ANFD-1 / ANFD-2 shared utility indication", "Temperature indication TICR054", "°C"),
    "TICR069": ("ANFD-1 TCU-H03 utility line", "Temperature indication TICR069", "°C"),

    # ANFD-2
    "PICR32": ("ANFD-2", "Mechanical-seal pressure PICR32", "bar"),
    "PICR33": ("ANFD-2", "Mechanical-seal pressure PICR33", "bar"),
    "PICR43": ("ANFD-2", "Mechanical-seal pressure PICR43", "bar"),
    "TICR043": ("ANFD-2 utility line", "Temperature indication TICR043", "°C"),
    "TICR044": ("ANFD-2 utility line", "Temperature indication TICR044", "°C"),
    "TICR045": ("ANFD-2 utility line", "Temperature indication TICR045", "°C"),
    "TICR046": ("ANFD-2 utility line", "Temperature indication TICR046", "°C"),
    "TICR047": ("ANFD-2 utility line", "Temperature indication TICR047", "°C"),
    "TICR048": ("ANFD-2 utility line", "Temperature indication TICR048", "°C"),
    "TICR066": ("ANFD-2 TCU-H07 utility line", "Temperature indication TICR066", "°C"),

    # Utility distribution and headers
    "XV001": ("Utility Distribution - Pure Steam Inlet", "Pure-steam inlet control-valve output", "%"),
    "PICR13": ("Utility Distribution - Nitrogen Header", "Nitrogen inlet pressure", "bar"),
    "PICR14": ("Utility Distribution - Process Air Header", "Process-air inlet pressure", "bar"),
    "TICR001": ("Utility Distribution - Drain Header", "Drain-header temperature TICR001", "°C"),
    "TICR002": ("Utility Distribution - Drain Header", "Drain-header temperature TICR002", "°C"),
    "TICR003": ("Utility Distribution - Drain Header", "Drain-header temperature TICR003", "°C"),

    # CIP solution tank, WFI tank and wash-solvent loop
    "PICR044": ("CIP Solution Tank MDC 1000 L", "Tank pressure", "bar"),
    "RLS003": ("CIP Solution Tank MDC 1000 L", "Tank level / volume indication", "L"),
    "RLS007": ("WFI Tank 1000 L", "Tank level / volume indication", "L"),
    "QICR01": ("Wash Solvent Return Loop", "pH indication QICR01", "pH"),
    "QICR02": ("CIP Recirculation Loop", "pH indication QICR02", "pH"),
    "CICR01": ("CIP Drain / Wash Solvent Loop", "Conductivity indication CICR01", "µS/cm"),
    "CICR002": ("Wash Solvent Return Loop", "Conductivity indication CICR002", "µS/cm"),
    "CP002": ("CIP Recirculation System", "Centrifugal pump CP002 speed", "RPM"),
    "CP003": ("WFI Tank 1000 L", "WFI circulation pump CP003 speed", "RPM"),
    "CP004": ("WFI Tank 1000 L", "WFI circulation pump CP004 speed", "RPM"),
    "CP010": ("Wash Solvent Return Loop", "Centrifugal pump CP010 speed", "RPM"),

    # Spent-solvent and wash-solvent collection
    "RLS004": ("Spent Solvent Storage Tank 20,000 L", "Tank level / volume indication", "L"),
    "PICR045": ("Spent Solvent Storage Tank 20,000 L", "Tank pressure", "bar"),
    "RLS006": ("Wash Solvent Collection Tank 200 L", "Tank level / volume indication", "L"),
    "PICR46": ("Wash Solvent Collection Tank 200 L", "Tank pressure", "bar"),
    "CP008": ("Wash Solvent Collection System", "Centrifugal pump CP008 speed", "RPM"),

    # OMCA ANFDA drying HMI/report names
    "TT-01": ("OMCA ANFDA drying system", "Temperature TT-01", "°C"),
    "TT-02": ("OMCA ANFDA drying system", "Temperature TT-02", "°C"),
    "PT-01": ("OMCA ANFDA drying system", "Pressure PT-01", "barg"),
    "PICR32": ("ANFD-2 / OMCA ANFDA drying system", "Pressure PICR32", "barg"),
    "TICR066": ("ANFD-2 / OMCA ANFDA drying system", "Temperature TICR066", "°C"),
    "Filter_Pos": ("OMCA ANFDA drying system", "Filter position", "°"),
    "Agit_Rpm": ("OMCA ANFDA drying system", "Agitator speed", "RPM"),
    "Agit_Pos": ("OMCA ANFDA drying system", "Agitator axial position", "mm"),
}

# Legacy CV-04 / CV-05 process-report tags
HMI_TAG_MAP.update({
    "CV4WICR-01": ("CV-04 Vessel", "Vessel weight", "Kg"),
    "CV4TT-01": ("CV-04 Vessel", "Vessel temperature", "°C"),
    "CV4PT-01": ("CV-04 Vessel", "Vessel pressure", "bar"),
    "CV5WICR-01": ("CV-05 Vessel", "Vessel weight", "Kg"),
    "CV5TT-01": ("CV-05 Vessel", "Vessel temperature", "°C"),
    "CV5PT-01": ("CV-05 Vessel", "Vessel pressure", "bar"),
})

FLOW_SOURCE_TAGS = {
    "LSICR001": "MV-01 Polymer Mixing Tank",
    "LSICR002": "MV-02 Dimethicone Collection Tank",
    "LSICR003": "SFV-01 Sterile Filtration Vessel",
    "LSICR004": "MV-04 Coacervation Vessel",
    "LSICR005": "MV-05 Hardening Vessel",
    "LSICR006": "BV-01 Bed Wash Vessel-01 Ethanol",
    "LSICR007": "BV-02 Bed Wash Vessel-02 Heptane",
}

FLOW_DESTINATION_HINTS = {
    "LSICR001": "Downstream vessel identified from step status",
    "LSICR002": "Downstream vessel identified from step status",
    "LSICR003": "MV-04 / downstream vessel identified from step status",
    "LSICR004": "MV-05 / downstream vessel identified from step status",
    "LSICR005": "BV / ANFD / downstream vessel identified from step status",
    "LSICR006": "ANFD / downstream vessel identified from step status",
    "LSICR007": "ANFD / downstream vessel identified from step status",
}

def infer_destination(status):
    u=str(status or "").upper()
    aliases=[
        ("MV-01","MV-01 Polymer Mixing Tank"),("MV01","MV-01 Polymer Mixing Tank"),
        ("MV-02","MV-02 Dimethicone Collection Tank"),("MV02","MV-02 Dimethicone Collection Tank"),
        ("SFV-01","SFV-01 Sterile Filtration Vessel"),("SFV01","SFV-01 Sterile Filtration Vessel"),
        ("MV-04","MV-04 Coacervation Vessel"),("MV04","MV-04 Coacervation Vessel"),
        ("MV-05","MV-05 Hardening Vessel"),("MV05","MV-05 Hardening Vessel"),
        ("BV-01","BV-01 Bed Wash Vessel-01 Ethanol"),("BV01","BV-01 Bed Wash Vessel-01 Ethanol"),
        ("BV-02","BV-02 Bed Wash Vessel-02 Heptane"),("BV02","BV-02 Bed Wash Vessel-02 Heptane"),
        ("MLT-01","MLT-01 Mother Liquor Tank-01"),("MLT01","MLT-01 Mother Liquor Tank-01"),
        ("MLT-02","MLT-02 Mother Liquor Tank-02"),("MLT02","MLT-02 Mother Liquor Tank-02"),
        ("ANFD-01","ANFD-1"),("ANFD01","ANFD-1"),("ANFD-1","ANFD-1"),
        ("ANFD-02","ANFD-2"),("ANFD02","ANFD-2"),("ANFD-2","ANFD-2"),
    ]
    hits=[]
    for token,name in aliases:
        if token in u and name not in hits: hits.append(name)
    return " -> ".join(hits[-2:]) if hits else "Destination not explicit in step status"

def calculate_interval_flowrates(long_df, smoothing_points=3):
    \"\"\"Calculate mass flow for each consecutive valid load-cell interval, without averaging.\"\"\"
    if long_df is None or long_df.empty:
        return pd.DataFrame()
    work=long_df[long_df["Instrument tag"].isin(FLOW_SOURCE_TAGS)].copy()
    if work.empty:
        return pd.DataFrame()
    parts=[]
    group_cols=["Source report","Instrument tag"] if "Source report" in work.columns else ["Instrument tag"]
    for _,g in work.groupby(group_cols,dropna=False,observed=True):
        g=g.sort_values("Date time").drop_duplicates("Date time").copy()
        g["Raw weight (kg)"]=pd.to_numeric(g["Value"],errors="coerce")
        g["Smoothed weight (kg)"]=g["Raw weight (kg)"].rolling(max(1,int(smoothing_points)),center=True,min_periods=1).median()
        g["Previous time"]=g["Date time"].shift()
        g["Previous weight (kg)"]=g["Smoothed weight (kg)"].shift()
        g["Interval (min)"]=(g["Date time"]-g["Previous time"]).dt.total_seconds()/60
        g["Weight change (kg)"]=g["Smoothed weight (kg)"]-g["Previous weight (kg)"]
        g["Signed flow (kg/min)"]=g["Weight change (kg)"]/g["Interval (min)"]
        invalid=g["Interval (min)"].isna()|(g["Interval (min)"]<=0)|(g["Interval (min)"]>5)
        g.loc[invalid,"Signed flow (kg/min)"]=pd.NA
        g["Flowrate (kg/min)"]=g["Signed flow (kg/min)"].abs()
        g["Flowrate (kg/h)"]=g["Flowrate (kg/min)"]*60
        g["Transfer direction"]=g["Signed flow (kg/min)"].apply(lambda x:"Receiving / charging" if pd.notna(x) and x>0 else ("Source / discharging" if pd.notna(x) and x<0 else "No measurable change"))
        g["Vessel"]=g["Instrument tag"].astype(str).map(FLOW_SOURCE_TAGS)
        g["Destination / route"]=g["Step status"].map(infer_destination)
        parts.append(g)
    return pd.concat(parts,ignore_index=True) if parts else pd.DataFrame()

def add_hmi_tag_names(df):
    \"\"\"Add HMI names without tuple mapping or MultiIndex construction.\"\"\"
    if df is None or df.empty or "Instrument tag" not in df.columns:
        return df
    out=df.copy()

    # Convert categorical tags to ordinary strings before mapping. Mapping a
    # categorical Series to tuples can create a pandas MultiIndex and trigger
    # "isna is not defined for MultiIndex" on Streamlit Cloud.
    tags=out["Instrument tag"].astype("string").fillna("")
    equipment_map={tag:values[0] for tag,values in HMI_TAG_MAP.items()}
    measurement_map={tag:values[1] for tag,values in HMI_TAG_MAP.items()}
    unit_map={tag:values[2] for tag,values in HMI_TAG_MAP.items()}

    out["Instrument tag"]=tags.astype(str)
    out["HMI equipment"]=tags.map(equipment_map).fillna("Not mapped from supplied HMI screens").astype(str)
    fallback_measurement="Instrument tag "+tags.astype(str)
    mapped_measurement=tags.map(measurement_map)
    out["HMI measurement name"]=mapped_measurement.where(mapped_measurement.notna(),fallback_measurement).astype(str)

    if "Unit" in out.columns:
        existing=out["Unit"].astype("string").fillna("").str.strip()
        defaults=tags.map(unit_map).fillna("").astype(str)
        out["Unit"]=existing.where(existing.ne(""),defaults).astype(str)

    out["HMI display label"]=(
        out["Instrument tag"].astype(str)+" | "+
        out["HMI equipment"].astype(str)+" | "+
        out["HMI measurement name"].astype(str)
    )
    return out

def extract_pdf_pages(raw: bytes):
    \"\"\"Fast PDF text extraction using Poppler, with pdfplumber fallback.\"\"\"
    started=time.perf_counter()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            pdf_path=os.path.join(tmp,"input.pdf")
            txt_path=os.path.join(tmp,"output.txt")
            with open(pdf_path,"wb") as f:
                f.write(raw)
            completed=subprocess.run(
                ["pdftotext","-layout","-enc","UTF-8",pdf_path,txt_path],
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,
                timeout=180,check=False,
            )
            if completed.returncode==0 and os.path.exists(txt_path):
                text=Path(txt_path).read_text(encoding="utf-8",errors="replace")
                pages=text.split("\f")
                if pages and not pages[-1].strip(): pages=pages[:-1]
                if any(x.strip() for x in pages):
                    return pages,"Poppler pdftotext",time.perf_counter()-started
    except (FileNotFoundError,subprocess.TimeoutExpired,OSError):
        pass

    # Portable fallback when Poppler is unavailable.
    with pdfplumber.open(BytesIO(raw)) as pdf:
        pages=[page.extract_text(layout=True) or "" for page in pdf.pages]
    return pages,"pdfplumber fallback",time.perf_counter()-started

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

TAG_ALIASES = {
    "PICR12":"PICR012", "PICR012":"PICR012",
    "PICR15":"PICR15", "PICR015":"PICR15",
    "PICR16":"PICR16", "PICR016":"PICR16",
    "PICR17":"PICR17", "PICR017":"PICR17",
    "PICR18":"PICR18", "PICR018":"PICR18",
    "PICR19":"PICR19", "PICR019":"PICR19",
    "TLP01":"TLP001", "TLP001":"TLP001",
    "TLP02":"TLP002", "TLP002":"TLP002",
}

def canonical_tag(tag):
    raw=str(tag or "").strip().replace("\\_","_")
    return TAG_ALIASES.get(raw.upper(),raw.upper())

def scan_report_tag_headers(pages):
    \"\"\"Inventory every tag printed in cycle/event headers, even if no data row is parsed.\"\"\"
    found=[]
    for page_no,text in enumerate(pages,1):
        lines=text.splitlines()
        section="Event" if "EVENT RECORD" in text.upper() else ("Cycle" if "CYCLE RECORD" in text.upper() else "Other")
        for line in lines:
            u=line.upper()
            if "DATE TIME" in u and ("STEP STATUS" in u or "EVENT STATUS" in u):
                right=re.split(r"DATE TIME",line,flags=re.I,maxsplit=1)[1]
                right=re.sub(r"(?:STEP|EVENT) STATUS.*$","",right,flags=re.I)
                for candidate in [x.strip() for x in re.split(r"\s{2,}",right) if x.strip()]:
                    if TAG_RE.match(candidate):
                        found.append({"Raw report tag":candidate,"Canonical tag":canonical_tag(candidate),"Section":section,"Header page":page_no})
            if re.match(r"^\s*Tag\s+",line,re.I):
                for candidate in [x.strip() for x in re.split(r"\s{2,}",line.strip())[1:] if x.strip()]:
                    if TAG_RE.match(candidate):
                        found.append({"Raw report tag":candidate,"Canonical tag":canonical_tag(candidate),"Section":section,"Header page":page_no})
    return pd.DataFrame(found).drop_duplicates() if found else pd.DataFrame(columns=["Raw report tag","Canonical tag","Section","Header page"])

def header_tags(page_text):
    \"\"\"Extract every tag token from the current page header without relying on spacing.\"\"\"
    lines=page_text.splitlines()
    tags=[]; units={}; record_type=None
    for line in lines:
        upper=line.upper()
        if "CYCLE RECORD" in upper: record_type="Cycle"
        if "EVENT RECORD" in upper: record_type="Event"

    # The DATE TIME row is repeated on every data page and is the most reliable source.
    for line in lines:
        upper=line.upper()
        if "DATE TIME" in upper and ("STEP STATUS" in upper or "EVENT STATUS" in upper):
            right=re.split(r"DATE TIME",line,flags=re.I,maxsplit=1)[1]
            right=re.sub(r"(?:STEP|EVENT) STATUS.*$","",right,flags=re.I)
            found=[canonical_tag(x) for x in TAG_TOKEN_RE.findall(right)]
            if found:
                tags=list(dict.fromkeys(found))
                break

    # The explicit Tag row is authoritative when present.
    for line in lines:
        if re.match(r"^\s*Tag\s+",line,re.I):
            found=[canonical_tag(x) for x in TAG_TOKEN_RE.findall(re.sub(r"^\s*Tag\s+","",line,flags=re.I))]
            if found: tags=list(dict.fromkeys(found))
        if re.match(r"^\s*Unit\s+",line,re.I) and tags:
            vals=[x.strip() for x in re.split(r"\s{2,}",line.strip())[1:] if x.strip()]
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
            status_tokens=tokens[len(current_tags):]
            leaked=[]
            while status_tokens and NUMBER_RE.match(status_tokens[0]):
                leaked.append(status_tokens.pop(0))
            status=clean_text(" ".join(status_tokens))
            if not status:
                status="STATUS NOT CAPTURED"
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
    if not long_df.empty:
        long_df["Step status"]=long_df["Step status"].fillna("").astype(str).str.strip()
    return wide,long_df,pd.DataFrame(events),pd.DataFrame(alarms)

def repair_missing_decimal_points(long_df, user_corrections=None):
    \"\"\"Repair clear OCR decimal-loss outliers and apply user manual corrections.
    
    The current reading is excluded from the local reference. Decimal candidates
    value/10, value/100 and value/1000 are tested. A change is accepted only
    when the candidate agrees closely with neighboring readings and improves
    the local error by at least 90%. Weight/load-cell readings are excluded.
    
    Any provided user corrections are applied sequentially.
    \"\"\"
    if long_df is None or long_df.empty or "Value" not in long_df.columns:
        return long_df
    out=long_df.copy()
    out["Value"]=pd.to_numeric(out["Value"],errors="coerce")
    out["OCR original value"]=out["Value"]
    out["OCR decimal repaired"]=False
    
    # 1. Automatic OCR repair for missing decimals
    for tag,idx in out.sort_values("Date time").groupby("Instrument tag",sort=False).groups.items():
        upper=str(tag).upper()
        compact=re.sub(r"[^A-Z0-9]","",upper)
        is_weight=("WICR" in upper or upper.startswith("LSICR"))
        is_temp=(upper.startswith(("TICR","TT-")) or re.search(r"CV[45]TT0*1$",compact))
        is_pressure=(upper.startswith(("PICR","PT-")) or re.search(r"CV[45]PT0*1$",compact))
        
        # Skip automatic repair for load cells
        if is_weight: 
            continue
            
        ordered=list(idx)
        vals=pd.to_numeric(out.loc[ordered,"Value"],errors="coerce")
        # Neighbor-only reference prevents the malformed value from masking itself.
        prev_vals=vals.shift(1)
        next_vals=vals.shift(-1)
        ref=pd.concat([prev_vals,next_vals],axis=1).median(axis=1,skipna=True)
        for row_i,current,reference in zip(ordered,vals,ref):
            if pd.isna(current) or pd.isna(reference) or abs(reference)<0.01:
                continue
            
            # Check 10, 100, 1000 divisors
            candidates=[current/10.0, current/100.0, current/1000.0]
            best=min(candidates,key=lambda x:abs(x-reference))
            old_error=abs(current-reference)
            new_error=abs(best-reference)
            tolerance=max(0.25,0.08*abs(reference))
            
            # If the current value is huge compared to reference (missing decimal), and the repaired 
            # version is extremely close to the reference, accept the fix.
            if abs(current)>=8*abs(reference) and new_error<=tolerance and new_error<=0.10*old_error:
                out.at[row_i,"Value"]=round(best,6)
                out.at[row_i,"OCR decimal repaired"]=True

    # 2. Apply explicit user manual corrections if provided
    if user_corrections is not None and not user_corrections.empty:
        for idx, row in user_corrections.iterrows():
            mask = (out["Date time"] == row["Date time"]) & (out["Instrument tag"] == row["Instrument tag"]) & (out["Source report"] == row["Source report"])
            if mask.any():
                out.loc[mask, "Value"] = float(row["Corrected value"])
                out.loc[mask, "OCR decimal repaired"] = True

    return out

def extract_pdf_pages_ocr(raw: bytes, first_page=1, last_page=None):
    \"\"\"Low-CPU, single-pass, page-at-a-time OCR for scanned legacy reports.\"\"\"
    started=time.perf_counter()
    if not shutil.which("pdftoppm") or not shutil.which("tesseract"):
        raise RuntimeError("Legacy OCR requires poppler-utils and tesseract-ocr in packages.txt.")
    first_page=max(1,int(first_page)); last_page=max(first_page,int(last_page or first_page))
    env=os.environ.copy()
    env.update({"OMP_THREAD_LIMIT":"1","OMP_NUM_THREADS":"1","OPENBLAS_NUM_THREADS":"1","MKL_NUM_THREADS":"1","NUMEXPR_NUM_THREADS":"1"})
    pages=[]
    with tempfile.TemporaryDirectory() as tmp:
        pdf_path=os.path.join(tmp,"input.pdf")
        with open(pdf_path,"wb") as f: f.write(raw)
        total=last_page-first_page+1
        status_box=st.empty(); page_progress=st.progress(0,text="Preparing OCR...")
        for n,page_no in enumerate(range(first_page,last_page+1),1):
            status_box.caption(f"OCR page {page_no} ({n} of {total})")
            prefix=os.path.join(tmp,f"page_{page_no}")
            cmd=["pdftoppm","-f",str(page_no),"-l",str(page_no),"-r","150","-png","-singlefile",pdf_path,prefix]
            completed=subprocess.run(cmd,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE,timeout=90,check=False,env=env)
            if completed.returncode!=0:
                raise RuntimeError(f"Poppler failed on page {page_no}: {completed.stderr.decode(errors='replace')[-300:]}")
            img=Path(prefix+".png")
            if not img.exists(): raise RuntimeError(f"Rendered image missing for page {page_no}.")
            source=img
            if shutil.which("magick"):
                angle=90 if page_no%2 else 270
                rotated=Path(prefix+"_rot.png")
                subprocess.run(["magick",str(img),"-rotate",str(angle),str(rotated)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=45,check=True,env=env)
                source=rotated
            command=["tesseract",str(source),"stdout","-l","eng","--psm","4"]
            if shutil.which("nice"): command=["nice","-n","10"]+command
            result=subprocess.run(command,capture_output=True,text=True,timeout=75,check=False,env=env)
            if result.returncode!=0:
                raise RuntimeError(f"Tesseract failed on page {page_no}: {result.stderr[-300:]}")
            pages.append(result.stdout or "")
            img.unlink(missing_ok=True); Path(prefix+"_rot.png").unlink(missing_ok=True)
            page_progress.progress(n/total,text=f"OCR page {page_no}: {n} of {total}")
            gc.collect()
        page_progress.empty(); status_box.empty()
    return pages,"Low-CPU Poppler 150 DPI + single-pass Tesseract",time.perf_counter()-started

LEGACY_STEP_NAME_MAP = {
    "TRANSFER FROM CV-05 TO ANFD": "TRANSFER FROM CV-05 TO ANFD",
    "CV-04 ADD API SOLUTION TO CV-03": "CV-04 ADD API SOLUTION TO CV-03",
    "CV-04 AGITATION": "CV-04 AGITATION",
    "CV-04 API DISPERSION": "CV-04 API DISPERSION",
    "CV-04 CHARGE PLGA USING N2": "CV-04 CHARGE PLGA USING N2",
    "CV-04 CHECKS": "CV-04 PRESSURIZATION": "CV-04 PRESSURIZATION",
    "CV-04 TRANSFER API SOLUTION TO CV-04": "CV-04 TRANSFER API SOLUTION TO CV-04",
    "CV-05 TC & N2 BLANKETING HOLD TIME": "CV-05 TC & N2 BLANKETING HOLD TIME",
    "CYCLE HOLD": "CYCLE HOLD", "HOLD TIME": "HOLD TIME",
    "TRANSFER COACEVRATES CV-04 TO CV-05": "TRANSFER COACEVRATES CV-04 to CV-05",
    "TRANSFER DIMETHICON FROM FROM FV-01 TO CV-04": "TRANSFER DIMETHICON FROM FROM FV-01 TO CV-04",
    "TRANSFER FROM V-01 TO CV-05": "TRANSFER FROM V-01 TO CV-05",
    "TRANSFER FROM V-02 TO CV-05": "TRANSFER FROM V-02 TO CV-05",
    "V-01 CHARGE HEPTANE": "V-01 CHARGE HEPTANE",
    "V-01 RECIRCULATION": "V-01 RECIRCULATION",
}
def correct_legacy_step_name(value):
    raw=clean_text(value)
    if not raw: return raw
    cleaned=re.sub(r"\s+"," ",raw.strip(" ‘'`|.,"))
    upper=cleaned.upper()
    upper=re.sub(r"\bAP(?:!|\||1)\s+SOLUTION\b","API SOLUTION",upper)
    upper=re.sub(r"\bANED\b","ANFD",upper)
    upper=re.sub(r"\s+AAA$","",upper).strip(" |.,")
    return LEGACY_STEP_NAME_MAP.get(upper,cleaned.strip(" |.,"))

def parse_legacy_cv_report(pages, source_page_offset=0):
    \"\"\"Parse scanned CV4/CV5 process tables while preserving every source-column position.\"\"\"
    target={"CV4WICR-01","CV4TT-01","CV4PT-01","CV5WICR-01","CV5TT-01","CV5PT-01"}
    unit_map={"WICR":"Kg","TT":"°C","PT":"bar","AG":"rpm"}
    long_rows=[]; groups={}; inventory=[]
    row_re=re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+)$")

    def normalized_header(line):
        x=line.upper().replace("|"," ").replace("["," ").replace("]"," ").replace("{"," ").replace("}"," ")
        fixes={"CVSWICR":"CV5WICR","CVSTT":"CV5TT","CVSPT":"CV5PT","CVSAG":"CV5AG",
               "CVATT":"CV4TT","CVAWICR":"CV4WICR","CVAPT":"CV4PT","CVAAG":"CV4AG",
               "NCV3PT-O1":"NCV3PT-01","CV3TT-O1":"CV3TT-01"}
        for a,b in fixes.items(): x=x.replace(a,b)
        return x

    for local_page,text in enumerate(pages,1):
        source_page=source_page_offset+local_page
        lines=[" ".join(x.split()) for x in text.splitlines() if x.strip()]
        tags=[]
        for line in lines:
            if line.upper().startswith("TAG "):
                header=normalized_header(line)
                
                # REPAIR: If the OCR merged tags together (e.g. CV5WICR-01CV5TT-01), insert a space
                # so that re.findall extracts them in the correct column order.
                for t in ["CV4WICR-01", "CV4TT-01", "CV4PT-01", "CV5WICR-01", "CV5TT-01", "CV5PT-01"]:
                     header = header.replace(t, f" {t} ")
                
                tags=re.findall(r"N?CV[345](?:WICR|TT|PT|AG)-0?1",header)
                tags=[re.sub(r"-0?1$","-01",x) for x in tags]
                break
        
        # Known five-column report layouts. These fallbacks preserve ignored columns so values do not leak into Cycle Step.
        joined=" ".join(lines).upper()
        # These legacy reports have fixed five-value layouts. Never trust a partial OCR header,
        # because losing the two leading columns shifts every requested value and corrupts status text.
        if (196 <= source_page <= 237) or "CV4WICR" in joined or "CV4PT-01" in joined:
            tags=["NCV3PT-01","CV3TT-01","CV4WICR-01","CV4TT-01","CV4PT-01"]
        elif (275 <= source_page <= 316) or "CV5WICR" in joined or "CV5PT-01" in joined:
            tags=["CV4AG-01","CV5WICR-01","CV5TT-01","CV5PT-01","CV5AG-01"]
        if not tags: continue

        selected=[t for t in tags if t in target]
        if not selected: continue
        for tag in selected:
            inventory.append({"Raw report tag":tag,"Canonical tag":tag,"Section":"Process Report","Header page":source_page})
        group_name=" + ".join(selected); wide=[]
        for raw in lines:
            m=row_re.match(raw)
            if not m: continue
            tokens=m.group(3).split()
            
            # REPAIR: Some OCR engines drop None entirely or merge values. We must pad
            # the numeric tokens if there are fewer numeric tokens than tags, assuming
            # trailing tags are 'None'. We must also enforce column order strictly.
            
            if len(tokens) < len(tags): 
                continue
                
            numeric=tokens[:len(tags)]
            
            # Ensure "None" is handled as NaN so we don't shift columns left
            cleaned_numeric = []
            for num in numeric:
                if num.upper() == "NONE":
                    cleaned_numeric.append(pd.NA)
                elif NUMBER_RE.fullmatch(num):
                    cleaned_numeric.append(float(num))
                else:
                    cleaned_numeric.append(pd.NA)
            
            dt=pd.to_datetime(m.group(1)+" "+m.group(2),dayfirst=True,errors="coerce")
            if pd.isna(dt): continue
            status=correct_legacy_step_name(" ".join(tokens[len(tags):])) or "STATUS NOT CAPTURED"
            # Reject a corrupted status that still starts with a numeric sensor value.
            while status and re.match(r"^-?\d+(?:\.\d+)?(?:\s|$)",status):
                status=re.sub(r"^-?\d+(?:\.\d+)?\s*","",status,1).strip()
            wrow={"Date time":dt,"Status":status,"Source page":source_page}
            for idx,(tag,value) in enumerate(zip(tags,cleaned_numeric)):
                if tag not in target: continue
                val=value; kind=re.search(r"(WICR|TT|PT|AG)",tag)
                unit=unit_map.get(kind.group(1),"") if kind else ""
                wrow[tag]=val
                long_rows.append({"Date time":dt,"Instrument tag":tag,"Value":val,"Unit":unit,
                    "Step status":status,"Instrument group":group_name,"Source page":source_page})
            if any(t in wrow for t in target): wide.append(wrow)
        if wide: groups[f"Page {source_page}: {group_name}"]=pd.DataFrame(wide)

    long_df=pd.DataFrame(long_rows)
    if not long_df.empty:
        long_df=long_df.sort_values(["Date time","Instrument tag","Source page"]).drop_duplicates(["Date time","Instrument tag"],keep="first")
    inv=pd.DataFrame(inventory).drop_duplicates() if inventory else pd.DataFrame(columns=["Raw report tag","Canonical tag","Section","Header page"])
    return groups,long_df,pd.DataFrame(),pd.DataFrame(),inv

def detect_report_type(pages):
    \"\"\"Automatically classify supported PDF layouts using multiple independent markers.\"\"\"
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
    \"\"\"Parse OMCA ANFDA/ANFD-2 reports with sequence + time-only rows.\"\"\"
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


def build_cross_batch_wide(valid_reports):
    \"\"\"Reconstruct one wide process table per uploaded report.\"\"\"
    frames = []
    for item in valid_reports:
        d = item.get("long_df", pd.DataFrame()).copy()
        if d.empty or not {"Date time", "Instrument tag", "Value", "Step status"}.issubset(d.columns):
            continue
        d["Instrument tag"] = d["Instrument tag"].astype(str)
        wide = (d[["Date time", "Instrument tag", "Value"]]
                .drop_duplicates(["Date time", "Instrument tag"], keep="first")
                .pivot(index="Date time", columns="Instrument tag", values="Value")
                .reset_index())
        status = d[["Date time", "Step status"]].drop_duplicates("Date time", keep="first")
        wide = wide.merge(status, on="Date time", how="left")
        # Use the uploaded PDF filename without the extension as the single batch identifier.
        batch = pdf_name_as_batch_number(item.get("file_name", ""))
        wide.insert(0, "Source report", item["file_name"])
        wide.insert(1, "Batch", batch)
        frames.append(wide)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def make_step_elapsed_profile(wide_df, selected_steps):
    \"\"\"Align every contiguous step occurrence at elapsed time zero.\"\"\"
    parts = []
    for report, g in wide_df.groupby("Source report", sort=False):
        g = g.sort_values("Date time").copy()
        g = g[g["Step status"].astype(str).isin(selected_steps)].copy()
        if g.empty:
            continue
        gap = g["Date time"].diff().dt.total_seconds().div(60)
        g["Step occurrence"] = (g["Step status"].ne(g["Step status"].shift()) | gap.gt(5)).cumsum()
        g["Elapsed time (min)"] = g.groupby("Step occurrence")["Date time"].transform(
            lambda x: (x - x.min()).dt.total_seconds() / 60
        )
        g["Profile label"] = (g["Batch"].astype(str) + " | " + g["Step status"].astype(str)
                              + " | Run " + g["Step occurrence"].astype(str))
        parts.append(g)
    return pd.concat(parts, ignore_index=True, sort=False) if parts else pd.DataFrame()

def identify_process_sequences(data, start_step, end_step, max_duration_minutes=180):
    \"\"\"Pair each start-step occurrence with the next end-step occurrence.

    The returned rows include every process status between the two boundaries,
    which creates the requested continuous profile rather than sparse selected-step lines.
    \"\"\"
    d=data.sort_values("Date time").copy()
    if d.empty:
        return []
    status=d["Step status"].astype(str)
    new_run=status.ne(status.shift()) | d["Date time"].diff().dt.total_seconds().div(60).gt(5)
    d["_run"]=new_run.cumsum()
    runs=(d.groupby("_run",as_index=False)
          .agg(Status=("Step status","first"),Start=("Date time","min"),End=("Date time","max"),Rows=("Date time","size")))
    start_norm=normalize_step_name(start_step)
    end_norm=normalize_step_name(end_step)
    runs["_Status norm"]=runs["Status"].astype(str).map(normalize_step_name)
    starts=runs[runs["_Status norm"]==start_norm]
    ends=runs[runs["_Status norm"]==end_norm]
    sequences=[]
    for _,sr in starts.iterrows():
        possible=ends[(ends["Start"]>=sr["Start"]) &
                      ((ends["End"]-sr["Start"]).dt.total_seconds()/60<=float(max_duration_minutes))]
        if possible.empty:
            continue
        er=possible.iloc[0]
        seq=d[(d["Date time"]>=sr["Start"]) & (d["Date time"]<=er["End"])].copy()
        if seq.empty:
            continue
        mv04_gain=0.0
        if "LSICR004" in seq.columns and seq["LSICR004"].notna().any():
            mv04_gain=float(seq["LSICR004"].iloc[-1]-seq["LSICR004"].iloc[0])
        duration=(er["End"]-sr["Start"]).total_seconds()/60
        label=(f"{sr['Start']:%d-%m-%Y %H:%M} to {er['End']:%H:%M} | "
               f"{duration:.0f} min | {len(seq):,} rows | MV04 net {mv04_gain:.2f} kg")
        sequences.append({"label":label,"start":sr["Start"],"end":er["End"],
                          "duration":duration,"gain":mv04_gain,"data":seq})
    return sequences

def identify_profile_windows(data, selected_steps, gap_minutes=10):
    \"\"\"Split matching process records into contiguous chronological windows.\"\"\"
    d=data[data["Step status"].astype(str).isin(selected_steps)].sort_values("Date time").copy()
    if d.empty:
        return d, []
    gap=d["Date time"].diff().dt.total_seconds().div(60)
    d["Profile window"]=(gap.isna()|gap.gt(float(gap_minutes))).cumsum()
    options=[]
    for window_id,g in d.groupby("Profile window",sort=True):
        start=g["Date time"].min(); end=g["Date time"].max()
        steps=[]
        for value in g["Step status"].astype(str):
            if value not in steps: steps.append(value)
        gain=0.0
        if "LSICR004" in g.columns and g["LSICR004"].notna().any():
            gain=float(g["LSICR004"].max()-g["LSICR004"].min())
        label=(f"Window {int(window_id)} | {start:%d-%m-%Y %H:%M} to {end:%H:%M} | "
               f"{len(g):,} rows | MV04 range {gain:.2f} kg")
        options.append({"id":window_id,"label":label,"start":start,"end":end,"gain":gain,"steps":steps})
    return d,options

def normalize_step_name(value):
    \"\"\"Normalize report step names so hyphens/spaces do not prevent matching.\"\"\"
    return re.sub(r"[^A-Z0-9]+", "", str(value or "").upper())


def add_target_step_highlight(
    fig,
    profile,
    tags,
    axis_for_tag,
    target_step,
    x_column,
    highlight_color="#FFC000",
    band_opacity=0.12,
    show_band=True,
):
    \"\"\"Overlay a bold line and optional vertical band for one process step.

    A separate highlighted segment is drawn for every batch and selected sensor.
    This is suitable for cross-batch plots because each batch can enter the
    target step at a different elapsed time.
    \"\"\"
    if profile is None or profile.empty or not target_step:
        return fig
    required={"Batch","Step status",x_column}
    if not required.issubset(profile.columns):
        return fig

    target_norm=normalize_step_name(target_step)
    if not target_norm:
        return fig
    work=profile.copy()
    work["_step_norm"]=work["Step status"].map(normalize_step_name)
    work=work[work["_step_norm"]==target_norm].copy()
    if work.empty:
        return fig

    # Highlight each contiguous occurrence. A five-minute gap starts a new block.
    legend_added=False
    for batch_name,batch_data in work.groupby("Batch",sort=False):
        batch_data=batch_data.sort_values(x_column).copy()
        gap=pd.to_numeric(batch_data[x_column],errors="coerce").diff()
        batch_data["_highlight_block"]=(gap.isna()|gap.gt(5)).cumsum()
        for _,block in batch_data.groupby("_highlight_block",sort=True):
            x_values=pd.to_numeric(block[x_column],errors="coerce").dropna()
            if x_values.empty:
                continue
            x0=float(x_values.min()); x1=float(x_values.max())
            # Give a one-sample step a visible width without overstating duration.
            if x1<=x0:
                x1=x0+0.5
            if show_band:
                fig.add_vrect(
                    x0=x0,
                    x1=x1,
                    fillcolor=highlight_color,
                    opacity=float(band_opacity),
                    line_width=1,
                    line_color=highlight_color,
                    layer="below",
                )
            for tag in tags:
                if tag not in block.columns:
                    continue
                segment=block[[x_column,tag,"Batch","Step status","Date time"]].dropna(subset=[tag]).sort_values(x_column)
                if segment.empty:
                    continue
                fig.add_trace(go.Scatter(
                    x=segment[x_column],
                    y=segment[tag],
                    mode="lines+markers",
                    name=f"Highlighted: {target_step}",
                    legendgroup="target_step_highlight",
                    showlegend=not legend_added,
                    yaxis=axis_for_tag.get(tag,"y"),
                    line=dict(color=highlight_color,width=6),
                    marker=dict(color=highlight_color,size=9,line=dict(color="white",width=1)),
                    customdata=segment[["Batch","Step status","Date time"]].astype(str).to_numpy(),
                    hovertemplate=(
                        f"Highlighted step={target_step}<br>Batch=%{{customdata[0]}}"
                        f"<br>Sensor={tag}<br>Step=%{{customdata[1]}}"
                        "<br>Elapsed=%{x:.1f} min<br>Actual time=%{customdata[2]}"
                        "<br>Value=%{y:.3f}<extra></extra>"
                    ),
                ))
                legend_added=True
    return fig

def build_multi_sensor_profile(profile, tags, title=None, y_ranges=None, highlight_step=None, highlight_color="#FFC000", highlight_opacity=0.12, show_highlight_band=True):
    \"\"\"Overlay multiple selected sensors in one interactive graph.

    Sensors are assigned to separate Y-axis families so weight, temperature,
    and pressure can be viewed together without forcing a common scale.
    \"\"\"
    if profile.empty or not tags:
        return go.Figure()
    y_ranges=y_ranges or {}

    d=profile.sort_values("Date time").copy()
    d["Date time"]=pd.to_datetime(d["Date time"],errors="coerce")
    d=d.dropna(subset=["Date time"])
    if d.empty:
        return go.Figure()
    d["Elapsed time (min)"]=(d["Date time"]-d["Date time"].min()).dt.total_seconds()/60.0
    fig=go.Figure()
    palette=px.colors.qualitative.Plotly + px.colors.qualitative.Safe + px.colors.qualitative.Set2

    def sensor_family(tag):
        upper=str(tag).upper()
        if upper.startswith("LSICR"):
            return "Weight (kg)"
        if upper.startswith(("TICR","TT-")):
            return "Temperature (°C)"
        if upper.startswith(("PICR","PT-")):
            return "Pressure (bar)"
        return "Value"

    families=[]
    for tag in tags:
        fam=sensor_family(tag)
        if fam not in families:
            families.append(fam)
    axis_for={fam:("y" if i==0 else f"y{i+1}") for i,fam in enumerate(families)}

    for i,tag in enumerate(tags):
        if tag not in d.columns:
            continue
        g=d[["Date time","Elapsed time (min)",tag,"Batch","Step status"]].dropna(subset=[tag]).sort_values("Elapsed time (min)")
        if g.empty:
            continue
        fig.add_trace(go.Scatter(
            x=(g["Date time"]-d["Date time"].min()).dt.total_seconds()/60.0,
            y=g[tag],
            mode="lines+markers",
            name=tag,
            yaxis=axis_for[sensor_family(tag)],
            line=dict(width=2.4,color=palette[i%len(palette)]),
            marker=dict(size=5,color=palette[i%len(palette)]),
            customdata=g[["Batch","Step status"]].astype(str).to_numpy(),
            hovertemplate=(
                f"Tag={tag}<br>Batch=%{{customdata[0]}}<br>"
                "Step=%{customdata[1]}<br>Elapsed=%{x:.1f} min<br>"
                "Value=%{y:.3f}<extra></extra>"
            ),
        ))

    # Highlight each contiguous process step across the complete graph.
    step_frame=d[["Date time","Step status"]].drop_duplicates("Date time").sort_values("Date time").copy()
    gap=step_frame["Date time"].diff().dt.total_seconds().div(60)
    step_frame["_segment"]=(step_frame["Step status"].ne(step_frame["Step status"].shift())|gap.gt(5)).cumsum()
    step_colors=["#DDF3EF","#EEEAF6","#DCECF7","#E9F6CF","#F1F1F1","#E9F7EA","#FFF4BF","#FDE8E8"]
    status_order=[]
    for _,seg in step_frame.groupby("_segment",sort=True):
        status=str(seg["Step status"].iloc[0])
        if status not in status_order:
            status_order.append(status)
        color=step_colors[status_order.index(status)%len(step_colors)]
        fig.add_vrect(
            x0=(seg["Date time"].min()-d["Date time"].min()).total_seconds()/60,
            x1=(seg["Date time"].max()-d["Date time"].min()).total_seconds()/60+1,
            fillcolor=color,opacity=0.42,line_width=0,layer="below",
        )

    # Add square legend keys for process steps.
    for i,status in enumerate(status_order):
        fig.add_trace(go.Scatter(
            x=[None],y=[None],mode="markers",name=status,
            legendgroup=f"status_{i}",
            marker=dict(size=13,symbol="square",color=step_colors[i%len(step_colors)]),
            hoverinfo="skip",
        ))

    axis_layout={}
    for i,fam in enumerate(families):
        key="yaxis" if i==0 else f"yaxis{i+1}"
        axis_layout[key]=dict(
            title=fam,
            showgrid=(i==0),
            gridcolor="#E6E8EB",
            zeroline=False,
            fixedrange=False,
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
        )
        family_tags=[tag for tag in tags if sensor_family(tag)==fam and tag in y_ranges]
        if family_tags:
            axis_layout[key]["range"]=[
                min(y_ranges[tag][0] for tag in family_tags),
                max(y_ranges[tag][1] for tag in family_tags),
            ]
        if i>0:
            axis_layout[key].update(
                overlaying="y",
                side="right",
                position=max(0.78,1-(i-1)*0.08),
            )

    axis_for_tag={tag:axis_for.get(sensor_family(tag),"y") for tag in tags}
    fig=add_target_step_highlight(
        fig,d,tags,axis_for_tag,highlight_step,"Elapsed time (min)",
        highlight_color=highlight_color,band_opacity=highlight_opacity,
        show_band=show_highlight_band,
    )
    tick_source=d.drop_duplicates("Elapsed time (min)").sort_values("Elapsed time (min)")
    if len(tick_source)>8:
        positions=[round(i*(len(tick_source)-1)/7) for i in range(8)]
        tick_source=tick_source.iloc[positions]
    tickvals=tick_source["Elapsed time (min)"].tolist()
    ticktext=[pd.to_datetime(x).strftime("%d-%m-%Y %H:%M") for x in tick_source["Date time"]]

    fig.update_layout(
        title=dict(
            text=title or "Multi-Sensor Process Profile with Step Segmentation",
            x=0.5,xanchor="center",font=dict(size=23,color="#111111"),
        ),
        height=740,
        template="plotly_white",
        paper_bgcolor="white",
        plot_bgcolor="white",
        hovermode="x unified",
        dragmode="zoom",
        margin=dict(l=85,r=190,t=110,b=205),
        legend=dict(
            orientation="h",x=0.5,y=-0.27,xanchor="center",yanchor="top",
            title=dict(text="Sensors and process status"),font=dict(size=10),
        ),
        xaxis=dict(
            title="Elapsed time from sequence start (min)",showgrid=True,gridcolor="#EEF0F2",
            rangeselector=dict(
                buttons=[
                    dict(count=10,label="10m",step="minute",stepmode="backward"),
                    dict(count=30,label="30m",step="minute",stepmode="backward"),
                    dict(count=1,label="1h",step="hour",stepmode="backward"),
                    dict(step="all",label="All"),
                ],x=0.0,y=1.10,
            ),
            showspikes=True,spikemode="across",spikesnap="cursor",spikethickness=1,
        ),
        xaxis2=dict(title="Actual date and time",overlaying="x",side="top",tickmode="array",tickvals=tickvals,ticktext=ticktext,showgrid=False),
        **axis_layout,
    )
    return fig

def build_cross_batch_sensor_profile(profile, tags, title, y_ranges=None, highlight_step=None, highlight_color="#FFC000", highlight_opacity=0.12, show_highlight_band=True):
    \"\"\"Overlay selected batches with elapsed minutes below and actual date/time above.\"\"\"
    if profile.empty or not tags:
        return go.Figure()
    y_ranges=y_ranges or {}
    fig=go.Figure()
    palette=px.colors.qualitative.Plotly+px.colors.qualitative.Safe+px.colors.qualitative.Set2

    def sensor_family(tag):
        upper=str(tag).upper()
        if upper.startswith("LSICR"): return "Weight (kg)"
        if upper.startswith(("TICR","TT-")): return "Temperature (°C)"
        if upper.startswith(("PICR","PT-")): return "Pressure (bar)"
        return "Value"

    families=[]
    for tag in tags:
        fam=sensor_family(tag)
        if fam not in families: families.append(fam)
    axis_for={fam:("y" if i==0 else f"y{i+1}") for i,fam in enumerate(families)}
    trace_index=0
    for batch_name,batch_data in profile.groupby("Batch",sort=False):
        for tag in tags:
            if tag not in batch_data.columns: continue
            g=batch_data.dropna(subset=[tag]).sort_values("Elapsed time (min)")
            if g.empty: continue
            fig.add_trace(go.Scatter(
                x=g["Elapsed time (min)"],y=g[tag],mode="lines+markers",
                name=f"{batch_name} | {tag}",yaxis=axis_for[sensor_family(tag)],
                line=dict(width=2.3,color=palette[trace_index%len(palette)]),marker=dict(size=5),
                customdata=g[["Batch","Step status","Date time"]].astype(str).to_numpy(),
                hovertemplate=(f"Batch=%{{customdata[0]}}<br>Tag={tag}<br>Step=%{{customdata[1]}}<br>"
                               "Elapsed=%{x:.1f} min<br>Actual time=%{customdata[2]}<br>Value=%{y:.3f}<extra></extra>"),
            ))
            trace_index+=1

    axis_for_tag={tag:axis_for.get(sensor_family(tag),"y") for tag in tags}
    fig=add_target_step_highlight(
        fig,profile,tags,axis_for_tag,highlight_step,"Elapsed time (min)",
        highlight_color=highlight_color,band_opacity=highlight_opacity,
        show_band=show_highlight_band,
    )
    # Secondary top X-axis: actual date/time labels corresponding to elapsed-time positions.
    tick_source=(profile.sort_values("Elapsed time (min)")
                 .drop_duplicates("Elapsed time (min)"))
    if len(tick_source)>8:
        positions=[round(i*(len(tick_source)-1)/7) for i in range(8)]
        tick_source=tick_source.iloc[positions]
    tickvals=tick_source["Elapsed time (min)"].tolist()
    ticktext=[pd.to_datetime(x).strftime("%d-%m-%Y %H:%M") for x in tick_source["Date time"]]

    axis_layout={}
    for i,fam in enumerate(families):
        key="yaxis" if i==0 else f"yaxis{i+1}"
        axis_layout[key]=dict(title=fam,showgrid=(i==0),gridcolor="#E6E8EB",zeroline=False,fixedrange=False)
        family_tags=[tag for tag in tags if sensor_family(tag)==fam and tag in y_ranges]
        if family_tags:
            family_min=min(y_ranges[tag][0] for tag in family_tags)
            family_max=max(y_ranges[tag][1] for tag in family_tags)
            axis_layout[key]["range"]=[family_min,family_max]
        if i>0: axis_layout[key].update(overlaying="y",side="right",position=max(.78,1-(i-1)*.08))
    fig.update_layout(
        title=dict(text=title,x=.5,xanchor="center",font=dict(size=23)),height=760,
        template="plotly_white",hovermode="x unified",dragmode="zoom",margin=dict(l=85,r=190,t=145,b=140),
        legend=dict(orientation="h",x=.5,y=-.18,xanchor="center",yanchor="top",title="Batch | Sensor"),
        xaxis=dict(title="Elapsed time from sequence start (min)",showgrid=True,gridcolor="#EEF0F2",showspikes=True),
        xaxis2=dict(title="Actual date and time",overlaying="x",side="top",tickmode="array",tickvals=tickvals,ticktext=ticktext,showgrid=False),
        **axis_layout,
    )
    return fig

def build_single_sensor_profile(profile, tag, title=None, y_range=None, highlight_step=None, highlight_color="#FFC000", highlight_opacity=0.12, show_highlight_band=True):
    \"\"\"Plot one sensor from sequence start to end with process-step highlighting.\"\"\"
    if profile.empty or tag not in profile.columns:
        return go.Figure()
    d=profile.sort_values("Date time").copy()
    d["Elapsed time (min)"]=(d["Date time"]-d["Date time"].min()).dt.total_seconds()/60
    d=d.dropna(subset=[tag])
    if d.empty:
        return go.Figure()

    upper=str(tag).upper()
    if upper.startswith("LSICR"):
        unit="kg"; y_title=f"{tag} weight (kg)"
    elif upper.startswith(("TICR","TT-")):
        unit="°C"; y_title=f"{tag} temperature (°C)"
    elif upper.startswith(("PICR","PT-")):
        unit="bar"; y_title=f"{tag} pressure (bar)"
    else:
        unit=""; y_title=tag

    colors=px.colors.qualitative.Plotly
    fig=go.Figure()
    fig.add_trace(go.Scatter(
        x=d["Elapsed time (min)"],y=d[tag],mode="lines+markers",name=tag,
        line=dict(color="#315EFB",width=2.5),marker=dict(size=6,color="#315EFB"),
        customdata=d[["Batch","Step status"]].astype(str).to_numpy(),
        hovertemplate=f"Tag={tag}<br>Batch=%{{customdata[0]}}<br>Step=%{{customdata[1]}}<br>Time=%{{x|%d-%m-%Y %H:%M}}<br>Value=%{{y:.3f}} {unit}<extra></extra>",
    ))

    # Shade each contiguous process step from the first selected timestamp to the last.
    step_frame=profile[["Date time","Step status"]].drop_duplicates("Date time").sort_values("Date time").copy()
    gap=step_frame["Date time"].diff().dt.total_seconds().div(60)
    step_frame["_segment"]=(step_frame["Step status"].ne(step_frame["Step status"].shift())|gap.gt(5)).cumsum()
    step_colors=["#DDF3EF","#EEEAF6","#DCECF7","#E9F6CF","#F1F1F1","#E9F7EA","#FFF4BF","#FDE8E8"]
    status_order=[]
    for _,seg in step_frame.groupby("_segment",sort=True):
        status=str(seg["Step status"].iloc[0])
        if status not in status_order: status_order.append(status)
        color=step_colors[status_order.index(status)%len(step_colors)]
        x0=seg["Date time"].min(); x1=seg["Date time"].max()+pd.Timedelta(minutes=1)
        fig.add_vrect(x0=(x0-d["Date time"].min()).total_seconds()/60,x1=(x1-d["Date time"].min()).total_seconds()/60,fillcolor=color,opacity=0.55,line_width=0,layer="below")

    # Add process-status legend entries without adding another data plot.
    for i,status in enumerate(status_order):
        fig.add_trace(go.Scatter(
            x=[None],y=[None],mode="markers",name=status,legendgroup=f"status_{i}",
            marker=dict(size=14,symbol="square",color=step_colors[i%len(step_colors)]),hoverinfo="skip",
        ))

    fig=add_target_step_highlight(
        fig,d,[tag],{tag:"y"},highlight_step,"Elapsed time (min)",
        highlight_color=highlight_color,band_opacity=highlight_opacity,
        show_band=show_highlight_band,
    )
    tick_source=d.drop_duplicates("Elapsed time (min)").sort_values("Elapsed time (min)")
    if len(tick_source)>8:
        positions=[round(i*(len(tick_source)-1)/7) for i in range(8)]
        tick_source=tick_source.iloc[positions]
    tickvals=tick_source["Elapsed time (min)"].tolist()
    ticktext=[pd.to_datetime(x).strftime("%d-%m-%Y %H:%M") for x in tick_source["Date time"]]

    fig.update_layout(
        title=dict(text=title or f"{tag} Process Profile with Step Segmentation",x=0.5,xanchor="center",font=dict(size=23,color="#111111")),
        height=700,template="plotly_white",paper_bgcolor="white",plot_bgcolor="white",
        margin=dict(l=80,r=35,t=110,b=205),hovermode="x unified",dragmode="zoom",
        legend=dict(orientation="h",x=0.5,y=-0.27,xanchor="center",yanchor="top",title=dict(text="Process status"),font=dict(size=10)),
        xaxis=dict(
            title="Elapsed time from sequence start (min)",showgrid=True,gridcolor="#EEF0F2",
            rangeselector=dict(
                buttons=[
                    dict(count=10,label="10m",step="minute",stepmode="backward"),
                    dict(count=30,label="30m",step="minute",stepmode="backward"),
                    dict(count=1,label="1h",step="hour",stepmode="backward"),
                    dict(step="all",label="All"),
                ],x=0.0,y=1.10,
            ),
            showspikes=True,spikemode="across",spikesnap="cursor",spikethickness=1,
        ),
        xaxis2=dict(title="Actual date and time",overlaying="x",side="top",tickmode="array",tickvals=tickvals,ticktext=ticktext,showgrid=False),
        yaxis=dict(title=y_title,showgrid=True,gridcolor="#E6E8EB",zeroline=False,fixedrange=False,
                   showspikes=True,spikemode="across",spikesnap="cursor"),
    )
    if y_range is not None and y_range[1]>y_range[0]:
        fig.update_yaxes(range=[y_range[0],y_range[1]],autorange=False)
    return fig


def apply_plot_font_sizes(fig):
    \"\"\"Apply sidebar-selected font sizes to every Plotly chart.\"\"\"
    fig.update_layout(
        font=dict(size=plot_tick_font),
        title_font=dict(size=plot_title_font),
        legend=dict(font=dict(size=plot_legend_font),title_font=dict(size=plot_legend_font)),
        hoverlabel=dict(font_size=plot_hover_font),
    )
    fig.update_xaxes(title_font=dict(size=plot_axis_title_font),tickfont=dict(size=plot_tick_font))
    fig.update_yaxes(title_font=dict(size=plot_axis_title_font),tickfont=dict(size=plot_tick_font))
    return fig

def apply_editable_axis_titles(fig, plot_title, bottom_x_title, top_x_title, family_titles, legend_title=None):
    \"\"\"Apply user-entered titles to existing Plotly axes without changing data.\"\"\"
    fig.update_layout(title_text=plot_title)
    fig.update_xaxes(title_text=bottom_x_title, row=None, col=None)
    if "xaxis2" in fig.layout:
        fig.layout.xaxis2.title.text=top_x_title
    # Preserve axis-family order used by multi-sensor plots.
    existing_yaxes=[k for k in fig.layout if str(k).startswith("yaxis")]
    if legend_title is not None:
        fig.update_layout(legend_title_text=legend_title)
    for axis_name in existing_yaxes:
        axis=getattr(fig.layout,axis_name)
        old=(axis.title.text or "") if axis.title else ""
        if "Weight" in old:
            axis.title.text=family_titles.get("Weight (kg)",old)
        elif "Temperature" in old:
            axis.title.text=family_titles.get("Temperature (°C)",old)
        elif "Pressure" in old:
            axis.title.text=family_titles.get("Pressure (bar)",old)
    return fig

def show_plot_with_downloads(fig, chart_key, file_stem, height=None):
    \"\"\"Display a Plotly chart with browser-side PNG and HTML downloads.

    PNG uses Plotly's camera button in the chart toolbar. This runs in the
    user's browser and does not require Kaleido, Chrome, or server memory.
    \"\"\"
    if height:
        fig.update_layout(height=height)
    fig=apply_plot_font_sizes(fig)
    safe_name=re.sub(r"[^A-Za-z0-9_-]+", "_", str(file_stem)).strip("_") or "plot"
    
    # NEW CONFIG ADDITION: Interactive direct HTML editing for Title, Axes, and Legends
    plot_config={
        "editable": True,
        "edits": {
            "titleText": True,
            "axisTitleText": True,
            "legendText": True,
            "legendPosition": True,
            "annotationText": True,
            "colorbarTitleText": True
        },
        "displaylogo": False,
        "responsive": True,
        "scrollZoom": True,
        "doubleClick": "reset+autosize",
        "showTips": True,
        "modeBarButtonsToAdd": ["drawline","drawopenpath","drawrect","eraseshape","toggleSpikelines"],
        "toImageButtonOptions": {
            "format": "png",
            "filename": safe_name,
            "height": 1000,
            "width": 1800,
            "scale": 2,
        },
    }
    st.plotly_chart(fig, width="stretch", key=chart_key, config=plot_config)
    st.caption("Interactive: hover for values, drag to zoom, mouse wheel to zoom, double-click to reset. **Click on titles, axis labels, or legend names to edit them directly.** Camera icon downloads PNG.")
    html_bytes=fig.to_html(full_html=True, include_plotlyjs=True, config=plot_config).encode("utf-8")
    st.download_button(
        "Download interactive HTML",
        data=html_bytes,
        file_name=f"{safe_name}.html",
        mime="text/html",
        key=f"download_html_{chart_key}",
        width="stretch",
    )


def pdf_name_as_batch_number(file_name):
    return Path(str(file_name)).stem.strip() or "Unknown_Batch"

def dataframe_to_excel_bytes(df, sheet_name="Extracted Data"):
    output=BytesIO()
    with pd.ExcelWriter(output,engine="openpyxl") as writer:
        df.to_excel(writer,index=False,sheet_name=sheet_name[:31])
        ws=writer.book[sheet_name[:31]]
        ws.freeze_panes="A2"
        ws.auto_filter.ref=ws.dimensions
        for cell in ws[1]:
            cell.font=cell.font.copy(bold=True,color="FFFFFF")
            cell.fill=cell.fill.copy(fill_type="solid",fgColor="17365D")
        for column in ws.columns:
            letter=column[0].column_letter
            ws.column_dimensions[letter].width=min(55,max(12,max(len(str(c.value or "")) for c in column)+2))
    return output.getvalue()

def safe_table(df,height=650,max_rows=3000,key=None):
    df=df.copy()
    if isinstance(df.index,pd.MultiIndex):
        df=df.reset_index()
    if isinstance(df.columns,pd.MultiIndex):
        df.columns=[" | ".join(str(x) for x in col if str(x)!="") if isinstance(col,tuple) else str(col) for col in df.columns]
    total=len(df)
    if total>max_rows:
        st.caption(f"Displaying the first {max_rows:,} of {total:,} rows for browser stability. Calculations use all rows.")
        view=df.head(max_rows).copy().reset_index(drop=True)
    else:
        view=df.copy().reset_index(drop=True)
    for c in view.columns:
        if pd.api.types.is_datetime64_any_dtype(view[c]): view[c]=view[c].dt.strftime("%d/%m/%Y %H:%M:%S").fillna("")
        elif str(view[c].dtype) in ("object","category"): view[c]=view[c].astype(str).replace("nan","")
    st.dataframe(view,width="stretch",hide_index=True,height=height,row_height=31,key=key)


def apply_live_corrections(reports_list, corrections_df):
    \"\"\"Applies user corrections stored in session state directly to the parsed dataframes without needing to reprocess the PDF.\"\"\"
    if not reports_list or corrections_df.empty:
        return reports_list
    
    # We mutate the report dictionaries in place so it immediately updates the UI graphs and tables
    for r in reports_list:
        if r.get("error"):
            continue
            
        file_name = r["file_name"]
        file_corrections = corrections_df[corrections_df["Source report"] == file_name]
        
        if not file_corrections.empty and not r.get("long_df", pd.DataFrame()).empty:
            df = r["long_df"]
            
            if "OCR decimal repaired" not in df.columns:
                 df["OCR decimal repaired"] = False
                 df["OCR original value"] = df["Value"]
                 
            for _, corr_row in file_corrections.iterrows():
                mask = (df["Date time"] == corr_row["Date time"]) & (df["Instrument tag"] == corr_row["Instrument tag"])
                if mask.any():
                    df.loc[mask, "Value"] = float(corr_row["Corrected value"])
                    df.loc[mask, "OCR decimal repaired"] = True
                    
            r["long_df"] = df
            
            # Since the wide structure groups everything, we must also update `groups` to keep the UI in sync
            updated_groups = {}
            for g_name, g_df in r.get("groups", {}).items():
                 g_df = g_df.copy()
                 for _, corr_row in file_corrections.iterrows():
                     tag = corr_row["Instrument tag"]
                     if tag in g_df.columns:
                         time_mask = g_df["Date time"] == corr_row["Date time"]
                         if time_mask.any():
                             g_df.loc[time_mask, tag] = float(corr_row["Corrected value"])
                 updated_groups[g_name] = g_df
            r["groups"] = updated_groups
            
    return reports_list

# Initialize Session State for Manual Corrections
if "manual_corrections" not in st.session_state:
    st.session_state["manual_corrections"] = pd.DataFrame(columns=["Source report", "Instrument tag", "Date time", "Corrected value"])

st.title("Universal ADAM and OMCA ANFDA Multi-Report Extractor")
st.caption("Build: INTERACTIVE-MULTI-SENSOR-v36 | Live In-Memory Manual Corrections")
st.caption("Fast extraction uses Poppler pdftotext, then applies the selected ADAM or OMCA parser. Multiple reports are supported without automatic detection delay.")

# Add Manual Correction UI to sidebar
st.sidebar.subheader("Manual OCR Data Correction")
st.sidebar.caption("If a decimal point issue persists (e.g., 6.50 extracted as 650), you can manually fix it here. Select the report, tag, and time, then enter the correct value.")

# Display existing corrections
if not st.session_state["manual_corrections"].empty:
    with st.sidebar.expander("Active Manual Corrections"):
        st.dataframe(st.session_state["manual_corrections"], hide_index=True, use_container_width=True)
        if st.button("Clear All Corrections"):
            st.session_state["manual_corrections"] = pd.DataFrame(columns=["Source report", "Instrument tag", "Date time", "Corrected value"])
            st.rerun()

uploads=st.sidebar.file_uploader(
    "Upload multiple report PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    help="You can upload ADAM and OMCA ANFDA reports together."
)
if not uploads:
    st.info("Upload one or more supported PDFs. Report formats will be detected automatically.")
    st.stop()


if len(uploads)>10:
    st.error("Upload a maximum of 10 reports per processing run to avoid Streamlit Community Cloud memory exhaustion.")
    st.stop()
large=[f.name for f in uploads if f.size>50*1024*1024]
if large:
    st.error("Each PDF must be 50 MB or smaller: "+", ".join(large))
    st.stop()

st.sidebar.subheader("Processing control")
process_now=st.sidebar.button("Process uploaded reports",type="primary",width="stretch")
if not process_now and "processed_reports" not in st.session_state:
    st.info("Select each report type, then click **Process uploaded reports**. Processing will run once and results will remain in the session.")

st.sidebar.subheader("Select report type for each PDF")
report_type_by_file={}
for idx,uploaded in enumerate(uploads):
    filename=uploaded.name.lower()
    default_index=1 if any(x in filename for x in ["drying","trial batch","anfd-2","omca"]) else 0
    report_type_by_file[uploaded.name]=st.sidebar.selectbox(
        uploaded.name,
        ["ADAM Skid Process Report","OMCA ANFDA Drying Report","Legacy CV4/CV5 Process Report (OCR)"],
        index=default_index,
        key=f"report_type_{idx}_{uploaded.name}_{uploaded.size}",
        help="ADAM: Process Cycle reports with full date/time and multiple LSICR/PICR/TICR groups. OMCA ANFDA: ANFD-2 Drying reports with Record, Time, TT-01, TT-02, PT-01, Filter_Pos, Agit_Rpm and Agit_Pos."
    )

st.sidebar.subheader("Legacy OCR page range for each PDF")
legacy_page_range_by_file={}
for idx,uploaded in enumerate(uploads):
    if report_type_by_file.get(uploaded.name)=="Legacy CV4/CV5 Process Report (OCR)":
        st.sidebar.markdown(f"**{uploaded.name}**")
        page_col1,page_col2=st.sidebar.columns(2)
        with page_col1:
            first_page=st.number_input(
                "Start page",min_value=1,value=1,step=1,
                key=f"legacy_start_{idx}_{uploaded.name}_{uploaded.size}",
                help="Internal PDF start page for this report."
            )
        with page_col2:
            last_page=st.number_input(
                "End page",min_value=1,value=42,step=1,
                key=f"legacy_end_{idx}_{uploaded.name}_{uploaded.size}",
                help="Internal PDF end page for this report."
            )
        legacy_page_range_by_file[uploaded.name]=(int(first_page),int(last_page))
    else:
        legacy_page_range_by_file[uploaded.name]=(1,None)
        
@st.cache_data(show_spinner=False, max_entries=2, ttl=1800)
def process_uploaded_report(file_name, raw, selected_type, first_page=1, last_page=None, parser_version="legacy-cv-v6-low-cpu-step-correction"):
    if selected_type=="Legacy CV4/CV5 Process Report (OCR)":
        pages,extraction_engine,text_extraction_seconds=extract_pdf_pages_ocr(raw,first_page,last_page)
    else:
        pages,extraction_engine,text_extraction_seconds=extract_pdf_pages(raw)
    tag_inventory=scan_report_tag_headers(pages)
    detected_type=selected_type
    adam_score=0; omca_score=0
    meta=metadata_from_pages(pages)
    error=None
    groups={}; long_df=pd.DataFrame(); events=pd.DataFrame(); alarms=pd.DataFrame()
    if selected_type=="ADAM Skid Process Report":
        groups,long_df,events,alarms=parse_process_report(pages)
    elif selected_type=="OMCA ANFDA Drying Report":
        groups,long_df,events,alarms=parse_omca_anfd_report(pages)
    elif selected_type=="Legacy CV4/CV5 Process Report (OCR)":
        groups,long_df,events,alarms,tag_inventory=parse_legacy_cv_report(pages,int(first_page)-1)
        long_df=repair_missing_decimal_points(long_df, user_corrections=None) # Start fresh, apply corrections dynamically later
    else:
        error="Select a valid report type."
    if error is None and long_df.empty:
        error=("No requested CV4/CV5 data rows were parsed. Confirm the Legacy report type, page range, "
               "and that packages.txt contains poppler-utils, tesseract-ocr, and imagemagick.")
    meta["File name"]=file_name
    meta["Selected report type"]=selected_type
    meta["Text extraction engine"]=extraction_engine
    meta["Text extraction time (s)"]=round(text_extraction_seconds,2)
    if not long_df.empty and "Source report" not in long_df.columns:
        long_df.insert(0,"Source report",file_name)
    if not long_df.empty:
        long_df["Value"]=pd.to_numeric(long_df["Value"],errors="coerce",downcast="float")
        long_df["Source page"]=pd.to_numeric(long_df["Source page"],errors="coerce",downcast="integer")
        for c in ["Source report","Instrument tag","Unit","Step status","Instrument group"]:
            if c in long_df:
                long_df[c]=long_df[c].astype("string").fillna("")
    long_df=add_hmi_tag_names(long_df)
    if not tag_inventory.empty:
        extracted_counts=(long_df.groupby("Instrument tag",as_index=False).size().rename(columns={"size":"Extracted readings"}) if not long_df.empty else pd.DataFrame(columns=["Instrument tag","Extracted readings"]))
        tag_inventory=tag_inventory.merge(extracted_counts,left_on="Canonical tag",right_on="Instrument tag",how="left")
        tag_inventory["Extracted readings"]=tag_inventory["Extracted readings"].fillna(0).astype(int)
        tag_inventory["Extraction status"]=tag_inventory["Extracted readings"].gt(0).map({True:"Extracted",False:"Header found, no data rows parsed"})
        tag_inventory=tag_inventory.drop(columns=["Instrument tag"],errors="ignore")
    pages.clear()
    return {
        "file_name":file_name,"detected_type":detected_type,"tag_inventory":tag_inventory,
        "extraction_engine":extraction_engine,"text_extraction_seconds":text_extraction_seconds,
        "adam_score":adam_score,"omca_score":omca_score,
        "meta":meta,"groups":groups,"long_df":long_df,"events":events,"alarms":alarms,"error":error,
    }


if process_now:
    # Clear the old processed_reports from session to force a fresh dictionary layout
    if "processed_reports" in st.session_state:
        del st.session_state["processed_reports"]

if process_now or "processed_reports" not in st.session_state:
    raw_reports = []
    if process_now: progress=st.progress(0,text="Starting fast report processing...")
    for i,uploaded in enumerate(uploads):
        selected_type=report_type_by_file[uploaded.name]
        if process_now: progress.progress(i/len(uploads),text=f"Extracting {uploaded.name} as {selected_type} ({i+1} of {len(uploads)})")
        try:
            first_page,last_page=legacy_page_range_by_file.get(uploaded.name,(1,None))
            if selected_type=="Legacy CV4/CV5 Process Report (OCR)" and last_page is not None and last_page<first_page:
                raise ValueError(f"End page ({last_page}) must be greater than or equal to start page ({first_page}) for {uploaded.name}.")
            # Call without manual corrections to leverage cache
            raw_reports.append(process_uploaded_report(uploaded.name,uploaded.getvalue(),selected_type,first_page,last_page,"legacy-cv-v7-per-file-page-range"))
        except Exception as exc:
            raw_reports.append({"file_name":uploaded.name,"detected_type":"Failed","error":f"{type(exc).__name__}: {exc}","long_df":pd.DataFrame(),"events":pd.DataFrame(),"alarms":pd.DataFrame(),"groups":{},"meta":{"File name":uploaded.name},"adam_score":0,"omca_score":0})
        gc.collect()
    if process_now: progress.progress(1.0,text=f"Processed {len(uploads)} report(s)")
    st.session_state["processed_reports"] = raw_reports
    
# Always apply live manual corrections dynamically to the session data without retriggering the heavy cache function
reports = apply_live_corrections(st.session_state["processed_reports"], st.session_state["manual_corrections"])


summary_rows=[]
for r in reports:
    d=r.get("long_df",pd.DataFrame())
    summary_rows.append({
        "File name":r["file_name"],"Selected report type":r.get("detected_type","Unknown"),
        "Instrument tags":d["Instrument tag"].nunique() if not d.empty else 0,
        "Header tags":r.get("tag_inventory",pd.DataFrame()).get("Canonical tag",pd.Series(dtype=str)).nunique(),
        "Header tags missing data":int((r.get("tag_inventory",pd.DataFrame()).get("Extracted readings",pd.Series(dtype=int))==0).sum()),
        "Tagwise readings":len(d),"Events":len(r.get("events",pd.DataFrame())),
        "Alarms":len(r.get("alarms",pd.DataFrame())),"Text engine":r.get("extraction_engine",""),
        "Text extraction (s)":round(r.get("text_extraction_seconds",0),2),
        "Status":"Error" if r.get("error") else "Processed",
        "Message":r.get("error") or "",
    })
summary_df=pd.DataFrame(summary_rows)
st.subheader("Batch processing summary")
safe_table(summary_df,height=min(520,110+len(summary_df)*38))

valid=[r for r in reports if not r.get("error") and not r.get("long_df",pd.DataFrame()).empty]
for item in valid:
    item_batch=pdf_name_as_batch_number(item.get("file_name",""))
    item.setdefault("meta",{})["Batch number"]=item_batch
    item["long_df"]=item["long_df"].copy()
    item["long_df"]["Batch number"]=item_batch
if not valid:
    st.error("None of the uploaded reports could be processed. Review the summary messages.")
    st.stop()

report_names=[r["file_name"] for r in valid]
active_name=st.sidebar.selectbox("Active report",report_names)
batch_number=pdf_name_as_batch_number(active_name)
r=next(x for x in valid if x["file_name"]==active_name)
long_df=r["long_df"].copy()
long_df["Batch number"]=batch_number
long_df=long_df[["Batch number"]+[c for c in long_df.columns if c!="Batch number"]]
groups=r["groups"]; events=r["events"]; alarms=r["alarms"]; meta=r["meta"]; tag_inventory=r.get("tag_inventory",pd.DataFrame())
flow_smoothing=st.sidebar.select_slider("Flowrate weight smoothing points",options=[1,3,5,7],value=3,key=f"flow_smoothing_{active_name}")
flow_points=calculate_interval_flowrates(long_df,flow_smoothing)
st.sidebar.success(f"Processing as: {r['detected_type']}")

combine_same_type=st.sidebar.checkbox("Combine all processed reports",value=False)
if combine_same_type:
    option_parts=[item["long_df"][["Instrument tag","HMI display label"]].drop_duplicates() for item in valid]
    combined_options=pd.concat(option_parts,ignore_index=True).drop_duplicates().sort_values("Instrument tag")
    combined_label=st.selectbox("Combined instrument tag",combined_options["HMI display label"].tolist(),key="combined_tag")
    combined_tag=combined_options.loc[combined_options["HMI display label"]==combined_label,"Instrument tag"].iloc[0]
    selected_parts=[]
    for item in valid:
        part=item["long_df"]
        part=part[part["Instrument tag"].astype(str)==str(combined_tag)].copy()
        if not part.empty:
            part["Source report"]=item["file_name"]
            part["Report type"]=item["detected_type"]
            selected_parts.append(part)
    combined_view=pd.concat(selected_parts,ignore_index=True).sort_values(["Source report","Date time"]) if selected_parts else pd.DataFrame()
    st.subheader("Combined selected-tag data across uploaded reports")
    st.caption(f"{len(valid)} processed reports | {len(combined_view):,} matching readings")
    safe_table(combined_view,height=650,max_rows=3000,key="combined_table")
    del selected_parts, combined_view
    st.divider()

st.subheader(f"Active report: {active_name}")
status_numeric_prefix=int(long_df["Step status"].astype(str).str.match(r"^[-+]?\d").sum()) if not long_df.empty else 0
q1,q2,q3=st.columns(3)
q1.metric("Extracted instrument tags",long_df["Instrument tag"].nunique())
q2.metric("Unique step statuses",long_df["Step status"].nunique())
q3.metric("Numeric-prefix status rows",status_numeric_prefix)
if status_numeric_prefix:
    st.warning("Some status rows still start with numeric values. Clear the application cache and process the report again with this corrected parser.")
# Keep the six legacy CV tags visible in the sensor selector, even when the active page range contains only CV4 or CV5.
LEGACY_CV_SELECTOR_TAGS=["CV4WICR-01","CV4TT-01","CV4PT-01","CV5WICR-01","CV5TT-01","CV5PT-01"]
present_options=long_df[["Instrument tag","HMI display label"]].drop_duplicates()
selector_rows=[]
for selector_tag in LEGACY_CV_SELECTOR_TAGS:
    equipment,measurement,unit=HMI_TAG_MAP.get(selector_tag,("","",""))
    selector_rows.append({"Instrument tag":selector_tag,"HMI display label":f"{selector_tag} | {equipment} | {measurement}"})
master_options=pd.DataFrame(selector_rows)
tag_options=pd.concat([present_options,master_options],ignore_index=True).drop_duplicates("Instrument tag",keep="first").sort_values("Instrument tag")
tags=present_options["Instrument tag"].drop_duplicates().sort_values().tolist()
selected_label=st.sidebar.selectbox("Instrument tag / HMI name",tag_options["HMI display label"].tolist(),key=f"tag_select_{active_name}")
selected_tag=tag_options.loc[tag_options["HMI display label"]==selected_label,"Instrument tag"].iloc[0]
tag_available=selected_tag in set(long_df["Instrument tag"].astype(str))
tag_df=long_df[long_df["Instrument tag"]==selected_tag].sort_values("Date time")
if not tag_available:
    st.sidebar.warning(f"{selected_tag} is available in the sensor list but has no extracted readings in the active PDF page range.")
statuses=sorted(x for x in tag_df["Step status"].dropna().astype(str).unique() if x.strip())
chosen=st.sidebar.multiselect(
    "Optional step-status filter",
    statuses,
    default=[],
    key=f"status_filter_{active_name}_{selected_tag}",
    help="Leave empty to display all step statuses. Select values only when you want to filter."
)
if chosen:
    tag_df=tag_df[tag_df["Step status"].astype(str).isin(chosen)]

m1,m2,m3,m4=st.columns(4)
m1.metric("Uploaded reports",len(uploads)); m2.metric("Processed reports",len(valid))
m3.metric("Active report tags",len(tags)); m4.metric("Active tag readings",f"{len(tag_df):,}")

summary=(long_df.groupby(["Instrument tag","HMI equipment","HMI measurement name","Unit"],dropna=False,observed=True,as_index=False)
    .agg(Records=("Value","size"),Start=("Date time","min"),End=("Date time","max"),Minimum=("Value","min"),Maximum=("Value","max"),Mean=("Value","mean")))

# Validate only the CV sensor family applicable to the active report. Page
# ranges are now stored per uploaded PDF, so the removed global
# legacy_first_page variable must not be referenced here.
found_tags=set(long_df.get("Instrument tag",pd.Series(dtype=str)).astype(str).unique())
active_first_page,active_last_page=legacy_page_range_by_file.get(active_name,(1,None))
cv4_expected={"CV4WICR-01","CV4TT-01","CV4PT-01"}
cv5_expected={"CV5WICR-01","CV5TT-01","CV5PT-01"}
if found_tags & cv4_expected:
    expected_tags=cv4_expected
elif found_tags & cv5_expected:
    expected_tags=cv5_expected
else:
    expected_tags=set()
missing_expected=sorted(expected_tags-found_tags)
if missing_expected:
    st.error("Extraction integrity check failed for "+active_name+" (pages "+str(active_first_page)+"-"+str(active_last_page)+"). Missing expected tags: "+", ".join(missing_expected)+". Clear cache and reprocess this PDF.")
elif expected_tags:
    st.success(f"Extraction integrity check passed for {active_name}: {len(long_df):,} tag-wise rows across {len(found_tags)} extracted tags.")
else:
    st.info(f"No CV4/CV5 integrity-tag family was detected in {active_name}; the extracted data remains available for review.")

tabs=st.tabs(["Selected tag","Tag summary", "Cross-batch profiles","Extraction audit","Transfer flowrate","HMI tag dictionary","Instrument groups","All tagwise data","Events & alarms","Metadata"])
with tabs[0]:
    if tag_df.empty:
        equipment,measurement,unit_hint=HMI_TAG_MAP.get(selected_tag,("","",""))
        st.info(f"{selected_tag} is included in the sensor dropdown, but no readings were extracted for this tag from the active page range. Select the corresponding CV4 or CV5 page range and reprocess the PDF.")
    selected_equipment=tag_df["HMI equipment"].iloc[0] if not tag_df.empty else HMI_TAG_MAP.get(selected_tag,("","",""))[0]
    selected_measurement=tag_df["HMI measurement name"].iloc[0] if not tag_df.empty else HMI_TAG_MAP.get(selected_tag,("","",""))[1]
    st.subheader(f"{selected_tag}: {selected_measurement}")
    st.caption(f"HMI equipment: {selected_equipment}")
    unit=tag_df["Unit"].dropna().astype(str).replace("",pd.NA).dropna().iloc[0] if tag_df["Unit"].astype(str).str.len().gt(0).any() else ""
    plot_df=tag_df.iloc[::max(1,len(tag_df)//3000)]
    fig=px.line(plot_df,x="Date time",y="Value",title=f"{selected_tag} trend",labels={"Value":f"Value ({unit})" if unit else "Value"})
    show_plot_with_downloads(
        fig,
        chart_key=f"selected_tag_plot_{active_name}_{selected_tag}",
        file_stem=f"{active_name}_{selected_tag}_trend",
    )
    safe_table(tag_df[["Date time","Instrument tag","HMI equipment","HMI measurement name","Value","Unit","Step status","Source page"]],max_rows=max(3000,len(tag_df)),key="selected_tag_complete")
with tabs[1]:
    safe_table(summary,height=600)
with tabs[2]:
    st.subheader("Interactive Sensor Profiles with Step Segmentation")
    st.caption("Select one or multiple batches. Single-batch plots retain process-step shading. Multiple-batch plots align each selected sequence at elapsed time zero for direct comparison.")
    cross_wide=build_cross_batch_wide(valid)
    if cross_wide.empty:
        st.info("Process at least one ADAM Process report to create sensor profiles.")
    else:
        # ---- UI Addition: Manual Form entry in Profile Tab ----
        with st.expander("🛠️ Add Manual OCR Correction", expanded=False):
            st.markdown("If you notice a spike/drop caused by OCR missing a decimal point (e.g. 6.50 extracted as 650), manually correct it here.")
            corr_col1, corr_col2, corr_col3 = st.columns(3)
            with corr_col1:
                man_report = st.selectbox("Source Report", report_names, key="man_corr_report")
            with corr_col2:
                available_tags = []
                # Fetch available tags for the selected report
                if not cross_wide.empty:
                    available_tags = cross_wide[cross_wide["Source report"] == man_report].columns.drop(["Source report", "Batch", "Date time", "Step status"], errors='ignore').tolist()
                man_tag = st.selectbox("Instrument Tag", sorted(available_tags) if available_tags else [selected_tag], key="man_corr_tag")
            with corr_col3:
                # Provide an initial value to the time input to avoid empty errors
                available_times = []
                if not cross_wide.empty and man_tag:
                   rep_data = cross_wide[cross_wide["Source report"] == man_report]
                   available_times = rep_data["Date time"].dt.strftime("%d-%m-%Y %H:%M:%S").tolist()
                   
                man_time = st.selectbox("Select exact Timestamp", available_times, key="man_corr_time")
            
            man_val = st.number_input("Corrected Value", format="%.3f", key="man_corr_val")
            if st.button("Apply Correction", type="primary"):
                try:
                    parsed_time = pd.to_datetime(man_time, format="%d-%m-%Y %H:%M:%S")
                    new_correction = pd.DataFrame([{
                        "Source report": man_report,
                        "Instrument tag": man_tag,
                        "Date time": parsed_time,
                        "Corrected value": man_val
                    }])
                    st.session_state["manual_corrections"] = pd.concat([st.session_state["manual_corrections"], new_correction], ignore_index=True)
                    st.success("Correction saved and applied to charts below!")
                    st.rerun() # Immediately rerun to apply the correction in memory
                except Exception as e:
                    st.error(f"Failed to add correction: {e}")
        st.divider()
        # ---- End of manual form ----

        available_batches=sorted(x for x in cross_wide["Batch"].dropna().astype(str).unique() if x.strip())
        selected_batches=st.multiselect(
            "Batch numbers",
            available_batches,
            default=available_batches[:1],
            key="sensor_batches_v9",
        )
        if not selected_batches:
            st.info("Select at least one batch number.")
            st.stop()
        selected_data=cross_wide[cross_wide["Batch"].astype(str).isin(selected_batches)].copy()
        all_steps=[]
        for value in selected_data.sort_values("Date time")["Step status"].dropna().astype(str):
            if value.strip() and value not in all_steps: all_steps.append(value)
        preferred_start="TRANSFER FROM MV01 TO MV04"; preferred_end="TRANSFER FROM SFV01 TO MV04"
        c_start,c_end,c_duration=st.columns([2,2,1])
        with c_start:
            start_step=st.selectbox("Sequence start step",all_steps,index=all_steps.index(preferred_start) if preferred_start in all_steps else 0,key="multi_batch_start_v9")
        with c_end:
            end_step=st.selectbox("Sequence end step",all_steps,index=all_steps.index(preferred_end) if preferred_end in all_steps else max(0,len(all_steps)-1),key="multi_batch_end_v9")
        with c_duration:
            max_duration=st.number_input("Max duration (min)",10,2880,1440,10,key="multi_batch_duration_v10",
                help="Maximum allowed time from the beginning of the selected start step to the end of the selected end step. Use 1440 for a 24-hour process.")

        sequence_parts=[]; sequence_rows=[]
        for batch_name in selected_batches:
            batch_data=selected_data[selected_data["Batch"].astype(str)==str(batch_name)].sort_values("Date time").copy()
            matches=identify_process_sequences(batch_data,start_step,end_step,max_duration)
            if not matches:
                start_times=batch_data.loc[batch_data["Step status"].astype(str).map(normalize_step_name)==normalize_step_name(start_step),"Date time"]
                end_times=batch_data.loc[batch_data["Step status"].astype(str).map(normalize_step_name)==normalize_step_name(end_step),"Date time"]
                detail="Start or end step is absent"
                if not start_times.empty and not end_times.empty:
                    later_ends=end_times[end_times>=start_times.min()]
                    if later_ends.empty:
                        detail="The selected end step occurs before the selected start step"
                    else:
                        required=(later_ends.min()-start_times.min()).total_seconds()/60
                        detail=f"Required duration is approximately {required:.0f} min; selected limit is {max_duration} min"
                sequence_rows.append({"Batch":batch_name,"Status":"No matching sequence","Reason":detail})
                continue
            best=max(matches,key=lambda x:(x.get("gain",0),-x.get("duration",999999)))
            part=best["data"].copy().sort_values("Date time")
            part["Elapsed time (min)"]=(part["Date time"]-part["Date time"].min()).dt.total_seconds()/60
            sequence_parts.append(part)
            sequence_rows.append({"Batch":batch_name,"Status":"Included","Sequence":best["label"]})
        if not sequence_parts:
            st.warning("No matching process sequence was found for the selected batches.")
            safe_table(pd.DataFrame(sequence_rows),height=300)
            st.stop()
        chronological=pd.concat(sequence_parts,ignore_index=True,sort=False)
        with st.expander("Sequence selected for each batch"):
            safe_table(pd.DataFrame(sequence_rows),height=300)

        st.markdown("#### Highlight a process step in the profile")
        available_highlight_steps=[]
        for step_value in chronological["Step status"].dropna().astype(str):
            if step_value.strip() and step_value not in available_highlight_steps:
                available_highlight_steps.append(step_value)
        preferred_highlight="TRANSFER FROM SFV01 TO MV04"
        preferred_norm=normalize_step_name(preferred_highlight)
        default_highlight_index=0
        for step_index,step_value in enumerate(available_highlight_steps):
            if normalize_step_name(step_value)==preferred_norm:
                default_highlight_index=step_index
                break
        highlight_enabled=st.checkbox(
            "Highlight selected process step",
            value=True,
            key="highlight_process_step_v17",
        )
        highlight_c1,highlight_c2,highlight_c3=st.columns([2.4,1,1])
        with highlight_c1:
            highlight_step=st.selectbox(
                "Process step to highlight",
                available_highlight_steps,
                index=default_highlight_index,
                key="highlight_step_name_v17",
                help="The default selection is TRANSFER FROM SFV01 TO MV04 when that step exists in the report.",
            ) if available_highlight_steps else None
        with highlight_c2:
            highlight_color=st.color_picker(
                "Highlight color",
                value="#FFC000",
                key="highlight_step_color_v17",
            )
        with highlight_c3:
            highlight_opacity=st.slider(
                "Band opacity",
                min_value=0.03,
                max_value=0.35,
                value=0.12,
                step=0.01,
                key="highlight_step_opacity_v17",
            )
        show_highlight_band=st.checkbox(
            "Show vertical shaded band in addition to the bold highlighted line",
            value=True,
            key="highlight_step_band_v17",
        )
        effective_highlight_step=highlight_step if highlight_enabled else None

        # Classify all available columns, including Legacy CV4/CV5 tag names.
        columns=[str(c).strip() for c in chronological.columns]
        def profile_sensor_family(tag):
            upper=str(tag).upper().strip()
            compact=re.sub(r"[^A-Z0-9]","",upper)
            if upper.startswith("LSICR") or "WICR" in upper or compact.startswith(("CV4WICR","CV5WICR")):
                return "loadcell"
            if upper.startswith(("TICR","TT-")) or re.search(r"CV[45]TT0*1$",compact):
                return "temperature"
            if upper.startswith(("PICR","PT-")) or re.search(r"CV[45]PT0*1$",compact):
                return "pressure"
            return "other"
        temperature_tags=sorted(c for c in columns if profile_sensor_family(c)=="temperature")
        pressure_tags=sorted(c for c in columns if profile_sensor_family(c)=="pressure")
        loadcell_tags=sorted(c for c in columns if profile_sensor_family(c)=="loadcell")
        c1,c2,c3=st.columns(3)
        sensor_key_suffix=re.sub(r"[^A-Za-z0-9]+","_",str(active_name))
        with c1:
            selected_temp=st.multiselect("Temperature sensors",temperature_tags,default=[x for x in ["TICR008","CV4TT-01","CV5TT-01"] if x in temperature_tags],key=f"multi_batch_temp_v32_{sensor_key_suffix}")
        with c2:
            selected_pressure=st.multiselect("Pressure sensors",pressure_tags,default=[x for x in ["PICR006","CV4PT-01","CV5PT-01"] if x in pressure_tags],key=f"multi_batch_pressure_v32_{sensor_key_suffix}")
        with c3:
            selected_load=st.multiselect("Load-cell sensors",loadcell_tags,default=[x for x in ["LSICR004","LSICR005","CV4WICR-01","CV5WICR-01"] if x in loadcell_tags],key=f"multi_batch_load_v32_{sensor_key_suffix}")
        selected_tags=list(dict.fromkeys(selected_load+selected_pressure+selected_temp))[:12]

        st.markdown("#### Editable plot and axis titles")
        title_c1,title_c2,title_c3=st.columns(3)
        with title_c1:
            custom_plot_title=st.text_input(
                "Plot title",
                value="Process Profile with Step Segmentation",
                key="custom_plot_title_v14",
            )
        with title_c2:
            custom_x_title=st.text_input(
                "Bottom X-axis title",
                value="Elapsed time from sequence start (min)",
                key="custom_x_title_v14",
            )
        with title_c3:
            custom_top_x_title=st.text_input(
                "Top X-axis title",
                value="Actual date and time",
                key="custom_top_x_title_v14",
            )
        ytitle_c1,ytitle_c2,ytitle_c3=st.columns(3)
        with ytitle_c1:
            custom_weight_y_title=st.text_input("Weight Y-axis title",value="Weight (kg)",key="custom_weight_y_title_v14")
        with ytitle_c2:
            custom_temperature_y_title=st.text_input("Temperature Y-axis title",value="Temperature (°C)",key="custom_temperature_y_title_v14")
        with ytitle_c3:
            custom_pressure_y_title=st.text_input("Pressure Y-axis title",value="Pressure (bar)",key="custom_pressure_y_title_v14")
        custom_axis_titles={
            "Weight (kg)":custom_weight_y_title,
            "Temperature (°C)":custom_temperature_y_title,
            "Pressure (bar)":custom_pressure_y_title,
        }
        st.markdown("##### Individual and comparison chart titles")
        editable_c1,editable_c2=st.columns(2)
        with editable_c1:
            custom_multi_sensor_title=st.text_input(
                "Multi-sensor chart title",
                value=custom_plot_title,
                key="custom_multi_sensor_title_v15",
            )
            custom_cross_batch_title=st.text_input(
                "Cross-batch chart title",
                value="Cross-Batch Process Profile",
                key="custom_cross_batch_title_v15",
            )
        with editable_c2:
            custom_individual_title_template=st.text_input(
                "Individual-sensor title template",
                value="{tag} Process Profile",
                key="custom_individual_title_template_v15",
                help="Use {tag} where the sensor tag should appear.",
            )
            custom_flowrate_title=st.text_input(
                "Flowrate chart title",
                value="Interval Material-Transfer Flowrate",
                key="custom_flowrate_title_v15",
            )
            custom_profile_legend_title=st.text_input(
                "Profile legend title",
                value="Batch | Sensor | Process status",
                key="custom_profile_legend_title_v16",
            )
        flow_label_c1,flow_label_c2,flow_label_c3=st.columns(3)
        with flow_label_c1:
            custom_flowrate_x_title=st.text_input(
                "Flowrate X-axis title",
                value="Date time",
                key="custom_flowrate_x_title_v16",
            )
        with flow_label_c2:
            custom_flowrate_y_title=st.text_input(
                "Flowrate Y-axis title",
                value="Flowrate (kg/min)",
                key="custom_flowrate_y_title_v16",
            )
        with flow_label_c3:
            custom_flowrate_legend_title=st.text_input(
                "Flowrate legend title",
                value="Transfer direction",
                key="custom_flowrate_legend_title_v16",
            )

        st.markdown("#### Manual Y-axis limits")
        manual_y_axis=st.checkbox(
            "Set Y-axis minimum and maximum manually",
            value=False,
            key="manual_y_axis_v12",
        )
        y_axis_ranges={}
        if manual_y_axis and selected_tags:
            for axis_tag in selected_tags:
                numeric_values=pd.to_numeric(chronological[axis_tag],errors="coerce").dropna() if axis_tag in chronological.columns else pd.Series(dtype=float)
                if numeric_values.empty:
                    continue
                observed_min=float(numeric_values.min())
                observed_max=float(numeric_values.max())
                span=max(observed_max-observed_min,abs(observed_max)*0.05,1.0)
                default_min=observed_min-0.05*span
                default_max=observed_max+0.05*span
                yc1,yc2,yc3=st.columns([1.2,1,1])
                with yc1:
                    st.write(f"**{axis_tag}**  \nObserved: {observed_min:.3f} to {observed_max:.3f}")
                with yc2:
                    selected_y_min=st.number_input(
                        f"{axis_tag} minimum",
                        value=float(default_min),
                        format="%.3f",
                        key=f"y_min_{axis_tag}_v12",
                    )
                with yc3:
                    selected_y_max=st.number_input(
                        f"{axis_tag} maximum",
                        value=float(default_max),
                        format="%.3f",
                        key=f"y_max_{axis_tag}_v12",
                    )
                if selected_y_max<=selected_y_min:
                    st.warning(f"{axis_tag}: maximum must be greater than minimum. Automatic scaling will be used for this tag.")
                else:
                    y_axis_ranges[axis_tag]=(float(selected_y_min),float(selected_y_max))

        plot_mode=st.radio("Plot mode",["Multiple selected sensors in one plot","Individual plot for each sensor"],horizontal=True,key="multi_batch_plot_mode_v9")
        if not selected_tags:
            st.info("Select at least one sensor.")
        elif len(selected_batches)>1:
            if plot_mode.startswith("Multiple"):
                fig=build_cross_batch_sensor_profile(
                    chronological,selected_tags,custom_cross_batch_title,y_ranges=y_axis_ranges,
                    highlight_step=effective_highlight_step,highlight_color=highlight_color,
                    highlight_opacity=highlight_opacity,show_highlight_band=show_highlight_band,
                )
                fig=apply_editable_axis_titles(fig,custom_cross_batch_title,custom_x_title,custom_top_x_title,custom_axis_titles,custom_profile_legend_title)
                show_plot_with_downloads(fig,"cross_batch_multi_v9",f"{'_'.join(selected_batches)}_multi_sensor",740)
            else:
                for tag in selected_tags:
                    individual_title=custom_individual_title_template.replace("{tag}",str(tag))
                    fig=build_cross_batch_sensor_profile(
                        chronological,[tag],individual_title,y_ranges=y_axis_ranges,
                        highlight_step=effective_highlight_step,highlight_color=highlight_color,
                        highlight_opacity=highlight_opacity,show_highlight_band=show_highlight_band,
                    )
                    fig=apply_editable_axis_titles(fig,individual_title,custom_x_title,custom_top_x_title,custom_axis_titles,custom_profile_legend_title)
                    show_plot_with_downloads(fig,f"cross_batch_{tag}_v9",f"{'_'.join(selected_batches)}_{tag}",700)
        else:
            one=chronological[chronological["Batch"].astype(str)==selected_batches[0]].copy()
            if plot_mode.startswith("Multiple"):
                fig=build_multi_sensor_profile(
                    one,selected_tags,custom_multi_sensor_title,y_ranges=y_axis_ranges,
                    highlight_step=effective_highlight_step,highlight_color=highlight_color,
                    highlight_opacity=highlight_opacity,show_highlight_band=show_highlight_band,
                )
                fig=apply_editable_axis_titles(fig,custom_multi_sensor_title,custom_x_title,custom_top_x_title,custom_axis_titles,custom_profile_legend_title)
                show_plot_with_downloads(fig,"single_batch_multi_v9",f"{selected_batches[0]}_multi_sensor",740)
            else:
                for tag in selected_tags:
                    individual_title=custom_individual_title_template.replace("{tag}",str(tag))
                    fig=build_single_sensor_profile(
                        one,tag,individual_title,y_range=y_axis_ranges.get(tag),
                        highlight_step=effective_highlight_step,highlight_color=highlight_color,
                        highlight_opacity=highlight_opacity,show_highlight_band=show_highlight_band,
                    )
                    fig=apply_editable_axis_titles(fig,individual_title,custom_x_title,custom_top_x_title,custom_axis_titles,custom_profile_legend_title)
                    show_plot_with_downloads(fig,f"single_batch_{tag}_v9",f"{selected_batches[0]}_{tag}",700)
        display_columns=["Source report","Batch","Date time","Elapsed time (min)","Step status"]+selected_tags
        safe_table(chronological[display_columns],height=650,max_rows=max(3000,len(chronological)),key="multi_batch_profile_table_v9")

        st.divider()
        st.subheader("Temperature Statistical Analysis by Batch and Process Step")
        st.caption("For each selected temperature sensor and process step, the app calculates count, minimum, maximum, mean, sample standard deviation, range, and %RSD using the selected start-to-end process sequence.")

        available_stat_batches=sorted(chronological["Batch"].dropna().astype(str).unique())
        available_stat_temp_tags=sorted(
            c for c in chronological.columns
            if str(c).upper().startswith(("TICR","TT-"))
        )
        stat_col1,stat_col2=st.columns(2)
        with stat_col1:
            stat_batches=st.multiselect(
                "Batches for temperature statistics",
                available_stat_batches,
                default=available_stat_batches,
                key="temperature_stats_batches_v10",
            )
        with stat_col2:
            # Use the temperature tags selected in the profile controls.
            default_stat_tags=[
                x for x in selected_temp
                if x in available_stat_temp_tags
            ]
            stat_temp_tags=st.multiselect(
                "Temperature sensor tags for statistics",
                available_stat_temp_tags,
                default=default_stat_tags or available_stat_temp_tags[:1],
                key="temperature_stats_tags_v10",
            )

        available_stat_steps=sorted(
            x for x in chronological["Step status"].dropna().astype(str).unique()
            if x.strip()
        )
        stat_steps=st.multiselect(
            "Process steps for statistics",
            available_stat_steps,
            default=available_stat_steps,
            key="temperature_stats_steps_v10",
        )

        statistic_frames=[]
        statistics_source=chronological[
            chronological["Batch"].astype(str).isin(stat_batches)
            & chronological["Step status"].astype(str).isin(stat_steps)
        ].copy()
        for temperature_tag in stat_temp_tags:
            if temperature_tag not in statistics_source.columns:
                continue
            part=statistics_source[["Batch","Step status",temperature_tag]].copy()
            part[temperature_tag]=pd.to_numeric(part[temperature_tag],errors="coerce")
            part=part.dropna(subset=[temperature_tag])
            if part.empty:
                continue
            tag_stats=(
                part.groupby(["Batch","Step status"],dropna=False,observed=True)[temperature_tag]
                .agg(
                    Count="count",
                    Minimum="min",
                    Maximum="max",
                    Mean="mean",
                    Standard_deviation="std",
                )
                .reset_index()
            )
            tag_stats.insert(2,"Temperature sensor",temperature_tag)
            tag_stats["Range"]=tag_stats["Maximum"]-tag_stats["Minimum"]
            tag_stats["%RSD"]=tag_stats["Standard_deviation"].div(tag_stats["Mean"].abs()).mul(100)
            statistic_frames.append(tag_stats)

        if not statistic_frames:
            st.info("No temperature data are available for the selected batches, sensor tags, and process steps.")
        else:
            temperature_statistics=pd.concat(statistic_frames,ignore_index=True)
            numeric_columns=["Minimum","Maximum","Mean","Standard_deviation","Range","%RSD"]
            temperature_statistics[numeric_columns]=temperature_statistics[numeric_columns].round(3)
            temperature_statistics=temperature_statistics.sort_values(
                ["Batch","Temperature sensor","Step status"],kind="stable"
            )
            stat_m1,stat_m2,stat_m3,stat_m4=st.columns(4)
            stat_m1.metric("Batches",temperature_statistics["Batch"].nunique())
            stat_m2.metric("Temperature sensors",temperature_statistics["Temperature sensor"].nunique())
            stat_m3.metric("Process steps",temperature_statistics["Step status"].nunique())
            stat_m4.metric("Statistical rows",len(temperature_statistics))
            st.markdown("#### Graphical temperature-statistics analysis")
            statistic_metric=st.selectbox(
                "Statistic to graph",
                ["Mean","Minimum","Maximum","Standard_deviation","Range","%RSD"],
                key="temperature_statistic_metric_v14",
            )
            statistic_chart_type=st.radio(
                "Statistical plot type",
                ["Mean with minimum-maximum band","Grouped bar chart","Heatmap"],
                horizontal=True,
                key="temperature_statistic_chart_type_v14",
            )
            statistics_plot_title=st.text_input(
                "Statistical plot title",
                value="Temperature Statistics Across Process Steps",
                key="temperature_statistics_title_v14",
            )
            stats_title_c1,stats_title_c2=st.columns(2)
            with stats_title_c1:
                statistics_x_title=st.text_input(
                    "Statistical X-axis title",
                    value="Process step",
                    key="temperature_statistics_x_title_v15",
                )
            with stats_title_c2:
                statistics_y_title=st.text_input(
                    "Statistical Y-axis title",
                    value="Temperature (°C)",
                    key="temperature_statistics_y_title_v15",
                )
            statistics_legend_title=st.text_input(
                "Statistical legend / color-scale title",
                value="Batch | Sensor",
                key="temperature_statistics_legend_title_v16",
            )

            if statistic_chart_type=="Mean with minimum-maximum band":
                stats_fig=go.Figure()
                palette=px.colors.qualitative.Plotly+px.colors.qualitative.Safe
                for profile_i,((batch_name,sensor_tag),group) in enumerate(
                    temperature_statistics.groupby(["Batch","Temperature sensor"],sort=False)
                ):
                    color=palette[profile_i%len(palette)]
                    label=f"{batch_name} | {sensor_tag}"
                    group=group.copy()
                    stats_fig.add_trace(go.Scatter(
                        x=group["Step status"],y=group["Maximum"],mode="lines",
                        line=dict(width=0),legendgroup=label,showlegend=False,hoverinfo="skip",
                    ))
                    stats_fig.add_trace(go.Scatter(
                        x=group["Step status"],y=group["Minimum"],mode="lines",
                        line=dict(width=0),fill="tonexty",fillcolor=color,
                        opacity=0.18,legendgroup=label,showlegend=False,
                        hovertemplate="Step=%{x}<br>Minimum=%{y:.3f} °C<extra></extra>",
                    ))
                    stats_fig.add_trace(go.Scatter(
                        x=group["Step status"],y=group["Mean"],mode="lines+markers",
                        name=label,legendgroup=label,line=dict(color=color,width=2.5),marker=dict(size=8),
                        customdata=group[["Minimum","Maximum","Standard_deviation","Count"]].to_numpy(),
                        hovertemplate=("Step=%{x}<br>Mean=%{y:.3f} °C<br>Minimum=%{customdata[0]:.3f} °C"
                                       "<br>Maximum=%{customdata[1]:.3f} °C<br>SD=%{customdata[2]:.3f} °C"
                                       "<br>Count=%{customdata[3]}<extra></extra>"),
                    ))
                stats_fig.update_layout(
                    title=statistics_plot_title,xaxis_title=statistics_x_title,yaxis_title=statistics_y_title,
                    template="plotly_white",height=650,hovermode="x unified",xaxis_tickangle=-35,
                    legend_title="Batch | Sensor",margin=dict(b=190),
                )
            elif statistic_chart_type=="Grouped bar chart":
                chart_data=temperature_statistics.copy()
                chart_data["Batch | Sensor"]=chart_data["Batch"].astype(str)+" | "+chart_data["Temperature sensor"].astype(str)
                stats_fig=px.bar(
                    chart_data,x="Step status",y=statistic_metric,color="Batch | Sensor",barmode="group",
                    error_y="Standard_deviation" if statistic_metric=="Mean" else None,
                    hover_data=["Count","Minimum","Maximum","Mean","Standard_deviation","Range","%RSD"],
                    title=statistics_plot_title,
                    labels={"Step status":"Process step",statistic_metric:statistic_metric},
                )
                stats_fig.update_layout(template="plotly_white",height=650,xaxis_tickangle=-35,margin=dict(b=190))
            else:
                chart_data=temperature_statistics.copy()
                chart_data["Batch | Sensor"]=chart_data["Batch"].astype(str)+" | "+chart_data["Temperature sensor"].astype(str)
                heat=chart_data.pivot_table(index="Batch | Sensor",columns="Step status",values=statistic_metric,aggfunc="mean")
                stats_fig=px.imshow(
                    heat,aspect="auto",color_continuous_scale="RdYlBu_r",text_auto=".2f",
                    title=statistics_plot_title,
                    labels=dict(x="Process step",y="Batch | Sensor",color=statistic_metric),
                )
                stats_fig.update_layout(height=max(480,100+55*len(heat)),xaxis_tickangle=-35,margin=dict(b=190))

            stats_fig.update_xaxes(title_text=statistics_x_title)
            stats_fig.update_yaxes(title_text=statistics_y_title)
            stats_fig.update_layout(legend_title_text=statistics_legend_title)
            if statistic_chart_type=="Heatmap":
                stats_fig.update_coloraxes(colorbar_title_text=statistics_legend_title)
            stats_fig=apply_plot_font_sizes(stats_fig)
            show_plot_with_downloads(
                stats_fig,
                chart_key=f"temperature_statistics_{statistic_chart_type}_{statistic_metric}",
                file_stem=f"temperature_statistics_{statistic_chart_type}_{statistic_metric}",
                height=650,
            )

            safe_table(
                temperature_statistics,
                height=650,
                max_rows=max(3000,len(temperature_statistics)),
                key="temperature_step_statistics_table_v10",
            )
            st.download_button(
                "Download temperature statistics CSV",
                data=temperature_statistics.to_csv(index=False).encode("utf-8-sig"),
                file_name="temperature_statistics_by_batch_sensor_step.csv",
                mime="text/csv",
                width="stretch",
                key="download_temperature_statistics_v10",
            )

with tabs[3]:
    st.subheader("Report tag extraction audit")
    st.caption("This table distinguishes tags that are printed in the PDF report from tags that exist only on the HMI. HMI mapping cannot create historical values that are absent from the PDF.")
    if tag_inventory.empty:
        st.info("No cycle/event tag headers were found in this report format.")
    else:
        safe_table(tag_inventory.sort_values(["Extraction status","Canonical tag"]),height=650,max_rows=10000,key="tag_audit")
with tabs[4]:
    st.subheader("Interval-by-interval material-transfer flowrate")
    st.caption("Flowrate is calculated at every consecutive sampling interval. No average or transfer-episode aggregation is applied.")
    if flow_points.empty:
        st.info("No load-cell data is available for interval flowrate calculation.")
    else:
        flow_tags=sorted(flow_points["Instrument tag"].astype(str).unique())
        flow_tag=st.selectbox("Load-cell tag",flow_tags,key=f"flow_tag_{active_name}")
        flow_tag_data=flow_points[flow_points["Instrument tag"].astype(str)==str(flow_tag)].copy()
        flow_steps=sorted(x for x in flow_tag_data["Step status"].dropna().astype(str).unique() if x.strip())
        flow_step=st.selectbox("Step name",["All steps"]+flow_steps,key=f"flow_step_{active_name}_{flow_tag}")
        if flow_step!="All steps":
            flow_tag_data=flow_tag_data[flow_tag_data["Step status"].astype(str)==flow_step]
        measurable=flow_tag_data[flow_tag_data["Flowrate (kg/min)"].notna()].copy()
        c1,c2,c3=st.columns(3)
        c1.metric("Valid intervals",f"{len(measurable):,}")
        c2.metric("Selected step",flow_step)
        c3.metric("Load-cell tag",flow_tag)
        if measurable.empty:
            st.info("No valid consecutive intervals are available for the selected step.")
        else:
            plot=measurable.iloc[::max(1,len(measurable)//3000)]
            fig=px.line(plot,x="Date time",y="Flowrate (kg/min)",color="Transfer direction",markers=True,title=f"{custom_flowrate_title}: {flow_tag} | {flow_step}")
            fig.update_layout(
                xaxis_title=custom_flowrate_x_title,
                yaxis_title=custom_flowrate_y_title,
                legend_title_text=custom_flowrate_legend_title,
            )
            show_plot_with_downloads(
                fig,
                chart_key=f"interval_flow_plot_{active_name}_{flow_tag}_{flow_step}",
                file_stem=f"interval_flow_{active_name}_{flow_tag}_{flow_step}",
            )
            cols=["Previous time","Date time","Instrument tag","Vessel","Destination / route","Previous weight (kg)","Smoothed weight (kg)","Weight change (kg)","Interval (min)","Signed flow (kg/min)","Flowrate (kg/min)","Flowrate (kg/h)","Transfer direction","Step status","Source page"]
            safe_table(measurable[cols],height=650,max_rows=max(3000,len(measurable)),key=f"interval_flow_{active_name}_{flow_tag}_{flow_step}")

with tabs[5]:
    mapping=long_df[["Instrument tag","HMI equipment","HMI measurement name","Unit"]].drop_duplicates().sort_values(["HMI equipment","Instrument tag"])
    safe_table(mapping,height=650)
with tabs[6]:
    group_name=st.selectbox("Instrument group",list(groups.keys()))
    safe_table(groups[group_name])
with tabs[7]:
    search=st.text_input("Search tag, status, unit or timestamp")
    view=long_df
    if search:
        view=view[view.astype(str).apply(lambda x:x.str.contains(search,case=False,na=False)).any(axis=1)]
    safe_table(view)
    export_scope=st.radio(
        "Excel export scope",
        ["Complete extracted table", "Current filtered table"],
        horizontal=True,
        key=f"excel_scope_{active_name}",
    )
    export_df=long_df if export_scope=="Complete extracted table" else view
    export_name=f"{batch_number}_complete_extracted_table.xlsx" if export_scope=="Complete extracted table" else f"{batch_number}_filtered_extracted_table.xlsx"
    st.download_button(
        f"Download {export_scope.lower()} in Excel",
        data=dataframe_to_excel_bytes(export_df, "Extracted Table"),
        file_name=export_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        width="stretch",
        key=f"excel_export_{active_name}_{export_scope}",
        disabled=export_df.empty,
    )
    st.caption(f"Excel export contains {len(export_df):,} extracted rows.")
with tabs[8]:
    a,b=st.columns(2)
    with a:
        st.subheader(f"Event records ({len(events):,})")
        safe_table(events,height=520) if not events.empty else st.info("No event records extracted.")
    with b:
        st.subheader(f"Alarm records ({len(alarms):,})")
        safe_table(alarms,height=520) if not alarms.empty else st.info("No alarm records extracted.")
with tabs[9]:
    safe_table(pd.DataFrame({"Batch number":batch_number,**meta}.items(),columns=["Field","Value"]),height=430)

st.caption("All PDFs are processed independently in memory. Excel files are generated only when you click a download button and are not stored by the app.")
