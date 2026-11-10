from io import BytesIO
from datetime import datetime, timedelta
import gc
import re
import pandas as pd
import plotly.express as px
import streamlit as st
import pdfplumber

st.set_page_config(page_title="ADAM Process Report - Tagwise Extraction", page_icon="📊", layout="wide")
DATE_RE = re.compile(r"^(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\s+(.+)$")
NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
TAG_RE = re.compile(r"^(?:LSICR|PICR|TICR|TA|TLP|RLS|CP|PT|TT|XV)[A-Z0-9-]*$", re.I)


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

def calculate_transfer_flowrates(long_df, min_duration_min=2.0, min_weight_change_kg=0.25, smoothing_points=3):
    """Estimate mass-transfer rate from sustained vessel weight change.

    Flow = -d(weight)/dt for source-vessel discharge and +d(weight)/dt for receiving-vessel charge.
    Short spikes are excluded using duration and total-weight-change thresholds.
    """
    if long_df is None or long_df.empty:
        return pd.DataFrame(),pd.DataFrame()
    load=long_df[long_df["Instrument tag"].isin(FLOW_SOURCE_TAGS)].copy()
    if load.empty:
        return pd.DataFrame(),pd.DataFrame()
    point_parts=[]; episode_rows=[]
    for (source_report,tag),g in load.groupby(["Source report","Instrument tag"],dropna=False) if "Source report" in load.columns else load.assign(**{"Source report":"Active report"}).groupby(["Source report","Instrument tag"]):
        g=g.sort_values("Date time").drop_duplicates("Date time").copy()
        g["Smoothed weight (kg)"]=g["Value"].rolling(max(1,int(smoothing_points)),center=True,min_periods=1).median()
        g["Interval (min)"]=g["Date time"].diff().dt.total_seconds().div(60)
        g["Weight change (kg)"]=g["Smoothed weight (kg)"].diff()
        g["Signed flow (kg/min)"]=g["Weight change (kg)"].div(g["Interval (min)"])
        g.loc[(g["Interval (min)"]<=0)|(g["Interval (min)"]>5),"Signed flow (kg/min)"]=pd.NA
        g["Transfer direction"]=g["Signed flow (kg/min)"].apply(lambda x:"Receiving / charging" if pd.notna(x) and x>0 else ("Source / discharging" if pd.notna(x) and x<0 else "No measurable transfer"))
        g["Transfer flowrate (kg/min)"]=g["Signed flow (kg/min)"].abs()
        g["Transfer flowrate (kg/h)"]=g["Transfer flowrate (kg/min)"]*60
        g["Source vessel"]=FLOW_SOURCE_TAGS[tag]
        g["Destination / route"]=g["Step status"].map(infer_destination)
        active=g["Signed flow (kg/min)"].abs().ge(0.02) & g["Signed flow (kg/min)"].notna()
        # Split episodes when direction, activity, status, or time continuity changes.
        direction=g["Signed flow (kg/min)"].apply(lambda x:1 if pd.notna(x) and x>0 else (-1 if pd.notna(x) and x<0 else 0))
        split=(active.ne(active.shift())|direction.ne(direction.shift())|g["Step status"].ne(g["Step status"].shift())|g["Interval (min)"].gt(5)).cumsum()
        g["Transfer episode"]=split
        point_parts.append(g)
        for episode,ep in g[active].groupby("Transfer episode"):
            if ep.empty: continue
            start=ep.iloc[0]["Date time"]-pd.to_timedelta(float(ep.iloc[0]["Interval (min)"] or 0),unit="m")
            end=ep.iloc[-1]["Date time"]
            duration=(end-start).total_seconds()/60
            weight_change=ep["Weight change (kg)"].sum()
            if duration < float(min_duration_min) or abs(weight_change) < float(min_weight_change_kg): continue
            avg=abs(weight_change)/duration
            episode_rows.append({
                "Source report":source_report,"Instrument tag":tag,"Vessel":FLOW_SOURCE_TAGS[tag],
                "Direction":"Receiving / charging" if weight_change>0 else "Source / discharging",
                "Destination / route":infer_destination(" ".join(ep["Step status"].astype(str).unique())),
                "Start":start,"End":end,"Duration (min)":duration,"Net weight change (kg)":weight_change,
                "Average flow (kg/min)":avg,"Average flow (kg/h)":avg*60,
                "Peak interval flow (kg/min)":ep["Transfer flowrate (kg/min)"].max(),
                "Step status":" | ".join(ep["Step status"].astype(str).unique()),
            })
    points=pd.concat(point_parts,ignore_index=True) if point_parts else pd.DataFrame()
    episodes=pd.DataFrame(episode_rows).sort_values(["Source report","Start"]) if episode_rows else pd.DataFrame()
    return points,episodes

