from io import BytesIO
from datetime import datetime, timedelta
import os
import subprocess
import tempfile
import time
import gc
import re
import pandas as pd
import plotly.express as px
import streamlit as st
import pdfplumber
from pathlib import Path


def clear_application_cache():
    """Clear parsed-report caches and temporary selection state."""
    st.cache_data.clear()
    st.cache_resource.clear()
    for key in list(st.session_state.keys()):
        if key=="processed_reports" or key.startswith(("report_type_", "combined_", "flow_", "page_")):
            del st.session_state[key]
    st.session_state["cache_cleared_notice"] = True

st.set_page_config(page_title="ADAM Process Report - Tagwise Extraction", page_icon="📊", layout="wide")

st.sidebar.header("Application controls")
if st.sidebar.button("Clear application cache", type="primary", use_container_width=True, help="Clears parsed-report data, Streamlit resources, and temporary report selections, then reloads the app."):
    clear_application_cache()
    st.rerun()
if st.session_state.pop("cache_cleared_notice", False):
    st.sidebar.success("Application cache cleared. Please upload the PDF again.")
st.sidebar.caption("Use after updating app.py, changing report type, or seeing an old cached parsing error.")
DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+)$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
TAG_RE = re.compile(r"^(?:LSICR|PICR|TICR|TA|TLP|RLS|CP|PT|TT|XV|DP|QI?CR|CI?CR|MFM)[A-Z0-9_-]*$", re.I)
TAG_TOKEN_RE = re.compile(r"(?:LSICR|PICR|TICR|TA|TLP|RLS|CP|PT|TT|XV|DP|QICR|CICR|MFM)[A-Z0-9_-]*", re.I)


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
    """Calculate mass flow for each consecutive valid load-cell interval, without averaging."""
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
    """Add HMI names without tuple mapping or MultiIndex construction."""
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
    """Fast PDF text extraction using Poppler, with pdfplumber fallback."""
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
    """Inventory every tag printed in cycle/event headers, even if no data row is parsed."""
    found=[]
    for page_no,text in enumerate(pages,1):
        lines=text.splitlines()
        section="Event" if "EVENT RECORD" in text.upper() else ("Cycle" if "CYCLE RECORD" in text.upper() else "Other")
        for line in lines:
            u=line.upper()
            if "DATE TIME" in u and ("STEP STATUS" in u or "EVENT STATUS" in u):
                right=re.split(r"DATE TIME",line,flags=re.I,maxsplit=1)[1]
                right=re.sub(r"(?:STEP|EVENT) STATUS.*$","",right,flags=re.I)
                for candidate in [x.strip() for x in re.split(r"\\s{2,}",right) if x.strip()]:
                    if TAG_RE.match(candidate):
                        found.append({"Raw report tag":candidate,"Canonical tag":canonical_tag(candidate),"Section":section,"Header page":page_no})
            if re.match(r"^\\s*Tag\\s+",line,re.I):
                for candidate in [x.strip() for x in re.split(r"\\s{2,}",line.strip())[1:] if x.strip()]:
                    if TAG_RE.match(candidate):
                        found.append({"Raw report tag":candidate,"Canonical tag":canonical_tag(candidate),"Section":section,"Header page":page_no})
    return pd.DataFrame(found).drop_duplicates() if found else pd.DataFrame(columns=["Raw report tag","Canonical tag","Section","Header page"])

def header_tags(page_text):
    """Extract every tag token from the current page header without relying on spacing."""
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


def build_cross_batch_wide(valid_reports):
    """Reconstruct one wide process table per uploaded report."""
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
        meta = item.get("meta", {})
        batch = meta.get("Batch number", item["file_name"]) if isinstance(meta, dict) else item["file_name"]
        wide.insert(0, "Source report", item["file_name"])
        wide.insert(1, "Batch", str(batch))
        frames.append(wide)
    return pd.concat(frames, ignore_index=True, sort=False) if frames else pd.DataFrame()


def make_step_elapsed_profile(wide_df, selected_steps):
    """Align every contiguous step occurrence at elapsed time zero."""
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

def show_plot_with_downloads(fig, chart_key, file_stem, height=None):
    """Display a Plotly chart and provide HTML and high-resolution PNG downloads."""
    if height:
        fig.update_layout(height=height)
    st.plotly_chart(fig, use_container_width=True, key=chart_key)
    safe_name=re.sub(r"[^A-Za-z0-9_-]+", "_", str(file_stem)).strip("_") or "plot"
    html_bytes=fig.to_html(full_html=True, include_plotlyjs=True).encode("utf-8")
    left,right=st.columns(2)
    left.download_button(
        "Download interactive HTML",
        data=html_bytes,
        file_name=f"{safe_name}.html",
        mime="text/html",
        key=f"download_html_{chart_key}",
        use_container_width=True,
    )
    try:
        png_bytes=fig.to_image(format="png", width=1800, height=1000, scale=2)
        right.download_button(
            "Download high-resolution PNG",
            data=png_bytes,
            file_name=f"{safe_name}.png",
            mime="image/png",
            key=f"download_png_{chart_key}",
            use_container_width=True,
        )
    except Exception as exc:
        right.info("PNG export unavailable. Ensure kaleido is installed; HTML download remains available.")

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
    st.dataframe(view,use_container_width=True,hide_index=True,height=height,row_height=31,key=key)

