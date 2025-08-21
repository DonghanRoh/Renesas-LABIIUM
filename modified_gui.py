# general_scpi_gui.py
# Revised: adopt connection pattern from connection_gui.py
# - Robust ASRL(serial) open with baud/termination trials
# - Standard open for non-serial resources
# - Clean handling of read/write terminations as literal "\n" etc.
# - Devices (connected) table with clear cell boundaries
# - "Create Scripts" button (enabled only when all labels are filled)
#   -> writes template_connection.py with label -> VISA/COM mappings
#
# Updated:
# - Label entry replaced with two dropdowns (Type, No.)
# - Supported types: ps, mm, smu, fgen, scope, eload, na, tm, cont, temp_force
# - Supported numbers: No Number, 1, 2, 3, 4, 5
# - Combined label shown as read-only in table and used for script generation
# - Also generates self.inst_dict grouped and ordered by type/number with aligned formatting
#
# New (2025-08-21):
# - PSU model-aware control panel:
#   * If active device Type=ps and model is HMP4040 -> channels [1,2,3,4], use INST:NSEL n + SOUR:VOLT/CURR
#   * If active device Type=ps and model is E3631A -> channels [P6V,P25V,N25V], use INST:SEL <name> + VOLT/CURR
#   * Others -> PSU panel hidden

import os
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox
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

# --- New: dropdown choices ---
LABEL_TYPES = ["ps", "mm", "smu", "fgen", "scope", "eload", "na", "tm", "cont", "temp_force"]
LABEL_NUMBERS = ["No Number", "1", "2", "3", "4", "5"]

# Order priority for inst_dict generation
TYPE_PRIORITY = {t: i for i, t in enumerate(["ps", "mm", "smu", "fgen", "scope", "eload", "na", "tm", "cont", "temp_force"])}

def combine_label(t: str, n: str) -> str:
    t = trim(t)
    n = trim(n)
    if not t:
        return ""
    if n and n != "No Number":
        return f"{t}{n}"
    return t

class DeviceShell:
    """Lightweight holder for a PyVISA instrument."""
    def __init__(self, pyvisa_instr):
        self.inst = pyvisa_instr

class GeneralSCPIGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("General SCPI GUI (PyVISA)")
        self.geometry("1100x900")

        # VISA / connection state
        self.rm = None
        # resource_key -> {"inst": DeviceShell, "idn": str, "label": str, "label_type": str, "label_num": str}
        self.sessions = {}
        self.scanned_resources = []      # list of strings
        self.connected_resource = None   # currently "active" resource key
        self.inst = None                 # currently active pyvisa instrument

        # Devices table state
        # list of row dicts: {"resource": str, "type_var": tk.StringVar, "num_var": tk.StringVar, "label_var": tk.StringVar}
        self.device_rows = []

        # PSU control state
        self.psu_frame = None
        self.psu_model_label_var = tk.StringVar(value="")
        self.psu_channel_var = tk.StringVar(value="")
        self.psu_voltage_var = tk.StringVar(value="")
        self.psu_current_var = tk.StringVar(value="")

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        conn = ttk.LabelFrame(self, text="Connection")
        conn.pack(fill="x", padx=10, pady=(10, 8))

        ttk.Button(conn, text="Scan", command=self.scan_resources).grid(row=0, column=0, padx=6, pady=8)
        ttk.Label(conn, text="Resource:").grid(row=0, column=1, padx=(12, 6), pady=8, sticky="e")

        self.resource_var = tk.StringVar()
        self.resource_combo = ttk.Combobox(conn, textvariable=self.resource_var, width=42, state="readonly")
        self.resource_combo.grid(row=0, column=2, padx=(0, 6), pady=8, sticky="w")

        ttk.Button(conn, text="Connect Selected", command=self.connect_selected).grid(row=0, column=3, padx=6, pady=8)
        ttk.Button(conn, text="Connect All", command=self.connect_all).grid(row=0, column=4, padx=6, pady=8)
        ttk.Button(conn, text="Disconnect", command=self.disconnect_current).grid(row=0, column=5, padx=6, pady=8)

        self.idn_label = ttk.Label(conn, text="[IDN] - Not connected")
        self.idn_label.grid(row=1, column=0, columnspan=6, padx=6, pady=(0, 8), sticky="w")

        # ----- PSU Controls (model-aware, hidden by default) -----
        self.psu_frame = ttk.LabelFrame(self, text="Power Supply Controls")
        self.psu_frame.pack(fill="x", padx=10, pady=(0, 8))
        self._build_psu_controls()
        self._show_psu_controls(False)

        # ----- Devices (connected) table -----
        devicesf = ttk.LabelFrame(self, text="Devices (connected)")
        devicesf.pack(fill="x", padx=10, pady=(0, 8))

        toolbar = ttk.Frame(devicesf)
        toolbar.pack(fill="x", padx=6, pady=(6, 0))
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

        # ----- Log -----
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        log_toolbar = ttk.Frame(logf)
        log_toolbar.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(log_toolbar, text="Clear Log", command=self.clear_log).pack(side="right")

        self.log = tk.Text(logf, height=18)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

    # ---------- PSU Controls ----------
    def _build_psu_controls(self):
        # Row 0: model + channel
        ttk.Label(self.psu_frame, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(self.psu_frame, textvariable=self.psu_model_label_var).grid(row=0, column=1, padx=(0, 12), pady=8, sticky="w")

        ttk.Label(self.psu_frame, text="Channel:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.psu_channel_combo = ttk.Combobox(self.psu_frame, textvariable=self.psu_channel_var, state="readonly", width=12)
        self.psu_channel_combo.grid(row=0, column=3, padx=(0, 12), pady=8, sticky="w")

        # Row 1: Voltage
        ttk.Label(self.psu_frame, text="Voltage (V):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(self.psu_frame, textvariable=self.psu_voltage_var, width=10).grid(row=1, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(self.psu_frame, text="Set V", command=self.psu_set_voltage).grid(row=1, column=2, padx=6, pady=6)
        ttk.Button(self.psu_frame, text="Query V", command=self.psu_query_voltage).grid(row=1, column=3, padx=6, pady=6)

        # Row 2: Current limit
        ttk.Label(self.psu_frame, text="Current Limit (A):").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(self.psu_frame, textvariable=self.psu_current_var, width=10).grid(row=2, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(self.psu_frame, text="Set I", command=self.psu_set_current).grid(row=2, column=2, padx=6, pady=6)
        ttk.Button(self.psu_frame, text="Query I", command=self.psu_query_current).grid(row=2, column=3, padx=6, pady=6)

        # Stretch
        for c, w in enumerate([0,1,0,1]):
            self.psu_frame.grid_columnconfigure(c, weight=w)

    def _show_psu_controls(self, show: bool):
        self.psu_frame.grid() if show else self.psu_frame.grid_remove()

    def _detect_model(self, idn: str) -> str:
        """Return 'HMP4040', 'E3631A', or ''."""
        s = (idn or "").upper()
        if "HMP4040" in s:
            return "HMP4040"
        if "E3631A" in s:
            return "E3631A"
        return ""

    def _active_is_ps(self) -> bool:
        if not self.connected_resource or self.connected_resource not in self.sessions:
            return False
        info = self.sessions[self.connected_resource]
        return trim(info.get("label_type", "")) == "ps"

    def _update_psu_panel(self):
        """Rebuild PSU channel list and model label based on active device."""
        if not self.inst or not self.connected_resource or self.connected_resource not in self.sessions:
            self._show_psu_controls(False)
            return

        info = self.sessions[self.connected_resource]
        if trim(info.get("label_type", "")) != "ps":
            self._show_psu_controls(False)
            return

        idn = info.get("idn", "")
        model = self._detect_model(idn)
        self.psu_model_label_var.set(model or "(Unknown PSU)")
        if model == "HMP4040":
            chs = ["1", "2", "3", "4"]
        elif model == "E3631A":
            # As requested: only P6V, P25V, N25V (no 1/2/3)
            chs = ["P6V", "P25V", "N25V"]
        else:
            # Unknown PSU: hide controls
            self._show_psu_controls(False)
            return

        self.psu_channel_combo["values"] = chs
        if not self.psu_channel_var.get() or self.psu_channel_var.get() not in chs:
            self.psu_channel_var.set(chs[0])

        self._show_psu_controls(True)

    # PSU SCPI helpers
    def _psu_select_channel(self, model: str, channel: str):
        """Send SCPI to select the given channel on the given model."""
        if model == "HMP4040":
            # HMP4040 uses INST:NSEL <1..4>
            self.inst.write(f"INST:NSEL {channel}")
        elif model == "E3631A":
            # E3631A uses INST:SEL <P6V|P25V|N25V>
            self.inst.write(f"INST:SEL {channel}")
        else:
            raise RuntimeError("Unsupported PSU model for channel selection.")

    def _psu_get_model(self) -> str:
        if not self.inst or not self.connected_resource:
            raise RuntimeError("No active instrument.")
        info = self.sessions.get(self.connected_resource, {})
        model = self._detect_model(info.get("idn", ""))
        if not model:
            raise RuntimeError("Unknown PSU model (IDN not recognized).")
        return model

    def psu_set_voltage(self):
        try:
            if not self._check_connected():
                return
            if not self._active_is_ps():
                messagebox.showinfo("Not a PSU", "Active device type is not 'ps'.")
                return
            model = self._psu_get_model()
            channel = trim(self.psu_channel_var.get())
            v = float(self.psu_voltage_var.get())
            self._psu_select_channel(model, channel)
            if model == "HMP4040":
                self.inst.write(f"SOUR:VOLT {v}")
            elif model == "E3631A":
                self.inst.write(f"VOLT {v}")
            self._log(f"[PSU] Set V -> {v} on {channel} ({model})")
        except Exception as e:
            messagebox.showerror("Set Voltage failed", str(e))

    def psu_set_current(self):
        try:
            if not self._check_connected():
                return
            if not self._active_is_ps():
                messagebox.showinfo("Not a PSU", "Active device type is not 'ps'.")
                return
            model = self._psu_get_model()
            channel = trim(self.psu_channel_var.get())
            i = float(self.psu_current_var.get())
            self._psu_select_channel(model, channel)
            if model == "HMP4040":
                self.inst.write(f"SOUR:CURR {i}")
            elif model == "E3631A":
                self.inst.write(f"CURR {i}")
            self._log(f"[PSU] Set I -> {i} on {channel} ({model})")
        except Exception as e:
            messagebox.showerror("Set Current failed", str(e))

    def psu_query_voltage(self):
        try:
            if not self._check_connected():
                return
            if not self._active_is_ps():
                messagebox.showinfo("Not a PSU", "Active device type is not 'ps'.")
                return
            model = self._psu_get_model()
            channel = trim(self.psu_channel_var.get())
            self._psu_select_channel(model, channel)
            if model == "HMP4040":
                resp = self.inst.query("SOUR:VOLT?").strip()
            elif model == "E3631A":
                resp = self.inst.query("VOLT?").strip()
            self.psu_voltage_var.set(resp)
            self._log(f"[PSU] Query V on {channel} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Voltage failed", str(e))

    def psu_query_current(self):
        try:
            if not self._check_connected():
                return
            if not self._active_is_ps():
                messagebox.showinfo("Not a PSU", "Active device type is not 'ps'.")
                return
            model = self._psu_get_model()
            channel = trim(self.psu_channel_var.get())
            self._psu_select_channel(model, channel)
            if model == "HMP4040":
                resp = self.inst.query("SOUR:CURR?").strip()
            elif model == "E3631A":
                resp = self.inst.query("CURR?").strip()
            self.psu_current_var.set(resp)
            self._log(f"[PSU] Query I on {channel} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Current failed", str(e))

    # ---------- helpers ----------
    def _busy(self, on=True, msg=None):
        self.config(cursor="watch" if on else "")
        if msg:
            self.status.set(msg)
        self.update_idletasks()

    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def clear_log(self):
        self.log.delete("1.0", "end")
        self.status.set("Log cleared.")

    def _update_idn_banner(self):
        if self.connected_resource and self.connected_resource in self.sessions:
            info = self.sessions[self.connected_resource]
            label = info.get("label") or ""
            idn = info.get("idn") or ""
            base = f"[IDN] {idn} ({self.connected_resource})"
            self.idn_label.config(text=(f"{label} | {base}" if label else base))
        else:
            self.idn_label.config(text="[IDN] - Not connected")

    # ---------- devices table ----------
    def _build_devices_table_headers(self):
        # Clear any existing
        for w in self.device_table.winfo_children():
            w.destroy()
        self.device_rows = []

        headers = ["#", "Type", "No.", "Label", "VISA Resource", "IDN"]
        for c, text in enumerate(headers):
            lbl = tk.Label(
                self.device_table,
                text=text,
                borderwidth=1,
                relief="solid",
                padx=6,
                pady=4,
                anchor="w",
                font=("TkDefaultFont", 9, "bold"),
            )
            lbl.grid(row=0, column=c, sticky="nsew")

        # Column expand weights
        for c, weight in enumerate([0, 1, 0, 1, 2, 3]):
            self.device_table.grid_columnconfigure(c, weight=weight)

    def _refresh_devices_table(self):
        self._build_devices_table_headers()
        # Deterministic row order
        for r, resource_key in enumerate(sorted(self.sessions.keys()), start=1):
            info = self.sessions[resource_key]
            idn = info.get("idn", "")
            t_default = info.get("label_type", "")
            n_default = info.get("label_num", "No Number")
            combined = info.get("label", "")

            # index cell
            tk.Label(self.device_table, text=str(r), borderwidth=1, relief="solid", padx=4, pady=2, anchor="w").grid(row=r, column=0, sticky="nsew")

            # type cell (dropdown)
            type_var = tk.StringVar(value=t_default)
            type_cb = ttk.Combobox(self.device_table, textvariable=type_var, values=LABEL_TYPES, state="readonly", width=12)
            type_cb.grid(row=r, column=1, sticky="nsew")

            # number cell (dropdown)
            num_var = tk.StringVar(value=n_default if n_default in LABEL_NUMBERS else "No Number")
            num_cb = ttk.Combobox(self.device_table, textvariable=num_var, values=LABEL_NUMBERS, state="readonly", width=10)
            num_cb.grid(row=r, column=2, sticky="nsew")

            # combined label (read-only)
            label_var = tk.StringVar(value=combined)
            lbl = tk.Label(self.device_table, textvariable=label_var, borderwidth=1, relief="solid", padx=6, pady=2, anchor="w")
            lbl.grid(row=r, column=3, sticky="nsew")

            # resource cell
            tk.Label(self.device_table, text=resource_key, borderwidth=1, relief="solid", padx=6, pady=2, anchor="w").grid(row=r, column=4, sticky="nsew")

            # idn cell
            tk.Label(self.device_table, text=idn, borderwidth=1, relief="solid", padx=6, pady=2, anchor="w").grid(row=r, column=5, sticky="nsew")

            # keep bindings: whenever type/num changes, recompute combined label and update session
            def _apply_change(*_, rk=resource_key, tvar=type_var, nvar=num_var, lvar=label_var):
                t = trim(tvar.get())
                n = trim(nvar.get())
                comb = combine_label(t, n)
                lvar.set(comb)
                # persist
                self.sessions[rk]["label_type"] = t
                self.sessions[rk]["label_num"] = n if n in LABEL_NUMBERS else "No Number"
                self.sessions[rk]["label"] = comb
                if rk == self.connected_resource:
                    self._update_idn_banner()
                    # Type change of active device may affect PSU panel
                    self._update_psu_panel()
                self._check_labels_filled()

            type_var.trace_add("write", _apply_change)
            num_var.trace_add("write", _apply_change)

            # Store row state
            self.device_rows.append({
                "resource": resource_key,
                "type_var": type_var,
                "num_var": num_var,
                "label_var": label_var,  # read-only combined
            })

        self._check_labels_filled()
        # Ensure PSU panel reflects any table updates for the active resource
        self._update_psu_panel()

    def _check_labels_filled(self):
        if not self.device_rows:
            self.create_btn.config(state="disabled")
            return
        # all rows must have non-empty combined label => type chosen
        all_filled = all(trim(row["label_var"].get()) for row in self.device_rows)
        self.create_btn.config(state=("normal" if all_filled else "disabled"))

    # ---------- scanning ----------
    def scan_resources(self):
        try:
            self._busy(True, "Scanning VISA resources...")
            self.rm = self.rm or pyvisa.ResourceManager()
            self.scanned_resources = list(self.rm.list_resources())
            if not self.scanned_resources:
                self.status.set("No VISA resources found.")
                self._log("[SCAN] No VISA resources found.")
                self.resource_combo["values"] = []
                self.resource_var.set("")
            else:
                self.status.set(f"Found {len(self.scanned_resources)} resource(s).")
                self._log(f"[SCAN] {len(self.scanned_resources)} resource(s) found:")
                for r in self.scanned_resources:
                    self._log(f"  - {r}")
                self.resource_combo["values"] = self.scanned_resources
                if not self.resource_var.get():
                    self.resource_var.set(self.scanned_resources[0])
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))
        finally:
            self._busy(False, "Ready.")

    # ---------- connection pattern from connection_gui.py ----------
    def _try_open_serial(self, resource_key):
        """Attempt robust serial connection (ASRL…)."""
        self.rm = self.rm or pyvisa.ResourceManager()
        baud_candidates = [115200, 38400, 19200, 9600]
        term_candidates = [("\r\n", "\n"), ("\n", "\n"), ("\r", "\r"), ("\r\n", "\r\n")]

        try:
            inst = self.rm.open_resource(resource_key)
        except Exception:
            return None, ""

        # Base serial config (best-effort)
        try:
            inst.timeout = 500
            inst.write_timeout = 500
            inst.data_bits = 8
            inst.parity = getattr(pv.Parity, "none", 0)
            inst.stop_bits = getattr(pv.StopBits, "one", 10)
            if hasattr(inst, "rtscts"):
                inst.rtscts = False
            if hasattr(inst, "xonxoff"):
                inst.xonxoff = False
        except Exception:
            pass

        for baud in baud_candidates:
            try:
                if hasattr(inst, "baud_rate"):
                    inst.baud_rate = baud
            except Exception:
                pass
            for wterm, rterm in term_candidates:
                try:
                    if hasattr(inst, "write_termination"):
                        inst.write_termination = wterm  # precise literal
                    if hasattr(inst, "read_termination"):
                        inst.read_termination = rterm   # precise literal
                    try:
                        inst.write("")  # nudge
                    except Exception:
                        pass
                    try:
                        idn = inst.query("*IDN?").strip()
                    except Exception:
                        idn = ""
                    if idn:
                        return DeviceShell(inst), idn
                except Exception:
                    continue

        try:
            inst.close()
        except Exception:
            pass
        return None, ""

    def _open_nonserial(self, resource_key):
        """Open non-serial VISA with safe terminations/timeouts."""
        self.rm = self.rm or pyvisa.ResourceManager()
        inst = self.rm.open_resource(resource_key)
        try:
            inst.timeout = 1000
            inst.write_timeout = 1000
            if hasattr(inst, "read_termination"):
                inst.read_termination = "\n"
            if hasattr(inst, "write_termination"):
                inst.write_termination = "\n"
        except Exception:
            pass
        return DeviceShell(inst)

    def connect_selected(self):
        sel = trim(self.resource_var.get())
        if not sel:
            messagebox.showinfo("No resource", "Select a VISA resource first.")
            return

        # Already connected? Just activate it.
        if sel in self.sessions:
            self.connected_resource = sel
            self.inst = self.sessions[sel]["inst"].inst
            self._update_idn_banner()
            self.status.set("Activated existing connection.")
            self._log(f"[ACTIVATE] {sel}")
            self._update_psu_panel()
            return

        self._busy(True, f"Connecting to {sel}...")
        try:
            if sel.upper().startswith("ASRL"):
                dev, idn = self._try_open_serial(sel)
                if dev is None:
                    self._log(f"[ERROR] Failed to connect {sel}: no response on serial.")
                    messagebox.showerror("Connect failed", f"No response on serial: {sel}")
                    return
            else:
                dev = self._open_nonserial(sel)
                try:
                    idn = dev.inst.query("*IDN?").strip()
                except Exception:
                    idn = ""

            # store session and activate
            self.sessions[sel] = {
                "inst": dev, "idn": idn,
                "label": "",
                "label_type": "",         # New
                "label_num": "No Number", # New
            }
            self.connected_resource = sel
            self.inst = dev.inst
            self._update_idn_banner()
            self._log(f"[CONNECT] Connected {sel}  IDN: {idn or '(no response)'}")
            self.status.set("Connected.")
            self._refresh_devices_table()
            self._update_psu_panel()
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))
            self.status.set("Connect failed.")
        finally:
            self._busy(False, "Ready.")

    def connect_all(self):
        if not self.scanned_resources:
            messagebox.showinfo("Nothing to connect", "Scan resources first.")
            return
        self._busy(True, "Connecting to all scanned instruments...")
        connected_count = 0

        for resource_key in self.scanned_resources:
            if resource_key in self.sessions:
                continue
            try:
                if resource_key.upper().startswith("ASRL"):
                    dev, idn = self._try_open_serial(resource_key)
                    if dev is None:
                        self._log(f"[ERROR] Failed to connect {resource_key}: no response on serial.")
                        continue
                else:
                    dev = self._open_nonserial(resource_key)
                    try:
                        idn = dev.inst.query("*IDN?").strip()
                    except Exception:
                        idn = ""

                self.sessions[resource_key] = {
                    "inst": dev, "idn": idn,
                    "label": "",
                    "label_type": "",
                    "label_num": "No Number",
                }
                self._log(f"[INFO] Connected: {idn or '(no response)'} ({resource_key})")
                connected_count += 1

                # If nothing active yet, activate first successful
                if not self.connected_resource:
                    self.connected_resource = resource_key
                    self.inst = dev.inst
                    self.resource_var.set(resource_key)
                    self._update_idn_banner()
            except Exception as e:
                self._log(f"[ERROR] Failed to connect {resource_key}: {e}")

        self.status.set(f"Connected {connected_count} device(s).")
        self._refresh_devices_table()
        self._update_psu_panel()
        self._busy(False, "Ready.")

    def disconnect_current(self):
        try:
            if self.inst and self.connected_resource:
                res = self.connected_resource
                try:
                    self.inst.close()
                except Exception:
                    pass
                # remove from sessions
                if res in self.sessions:
                    try:
                        # ensure underlying resource closed
                        self.sessions[res]["inst"].inst.close()
                    except Exception:
                        pass
                    del self.sessions[res]
                self.inst = None
                self.connected_resource = None
                self._log(f"[DISCONNECT] Closed {res}")
                self.idn_label.config(text="[IDN] - Not connected")
                self.status.set("Disconnected.")
                self._refresh_devices_table()
                self._show_psu_controls(False)
            else:
                self.status.set("Nothing to disconnect.")
        except Exception as e:
            messagebox.showerror("Disconnect failed", str(e))

    # ---------- command helpers ----------
    def _check_connected(self):
        if not self.inst:
            messagebox.showinfo("Not connected", "Connect to a VISA resource first.")
            return False
        return True

    def _format_selected_command(self, for_query: bool) -> str:
        tpl = trim(self.cmd_var.get())
        param = trim(self.param_var.get())
        if "{param}" in tpl:
            if not param and not tpl.endswith("?"):
                self._log("[WARN] No parameter provided; sending without value.")
            cmd = tpl.replace("{param}", param)
        else:
            cmd = tpl if (for_query or not param) else f"{tpl} {param}"
        if for_query and not cmd.endswith("?"):
            base_up = cmd.upper().split(" ")[0]
            if base_up in QUERYABLE_BASES:
                cmd = cmd + "?"
        return cmd

    # ---------- write/query ----------
    def do_write(self):
        if not self._check_connected():
            return
        cmd = self._format_selected_command(False)
        if cmd.endswith("?"):
            messagebox.showinfo("Use Query", "This looks like a query. Use the Query button.")
            return
        try:
            self.inst.write(cmd)
            self._log(f"[WRITE] {cmd}")
        except Exception as e:
            messagebox.showerror("Write failed", str(e))

    def do_query(self):
        if not self._check_connected():
            return
        cmd = self._format_selected_command(True)
        if not cmd.endswith("?"):
            messagebox.showinfo("Not a query", "This command is not a query.")
            return
        try:
            resp = self.inst.query(cmd).strip()
            self._log(f"[QUERY] {cmd} -> {resp}")
        except Exception as e:
            messagebox.showerror("Query failed", str(e))

    def custom_write(self):
        if not self._check_connected():
            return
        cmd = trim(self.custom_var.get())
        if not cmd:
            messagebox.showinfo("No command", "Enter a custom SCPI command.")
            return
        if cmd.endswith("?"):
            messagebox.showinfo("Use Query", "Custom command ends with '?'.")
            return
        try:
            self.inst.write(cmd)
            self._log(f"[WRITE] {cmd}")
        except Exception as e:
            messagebox.showerror("Write failed", str(e))

    def custom_query(self):
        if not self._check_connected():
            return
        cmd = trim(self.custom_var.get())
        if not cmd:
            messagebox.showinfo("No command", "Enter a custom SCPI command.")
            return
        if not cmd.endswith("?"):
            messagebox.showinfo("Not a query", "Custom query must end with '?'.")
            return
        try:
            resp = self.inst.query(cmd).strip()
            self._log(f"[QUERY] {cmd} -> {resp}")
        except Exception as e:
            messagebox.showerror("Query failed", str(e))

    # ---------- script generation ----------
    @staticmethod
    def _sanitize_label(name: str) -> str:
        """Turn arbitrary label into a safe Python attribute name."""
        name = trim(name)
        if not name:
            return ""
        # Replace non-identifier chars with underscore
        safe = re.sub(r"\W", "_", name)
        # If starts with digit, prefix underscore
        if re.match(r"^\d", safe):
            safe = "_" + safe
        return safe

    @staticmethod
    def _resource_to_value(resource: str) -> str:
        """Map VISA resource to desired string value.
        ASRL<n>::... -> 'COM<n>' else keep resource literal.
        Accepts typos like ::NSTR as well."""
        m = re.match(r"^ASRL(\d+)", resource.strip(), flags=re.IGNORECASE)
        if m:
            return f"COM{m.group(1)}"
        return resource

    def create_scripts(self):
        # Collect labeled devices (combined labels) and per-row type/num
        labels = []
        items = []          # (label, resource)
        dict_entries = []   # (type, num, KEY) where KEY is upper-case label for inst_dict

        for row in self.device_rows:
            label_raw = row["label_var"].get()
            t = trim(row["type_var"].get())
            n = trim(row["num_var"].get())
            label = self._sanitize_label(label_raw)
            if not label or not t:
                messagebox.showerror("Invalid label", "All rows must have a Type selected.")
                return

            labels.append(label)
            items.append((label, row["resource"]))

            # Build uppercase key for inst_dict
            key = t.upper()
            if n and n != "No Number":
                key = f"{key}{n}"
            dict_entries.append((t, n, key))

        # Check duplicates for attribute labels
        dups = {x for x in labels if labels.count(x) > 1}
        if dups:
            messagebox.showerror("Duplicate labels", f"Labels must be unique. Duplicates: {', '.join(sorted(dups))}")
            return

        # Build file content
        lines = []
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        lines.append("# Auto-generated by General SCPI GUI")
        lines.append(f"# Generated: {ts}")
        lines.append("")
        lines.append("class TemplateConnection:")
        lines.append("    def __init__(self):")

        # 1) self.<label> = ('<value>') lines
        for label, resource in items:
            value = self._resource_to_value(resource)
            lines.append(f"        self.{label} = ('{value}')")

        # 2) self.inst_dict with required ordering/formatting
        # Sort by type priority, then by number (No Number -> 0), then by KEY for stability
        def _num_val(num_str: str) -> int:
            if num_str and num_str != "No Number":
                try:
                    return int(num_str)
                except ValueError:
                    return 0
            return 0

        dict_entries_sorted = sorted(
            dict_entries,
            key=lambda x: (TYPE_PRIORITY.get(x[0], 999), _num_val(x[1]), x[2])
        )

        # Group by type preserving the sorted order
        grouped = {}
        for t, n, key in dict_entries_sorted:
            grouped.setdefault(t, []).append(key)

        # If nothing to add, still create empty dict
        if dict_entries_sorted:
            # Padding for colon alignment
            max_key_len = max(len(k) for _, _, k in dict_entries_sorted)
            def fmt_token(k: str) -> str:
                pad = " " * (max_key_len - len(k))
                return f"'{k}'{pad} : ['X']"

            # Build lines per type in specified order
            parts = []
            for t in ["ps", "mm", "smu", "fgen", "scope", "eload", "na", "tm", "cont", "temp_force"]:
                if t in grouped:
                    tokens = [fmt_token(k) for k in grouped[t]]
                    parts.append(", ".join(tokens))

            prefix = "        self.inst_dict = "
            indent = " " * len(prefix)
            combined = (",\n" + indent).join(parts)
            lines.append("")
            lines.append(f"{prefix}{{{combined}}}")
        else:
            lines.append("")
            lines.append("        self.inst_dict = {}")

        content = "\n".join(lines) + "\n"
        out_path = os.path.join(os.getcwd(), "template_connection.py")
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._log(f"[SCRIPT] Wrote {out_path}")
            messagebox.showinfo("Success", f"Created {out_path}")
        except Exception as e:
            messagebox.showerror("Write failed", f"Could not create template_connection.py:\n{e}")

    # ---------- event loop ----------
    def mainloop(self, n=0):
        # Ensure PSU panel is consistent at start
        self._update_psu_panel()
        super().mainloop(n)

if __name__ == "__main__":
    app = GeneralSCPIGUI()
    app.mainloop()