def add_hmi_tag_names(df):
    """Add HMI equipment and measurement names while preserving the raw report tag."""
    if df is None or df.empty or "Instrument tag" not in df.columns:
        return df
    out=df.copy()
    def details(tag):
        equipment, measurement, default_unit=HMI_TAG_MAP.get(str(tag),("Not mapped from supplied HMI screens",f"Instrument tag {tag}",""))
        return equipment,measurement,default_unit
    detail=out["Instrument tag"].map(details)
    out["HMI equipment"]=detail.map(lambda x:x[0])
    out["HMI measurement name"]=detail.map(lambda x:x[1])
    if "Unit" in out.columns:
        out["Unit"]=out.apply(lambda r: r["Unit"] if str(r["Unit"]).strip() else details(r["Instrument tag"])[2],axis=1)
    out["HMI display label"]=out.apply(lambda r:f"{r['Instrument tag']} | {r['HMI equipment']} | {r['HMI measurement name']}",axis=1)
    return out

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

def safe_table(df,height=650,max_rows=3000,key=None):
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
st.caption("Upload multiple reports, manually select ADAM or OMCA ANFDA for each PDF, and process without report-type detection delay.")
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
def process_uploaded_report(file_name, raw, selected_type):
    pages=extract_pdf_pages(raw)
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
    if not long_df.empty and "Source report" not in long_df.columns:
        long_df.insert(0,"Source report",file_name)
    if not long_df.empty:
        long_df["Value"]=pd.to_numeric(long_df["Value"],errors="coerce",downcast="float")
        long_df["Source page"]=pd.to_numeric(long_df["Source page"],errors="coerce",downcast="integer")
        for c in ["Source report","Instrument tag","Unit","Step status","Instrument group"]:
            if c in long_df: long_df[c]=long_df[c].astype("category")
    long_df=add_hmi_tag_names(long_df)
    pages.clear()
    return {
        "file_name":file_name,"detected_type":detected_type,
        "adam_score":adam_score,"omca_score":omca_score,
        "meta":meta,"groups":groups,"long_df":long_df,"events":events,"alarms":alarms,"error":error,
    }

reports=[]
progress=st.progress(0,text="Starting report processing...")
for i,uploaded in enumerate(uploads):
    selected_type=report_type_by_file[uploaded.name]
    progress.progress(i/len(uploads),text=f"Processing {uploaded.name} as {selected_type} ({i+1} of {len(uploads)})")
    try:
        reports.append(process_uploaded_report(uploaded.name,uploaded.getvalue(),selected_type))
    except Exception as exc:
        reports.append({"file_name":uploaded.name,"detected_type":"Failed","error":str(exc),"long_df":pd.DataFrame(),"events":pd.DataFrame(),"alarms":pd.DataFrame(),"groups":{},"meta":{"File name":uploaded.name},"adam_score":0,"omca_score":0})
    gc.collect()
progress.progress(1.0,text=f"Processed {len(uploads)} report(s)")