st.title("Universal ADAM and OMCA ANFDA Multi-Report Extractor")
st.caption("Fast extraction uses Poppler pdftotext, then applies the selected ADAM or OMCA parser. Multiple reports are supported without automatic detection delay.")
uploads=st.sidebar.file_uploader(
    "Upload multiple report PDFs",
    type=["pdf"],
    accept_multiple_files=True,
    help="You can upload ADAM and OMCA ANFDA reports together."
)
if not uploads:
    st.info("Upload one or more supported PDFs. Report formats will be detected automatically.")
    st.stop()


if len(uploads)>5:
    st.error("Upload a maximum of 5 reports per processing run to avoid Streamlit Community Cloud memory exhaustion.")
    st.stop()
large=[f.name for f in uploads if f.size>50*1024*1024]
if large:
    st.error("Each PDF must be 50 MB or smaller: "+", ".join(large))
    st.stop()

st.sidebar.subheader("Processing control")
process_now=st.sidebar.button("Process uploaded reports",type="primary",use_container_width=True)
if not process_now and "processed_reports" not in st.session_state:
    st.info("Select each report type, then click **Process uploaded reports**. Processing will run once and results will remain in the session.")

st.sidebar.subheader("Select report type for each PDF")
report_type_by_file={}
for idx,uploaded in enumerate(uploads):
    filename=uploaded.name.lower()
    default_index=1 if any(x in filename for x in ["drying","trial batch","anfd-2","omca"]) else 0
    report_type_by_file[uploaded.name]=st.sidebar.selectbox(
        uploaded.name,
        ["ADAM Skid Process Report","OMCA ANFDA Drying Report"],
        index=default_index,
        key=f"report_type_{idx}_{uploaded.name}_{uploaded.size}",
        help="ADAM: Process Cycle reports with full date/time and multiple LSICR/PICR/TICR groups. OMCA ANFDA: ANFD-2 Drying reports with Record, Time, TT-01, TT-02, PT-01, Filter_Pos, Agit_Rpm and Agit_Pos."
    )

@st.cache_data(show_spinner=False, max_entries=2, ttl=1800)
def process_uploaded_report(file_name, raw, selected_type, parser_version="status-v2"):
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
    else:
        error="Select a valid report type."
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
    reports=[]
    progress=st.progress(0,text="Starting fast report processing...")
    for i,uploaded in enumerate(uploads):
        selected_type=report_type_by_file[uploaded.name]
        progress.progress(i/len(uploads),text=f"Extracting {uploaded.name} as {selected_type} ({i+1} of {len(uploads)})")
        try:
            reports.append(process_uploaded_report(uploaded.name,uploaded.getvalue(),selected_type,"status-v2"))
        except Exception as exc:
            reports.append({"file_name":uploaded.name,"detected_type":"Failed","error":str(exc),"long_df":pd.DataFrame(),"events":pd.DataFrame(),"alarms":pd.DataFrame(),"groups":{},"meta":{"File name":uploaded.name},"adam_score":0,"omca_score":0})
        gc.collect()
    progress.progress(1.0,text=f"Processed {len(uploads)} report(s)")
    st.session_state["processed_reports"]=reports
elif "processed_reports" in st.session_state:
    reports=st.session_state["processed_reports"]
else:
    st.stop()

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
if not valid:
    st.error("None of the uploaded reports could be processed. Review the summary messages.")
    st.stop()

report_names=[r["file_name"] for r in valid]
active_name=st.sidebar.selectbox("Active report",report_names)
r=next(x for x in valid if x["file_name"]==active_name)
long_df=r["long_df"]; groups=r["groups"]; events=r["events"]; alarms=r["alarms"]; meta=r["meta"]; tag_inventory=r.get("tag_inventory",pd.DataFrame())
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
tag_options=long_df[["Instrument tag","HMI display label"]].drop_duplicates().sort_values("Instrument tag")
tags=tag_options["Instrument tag"].tolist()
selected_label=st.sidebar.selectbox("Instrument tag / HMI name",tag_options["HMI display label"].tolist(),key=f"tag_select_{active_name}")
selected_tag=tag_options.loc[tag_options["HMI display label"]==selected_label,"Instrument tag"].iloc[0]
tag_df=long_df[long_df["Instrument tag"]==selected_tag].sort_values("Date time")
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

