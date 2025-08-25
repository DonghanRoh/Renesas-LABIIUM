# general_scpi_gui.py
# Row-click activation + model-aware PSU panel between General SCPI and Log
# Supports: E3631A (P6V/P25V/N25V), E3633A (OUT), HMP4040 (1..4), HMP4030 (1..3), HM8143 (U1/U2)
# Added: DMM "Show Label"/"Clear" buttons for MODEL 2000, 34410A, 34461A, 34465A
# Added: SMU "Show Label"/"Clear" buttons for Keithley MODEL 2420, 2440, 2450, 2460, 2461

import os
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pyvisa
from pyvisa import constants as pv  # parity/stopbits constants

def trim(s: str) -> str:
    return (s or "").strip()

COMMANDS = [
    "*IDN?",
    "*CLS",
    "*RST",
    "*OPC?",
    "*WAI",
    "*TST?",
    "*ESE {param}",
    "*ESR?",
    "*SRE {param}",
    "*STB?",
    "SYST:ERR?",
]

QUERYABLE_BASES = {"*IDN", "*OPC", "*TST", "*ESR", "*STB", "SYST:ERR"}

# ---- cont 제거 반영 ----
LABEL_TYPES = ["ps", "mm", "smu", "fgen", "scope", "eload", "na", "tm", "temp_force"]
LABEL_NUMBERS = ["No Number", "1", "2", "3", "4", "5"]
TYPE_PRIORITY = {t: i for i in enumerate(["ps", "mm", "smu", "fgen", "scope", "eload", "na", "tm", "temp_force"])}

def combine_label(t: str, n: str) -> str:
    t = trim(t); n = trim(n)
    if not t: return ""
    return f"{t}{n}" if (n and n != "No Number") else t

class DeviceShell:
    def __init__(self, pyvisa_instr):
        self.inst = pyvisa_instr

class GeneralSCPIGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("General SCPI GUI (PyVISA)")
        self.geometry("1100x950")

        # VISA / connection state
        self.rm = None
        self.sessions = {}              # resource_key -> {inst: DeviceShell, idn: str, ...}
        self.scanned_resources = []
        self.connected_resource = None
        self.inst = None

        # Devices table state
        self.device_rows = []
        self._row_active_bg = "#fff9d6"
        self._row_default_bg = None

        # PSU state
        self.psu_model_label_var = tk.StringVar(value="")
        self.psu_channel_var = tk.StringVar(value="")
        self.psu_voltage_var = tk.StringVar(value="")
        self.psu_current_var = tk.StringVar(value="")
        self._psu_visible = False       # track pane presence

        # Script save dir & file name (GUI에서 설정)
        self.save_dir_var = tk.StringVar(value=os.getcwd())
        self.save_filename_var = tk.StringVar(value="template_connection.py")

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        # ----- Connection -----
        conn = ttk.LabelFrame(self, text="Connection")
        conn.pack(fill="x", padx=10, pady=(10, 8))

        ttk.Button(conn, text="Scan", command=self.scan_resources).grid(row=0, column=0, padx=6, pady=8)
        ttk.Label(conn, text="Resource:").grid(row=0, column=1, padx=(12, 6), pady=8, sticky="e")

        self.resource_var = tk.StringVar()
        self.resource_combo = ttk.Combobox(conn, textvariable=self.resource_var, width=42, state="readonly")
        self.resource_combo.grid(row=0, column=2, padx=(0, 6), pady=8, sticky="w")

        ttk.Button(conn, text="Connect All", command=self.connect_all).grid(row=0, column=3, padx=6, pady=8)
        ttk.Button(conn, text="Disconnect", command=self.disconnect_current).grid(row=0, column=4, padx=6, pady=8)

        self.idn_label = ttk.Label(conn, text="[IDN] - Not connected")
        self.idn_label.grid(row=1, column=0, columnspan=6, padx=6, pady=(0, 8), sticky="w")

        # ----- Devices (connected) -----
        devicesf = ttk.LabelFrame(self, text="Devices (connected)")
        devicesf.pack(fill="x", padx=10, pady=(0, 8))
        toolbar = ttk.Frame(devicesf)
        toolbar.pack(fill="x", padx=6, pady=(6, 0))

        # Save directory chooser + file name
        ttk.Label(toolbar, text="Save Dir:").pack(side="left", padx=(0, 4))
        ttk.Entry(toolbar, textvariable=self.save_dir_var, width=40).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Browse...", command=self.browse_save_dir).pack(side="left")

        ttk.Label(toolbar, text="File Name:").pack(side="left", padx=(12, 4))
        ttk.Entry(toolbar, textvariable=self.save_filename_var, width=28).pack(side="left", padx=(0, 4))

        self.create_btn = ttk.Button(toolbar, text="Create Scripts", command=self.create_scripts, state="disabled")
        self.create_btn.pack(side="right")

        self.device_table = ttk.Frame(devicesf)
        self.device_table.pack(fill="x", padx=6, pady=6)
        self._build_devices_table_headers()

        # ----- General SCPI -----
        cmdf = ttk.LabelFrame(self, text="General SCPI Command")
        cmdf.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(cmdf, text="Command:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        self.cmd_var = tk.StringVar(value=COMMANDS[0])
        self.cmd_combo = ttk.Combobox(cmdf, textvariable=self.cmd_var, values=COMMANDS, width=28, state="readonly")
        self.cmd_combo.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="w")
        ttk.Label(cmdf, text="Param (if needed):").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.param_var = tk.StringVar(value="")
        ttk.Entry(cmdf, textvariable=self.param_var, width=16).grid(row=0, column=3, padx=(0, 8), pady=8, sticky="w")
        ttk.Button(cmdf, text="Write", command=self.do_write).grid(row=0, column=4, padx=6, pady=8)
        ttk.Button(cmdf, text="Query", command=self.do_query).grid(row=0, column=5, padx=6, pady=8)

        ttk.Label(cmdf, text="Custom SCPI:").grid(row=1, column=0, padx=6, pady=(0, 8), sticky="e")
        self.custom_var = tk.StringVar()
        ttk.Entry(cmdf, textvariable=self.custom_var).grid(row=1, column=1, columnspan=3, padx=(0, 8), pady=(0, 8), sticky="we")
        ttk.Button(cmdf, text="Write (custom)", command=self.custom_write).grid(row=1, column=4, padx=6, pady=(0, 8))
        ttk.Button(cmdf, text="Query (custom)", command=self.custom_query).grid(row=1, column=5, padx=6, pady=(0, 8))

        # ----- DMM & SMU display controls -----
        # DMM controls
        ttk.Label(cmdf, text="DMM Display:").grid(row=2, column=0, padx=6, pady=(0, 8), sticky="e")

        # [변경] DMM 버튼을 프레임에 묶어 같은 열(col=1~2)에서 좌측 정렬로 인접 배치
        dmm_btns = ttk.Frame(cmdf)
        dmm_btns.grid(row=2, column=1, columnspan=2, padx=(0, 8), pady=(0, 8), sticky="w")
        ttk.Button(dmm_btns, text="Show Label", command=self.dmm_show_label).grid(row=0, column=0, padx=(0, 8), pady=0, sticky="w")
        ttk.Button(dmm_btns, text="Clear", command=self.dmm_clear_label).grid(row=0, column=1, pady=0, sticky="w")

        # Separator to clearly divide DMM and SMU controls
        ttk.Separator(cmdf, orient="vertical").grid(row=2, column=3, sticky="ns", padx=12, pady=(0, 8))

        # SMU controls
        ttk.Label(cmdf, text="SMU Display:").grid(row=2, column=4, padx=6, pady=(0, 8), sticky="e")
        ttk.Button(cmdf, text="Show Label", command=self.smu_show_label).grid(row=2, column=5, padx=(0, 8), pady=(0, 8), sticky="w")
        ttk.Button(cmdf, text="Clear", command=self.smu_clear_label).grid(row=2, column=6, padx=(0, 8), pady=(0, 8), sticky="w")

        # ----- Paned (PSU + Log) -----
        self.paned = ttk.Panedwindow(self, orient="vertical")
        self.paned.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # PSU pane (container)
        self.psu_pane = ttk.Frame(self.paned)  # will be added/removed dynamically
        self._build_psu_controls(parent=self.psu_pane)

        # Log pane
        self.logf = ttk.LabelFrame(self.paned, text="Log")
        log_toolbar = ttk.Frame(self.logf)
        log_toolbar.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(log_toolbar, text="Clear Log", command=self.clear_log).pack(side="right")
        self.log = tk.Text(self.logf, height=18)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        # Add only the log by default; PSU will be added when a supported model is active
        self.paned.add(self.logf, weight=1)

        # Status bar
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

    # ---------- PSU Controls ----------
    def _build_psu_controls(self, parent):
        psu_frame = ttk.LabelFrame(parent, text="Power Supply Controls")
        psu_frame.pack(fill="x", padx=0, pady=0)  # internal layout within pane
        self._psu_frame = psu_frame

        # Row 0: model + channel
        ttk.Label(psu_frame, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(psu_frame, textvariable=self.psu_model_label_var).grid(row=0, column=1, padx=(0, 12), pady=8, sticky="w")

        ttk.Label(psu_frame, text="Channel:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.psu_channel_combo = ttk.Combobox(psu_frame, textvariable=self.psu_channel_var, state="readonly", width=12)
        self.psu_channel_combo.grid(row=0, column=3, padx=(0, 12), pady=8, sticky="w")

        # Row 1: Voltage
        ttk.Label(psu_frame, text="Voltage (V):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(psu_frame, textvariable=self.psu_voltage_var, width=10).grid(row=1, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(psu_frame, text="Set V", command=self.psu_set_voltage).grid(row=1, column=2, padx=6, pady=6)
        ttk.Button(psu_frame, text="Query V", command=self.psu_query_voltage).grid(row=1, column=3, padx=6, pady=6)

        # Row 2: Current limit
        ttk.Label(psu_frame, text="Current Limit (A):").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(psu_frame, textvariable=self.psu_current_var, width=10).grid(row=2, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(psu_frame, text="Set I", command=self.psu_set_current).grid(row=2, column=2, padx=6, pady=6)
        ttk.Button(psu_frame, text="Query I", command=self.psu_query_current).grid(row=2, column=3, padx=6, pady=6)

        for c, w in enumerate([0,1,0,1]):
            psu_frame.grid_columnconfigure(c, weight=w)

    def _show_psu_controls(self, show: bool):
        if show and not self._psu_visible:
            # Add above log pane
            self.paned.insert(0, self.psu_pane, weight=0)  # put PSU pane above Log
            self._psu_visible = True
        elif (not show) and self._psu_visible:
            self.paned.forget(self.psu_pane)
            self._psu_visible = False

    def _detect_model(self, idn: str) -> str:
        s = (idn or "").upper()
        if "HMP4040" in s: return "HMP4040"
        if "HMP4030" in s: return "HMP4030"
        if "E3631A"  in s: return "E3631A"
        if "E3633A"  in s: return "E3633A"
        if "HM8143"  in s: return "HM8143"
        return ""

    def _update_psu_panel(self):
        if not self.inst or not self.connected_resource or self.connected_resource not in self.sessions:
            self._show_psu_controls(False); return

        info = self.sessions[self.connected_resource]
        idn = info.get("idn", "")
        model = self._detect_model(idn)
        self.psu_model_label_var.set(model or "(Unknown)")

        if model == "HMP4040":
            chs = ["1", "2", "3", "4"]
        elif model == "HMP4030":
            chs = ["1", "2", "3"]
        elif model == "E3631A":
            chs = ["P6V", "P25V", "N25V"]
        elif model == "E3633A":
            chs = ["OUT"]  # Single output supply
        elif model == "HM8143":
            chs = ["U1", "U2"]   # HM8143: only U1/U2 support remote V/I set/query
        else:
            self._show_psu_controls(False); return

        self.psu_channel_combo["values"] = chs
        if not self.psu_channel_var.get() or self.psu_channel_var.get() not in chs:
            self.psu_channel_var.set(chs[0])

        self._show_psu_controls(True)

    # ---------- PSU SCPI helpers ----------
    def _psu_select_channel(self, model: str, channel: str):
        """Models that need explicit selection; HM8143 encodes channel in command."""
        if model in ("HMP4040", "HMP4030"):
            self.inst.write(f"INST:NSEL {channel}")
        elif model == "E3631A":
            self.inst.write(f"INST:SEL {channel}")
        elif model == "E3633A":
            return  # single output; no channel selection required
        elif model == "HM