summary_rows=[]
for r in reports:
    d=r.get("long_df",pd.DataFrame())
    summary_rows.append({
        "File name":r["file_name"],"Selected report type":r.get("detected_type","Unknown"),
        "Instrument tags":d["Instrument tag"].nunique() if not d.empty else 0,
        "Tagwise readings":len(d),"Events":len(r.get("events",pd.DataFrame())),
        "Alarms":len(r.get("alarms",pd.DataFrame())),"Status":"Error" if r.get("error") else "Processed",
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
long_df=r["long_df"]; groups=r["groups"]; events=r["events"]; alarms=r["alarms"]; meta=r["meta"]
flow_min_duration=st.sidebar.number_input("Minimum transfer duration (min)",min_value=1.0,max_value=30.0,value=2.0,step=1.0)
flow_min_change=st.sidebar.number_input("Minimum net weight change (kg)",min_value=0.05,max_value=20.0,value=0.25,step=0.05)
flow_smoothing=st.sidebar.select_slider("Weight smoothing points",options=[1,3,5,7],value=3)
flow_points,flow_episodes=calculate_transfer_flowrates(long_df,flow_min_duration,flow_min_change,flow_smoothing)
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
tag_options=long_df[["Instrument tag","HMI display label"]].drop_duplicates().sort_values("Instrument tag")
tags=tag_options["Instrument tag"].tolist()
selected_label=st.sidebar.selectbox("Instrument tag / HMI name",tag_options["HMI display label"].tolist())
selected_tag=tag_options.loc[tag_options["HMI display label"]==selected_label,"Instrument tag"].iloc[0]
tag_df=long_df[long_df["Instrument tag"]==selected_tag].sort_values("Date time")
statuses=sorted(tag_df["Step status"].dropna().astype(str).unique())
chosen=st.sidebar.multiselect("Step status",statuses,default=statuses)
tag_df=tag_df[tag_df["Step status"].astype(str).isin(chosen)]

m1,m2,m3,m4=st.columns(4)
m1.metric("Uploaded reports",len(uploads)); m2.metric("Processed reports",len(valid))
m3.metric("Active report tags",len(tags)); m4.metric("Active tag readings",f"{len(tag_df):,}")

summary=long_df.groupby(["Instrument tag","HMI equipment","HMI measurement name","Unit"],dropna=False).agg(Records=("Value","size"),Start=("Date time","min"),End=("Date time","max"),Minimum=("Value","min"),Maximum=("Value","max"),Mean=("Value","mean")).reset_index()

tabs=st.tabs(["Selected tag","Tag summary","Transfer flowrate","HMI tag dictionary","Instrument groups","All tagwise data","Events & alarms","Metadata"])
with tabs[0]:
    selected_equipment=tag_df["HMI equipment"].iloc[0] if not tag_df.empty else ""
    selected_measurement=tag_df["HMI measurement name"].iloc[0] if not tag_df.empty else ""
    st.subheader(f"{selected_tag}: {selected_measurement}")
    st.caption(f"HMI equipment: {selected_equipment}")
    unit=tag_df["Unit"].dropna().astype(str).replace("",pd.NA).dropna().iloc[0] if tag_df["Unit"].astype(str).str.len().gt(0).any() else ""
    plot_df=tag_df.iloc[::max(1,len(tag_df)//3000)]
    fig=px.line(plot_df,x="Date time",y="Value",title=f"{selected_tag} trend",labels={"Value":f"Value ({unit})" if unit else "Value"})
    st.plotly_chart(fig,use_container_width=True)
    safe_table(tag_df[["Date time","Instrument tag","HMI equipment","HMI measurement name","Value","Unit","Step status","Source page"]])
with tabs[1]:
    safe_table(summary,height=600)
with tabs[2]:
    st.subheader("Calculated material-transfer flowrate from vessel weight")
    st.caption("Mass flow is estimated from the slope of LSICR vessel weight: |Δweight| / Δtime. Negative slope is discharge; positive slope is receiving/charging. Results are mass flow only, not volumetric flow.")
    if flow_episodes.empty:
        st.info("No sustained weight-transfer episodes met the selected duration and weight-change thresholds.")
    else:
        source_tags=sorted(flow_episodes["Instrument tag"].unique())
        flow_tag=st.selectbox("Load-cell tag",source_tags,key="flow_tag")
        episode_view=flow_episodes[flow_episodes["Instrument tag"]==flow_tag].copy()
        safe_table(episode_view,height=520)
        point_view=flow_points[(flow_points["Instrument tag"]==flow_tag)&flow_points["Transfer flowrate (kg/min)"].notna()].copy()
        if not point_view.empty:
            plot=point_view.iloc[::max(1,len(point_view)//3000)]
            fig=px.line(plot,x="Date time",y="Transfer flowrate (kg/min)",color="Transfer direction",title=f"Calculated transfer flowrate: {flow_tag}")
            st.plotly_chart(fig,use_container_width=True)
            safe_table(point_view[["Date time","Instrument tag","Source vessel","Destination / route","Smoothed weight (kg)","Weight change (kg)","Interval (min)","Transfer direction","Transfer flowrate (kg/min)","Transfer flowrate (kg/h)","Step status"]],height=620)
with tabs[3]:
    mapping=long_df[["Instrument tag","HMI equipment","HMI measurement name","Unit"]].drop_duplicates().sort_values(["HMI equipment","Instrument tag"])
    safe_table(mapping,height=650)
with tabs[4]:
    group_name=st.selectbox("Instrument group",list(groups.keys()))
    safe_table(groups[group_name])
with tabs[5]:
    search=st.text_input("Search tag, status, unit or timestamp")
    view=long_df
    if search: view=view[view.astype(str).apply(lambda x:x.str.contains(search,case=False,na=False)).any(axis=1)]
    safe_table(view)
with tabs[6]:
    a,b=st.columns(2)
    with a:
        st.subheader(f"Event records ({len(events):,})")
        safe_table(events,height=520) if not events.empty else st.info("No event records extracted.")
    with b:
        st.subheader(f"Alarm records ({len(alarms):,})")
        safe_table(alarms,height=520) if not alarms.empty else st.info("No alarm records extracted.")
with tabs[7]:
    safe_table(pd.DataFrame(meta.items(),columns=["Field","Value"]),height=430)

st.caption("All PDFs are processed independently in memory. The app does not create or store Excel/CSV files.")