tabs=st.tabs(["Selected tag","Tag summary", "Cross-batch profiles","Extraction audit","Transfer flowrate","HMI tag dictionary","Instrument groups","All tagwise data","Events & alarms","Metadata"])
with tabs[0]:
    selected_equipment=tag_df["HMI equipment"].iloc[0] if not tag_df.empty else ""
    selected_measurement=tag_df["HMI measurement name"].iloc[0] if not tag_df.empty else ""
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
    st.subheader("MV04/MV05 cross-batch process profiles")
    st.caption("Compare vessel weight, pressure, temperature and agitator profiles across uploaded ADAM batches. Elapsed-time alignment starts every selected step at 0 minutes.")
    cross_wide = build_cross_batch_wide(valid)
    if cross_wide.empty:
        st.info("Process at least one ADAM Process report to create profiles.")
    else:
        # Batch selector controls every cross-batch profile chart and its table.
        available_batches = sorted(x for x in cross_wide["Batch"].dropna().astype(str).unique() if x.strip())
        selected_batches = st.multiselect(
            "Batch numbers",
            available_batches,
            default=available_batches,
            key="profile_batches",
            help="Select one batch for an individual profile or multiple batches for comparison."
        )
        if not selected_batches:
            st.info("Select at least one batch number.")
            st.stop()
        cross_wide = cross_wide[cross_wide["Batch"].astype(str).isin(selected_batches)].copy()

        profile_steps = sorted(x for x in cross_wide["Step status"].dropna().astype(str).unique() if x.strip())
        requested_defaults = [
            "TRANSFER FROM MV01 TO MV04", "MV03 DEPRESSURISE",
            "TRANSFER API FROM MV03 TO MV04", "MV04 AGITATION",
            "CHECKS BEFORE COACERVATION", "MANUAL PROMPT",
            "TRANSFER FROM SFV01 TO MV04",
        ]
        default_steps = [x for x in requested_defaults if x in profile_steps]
        selected_steps = st.multiselect("Step names", profile_steps, default=default_steps, key="profile_steps")
        profile_tags = [x for x in ["LSICR004", "LSICR005", "PICR006", "TICR008", "TA005"] if x in cross_wide.columns]
        selected_tags = st.multiselect("Profile tags", profile_tags, default=profile_tags, key="profile_tags")
        x_mode = st.radio("X-axis", ["Elapsed time from step start", "Actual date/time"], horizontal=True, key="profile_x_mode")
        if not selected_steps or not selected_tags:
            st.info("Select at least one step and one tag.")
        else:
            profile = make_step_elapsed_profile(cross_wide, selected_steps)
            if profile.empty:
                st.info("No records match the selected batches and steps.")
            else:
                m1,m2,m3=st.columns(3)
                m1.metric("Selected batches",len(selected_batches))
                m2.metric("Selected steps",len(selected_steps))
                m3.metric("Profile rows",f"{len(profile):,}")
                x_col = "Elapsed time (min)" if x_mode.startswith("Elapsed") else "Date time"
                plot_profile = profile.iloc[::max(1, len(profile)//12000)].copy()
                titles = {
                    "LSICR004": "MV04 vessel weight (kg)",
                    "LSICR005": "MV05 vessel weight (kg)",
                    "PICR006": "MV05 pressure (bar)",
                    "TICR008": "MV05 temperature (°C)",
                    "TA005": "MV05 agitator speed (RPM)",
                }
                for tag in selected_tags:
                    chart = plot_profile[[x_col, "Profile label", "Batch", "Step status", tag]].dropna(subset=[tag])
                    if chart.empty:
                        continue
                    fig = px.line(chart, x=x_col, y=tag, color="Profile label", line_group="Profile label",
                                  markers=True, title=titles.get(tag, tag), hover_data=["Batch", "Step status"])
                    fig.update_layout(height=430, legend_title_text="Batch | Step | Run")
                    show_plot_with_downloads(
                        fig,
                        chart_key=f"profile_{tag}_{x_mode}",
                        file_stem=f"cross_batch_{'_'.join(selected_batches)}_{tag}_{x_mode}",
                        height=430,
                    )
                # Sort while Step occurrence still exists, then select visible columns.
                columns = ["Source report", "Batch", "Date time", "Elapsed time (min)", "Step status"] + selected_tags
                sorted_profile = profile.sort_values(["Source report", "Step occurrence", "Date time"], kind="stable")
                safe_table(sorted_profile[columns],
                           height=650, max_rows=max(3000, len(sorted_profile)), key="cross_batch_profile_table")

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
            fig=px.line(plot,x="Date time",y="Flowrate (kg/min)",color="Transfer direction",markers=True,title=f"Interval flowrate: {flow_tag} | {flow_step}")
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
    if search: view=view[view.astype(str).apply(lambda x:x.str.contains(search,case=False,na=False)).any(axis=1)]
    safe_table(view)
with tabs[8]:
    a,b=st.columns(2)
    with a:
        st.subheader(f"Event records ({len(events):,})")
        safe_table(events,height=520) if not events.empty else st.info("No event records extracted.")
    with b:
        st.subheader(f"Alarm records ({len(alarms):,})")
        safe_table(alarms,height=520) if not alarms.empty else st.info("No alarm records extracted.")
with tabs[9]:
    safe_table(pd.DataFrame(meta.items(),columns=["Field","Value"]),height=430)

st.caption("All PDFs are processed independently in memory. The app does not create or store Excel/CSV files.")
