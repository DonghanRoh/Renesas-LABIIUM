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
# - PSU Quick Controls (voltage/current limit per channel)
# - Auto profile detection by *IDN? (Keysight E3631A, Rigol DP series, R&S HMC804x, Generic)
# - Channel helper (E3631A: P6V/P25V/N25V or 1/2/3; Rigol/R&S/Generic: 1..4)
# - Safe set: if only V or only I provided, query the other and apply together when needed (E3631A)

import os
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox
import pyvisa
from pyvisa import constants as pv  # parity/stopbits constants
from typing import Optional  # <<< for Python 3.7–3.9 compatibility

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

# ========= PSU profile helpers =========

_E3631A_CHANNELS = {"1": "P6V", "2": "P25V", "3": "N25V", "P6V": "P6V", "P25V": "P25V", "N25V": "N25V"}

def _detect_psu_profile_from_idn(idn: str) -> str:
    s = (idn or "").upper()
    if "KEYSIGHT" in s or "AGILENT" in s or "HEWLETT-PACKARD" in s:
        if "E3631A" in s:
            return "E3631A"
        return "GENERIC"
    if "RIGOL" in s and ("DP" in s or "DL" in s):
        return "RIGOL_DP"
    if "ROHDE&SCHWARZ" in s or "ROHDE & SCHWARZ" in s or "R&S" in s:
        if "HMC804" in s:
            return "RSHMC804"
        return "GENERIC"
    return "GENERIC"

def _format_float(v, digits=4):
    return f"{float(v):.{digits}f}"

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
        self.psu_profile = "GENERIC"
        self.psu_channel_var = tk.StringVar(value="1")
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

        # ----- PSU Quick Controls -----
        psuf = ttk.LabelFrame(self, text="PSU Quick Controls (per-channel)")
        psuf.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(psuf, text="Channel:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        self.psu_chan_combo = ttk.Combobox(psuf, textvariable=self.psu_channel_var, width=12, state="readonly",
                                           values=["1", "2", "3", "4", "P6V", "P25V", "N25V"])
        self.psu_chan_combo.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="w")

        ttk.Label(psuf, text="Voltage (V):").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        ttk.Entry(psuf, textvariable=self.psu_voltage_var, width=12).grid(row=0, column=3, padx=(0, 8), pady=8, sticky="w")

        ttk.Label(psuf, text="Current Limit (A):").grid(row=0, column=4, padx=6, pady=8, sticky="e")
        ttk.Entry(psuf, textvariable=self.psu_current_var, width=12).grid(row=0, column=5, padx=(0, 8), pady=8, sticky="w")

        ttk.Button(psuf, text="Set Voltage", command=self.psu_set_voltage).grid(row=0, column=6, padx=6, pady=8)
        ttk.Button(psuf, text="Set Current", command=self.psu_set_current).grid(row=0, column=7, padx=6, pady=8)
        ttk.Button(psuf, text="Set Both", command=self.psu_set_both).grid(row=0, column=8, padx=6, pady=8)
        ttk.Button(psuf, text="Read Back", command=self.psu_read_back).grid(row=0, column=9, padx=6, pady=8)

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
            # Update PSU profile guess
            self.psu_profile = _detect_psu_profile_from_idn(idn)
            self._adjust_psu_channel_choices()
        else:
            self.idn_label.config(text="[IDN] - Not connected")

    def _adjust_psu_channel_choices(self):
        # For E3631A show P6V/P25V/N25V prominently
        if self.psu_profile == "E3631A":
            choices = ["P6V", "P25V", "N25V", "1", "2", "3"]
        else:
            choices = ["1", "2", "3", "4"]
        self.psu_chan_combo["values"] = choices
        cur = self.psu_channel_var.get()
        if cur not in choices:
            self.psu_channel_var.set(choices[0])

    # ---------- devices table ----------
    def _build_devices_table_headers(self):
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

        for c, weight in enumerate([0, 1, 0, 1, 2, 3]):
            self.device_table.grid_columnconfigure(c, weight=weight)

    def _refresh_devices_table(self):
        self._build_devices_table_headers()
        for r, resource_key in enumerate(sorted(self.sessions.keys()), start=1):
            info = self.sessions[resource_key]
            idn = info.get("idn", "")
            t_default = info.get("label_type", "")
            n_default = info.get("label_num", "No Number")
            combined = info.get("label", "")

            tk.Label(self.device_table, text=str(r), borderwidth=1, relief="solid", padx=4, pady=2, anchor="w").grid(row=r, column=0, sticky="nsew")

            type_var = tk.StringVar(value=t_default)
            type_cb = ttk.Combobox(self.device_table, textvariable=type_var, values=LABEL_TYPES, state="readonly", width=12)
            type_cb.grid(row=r, column=1, sticky="nsew")

            num_var = tk.StringVar(value=n_default if n_default in LABEL_NUMBERS else "No Number")
            num_cb = ttk.Combobox(self.device_table, textvariable=num_var, values=LABEL_NUMBERS, state="readonly", width=10)
            num_cb.grid(row=r, column=2, sticky="nsew")

            label_var = tk.StringVar(value=combined)
            lbl = tk.Label(self.device_table, textvariable=label_var, borderwidth=1, relief="solid", padx=6, pady=2, anchor="w")
            lbl.grid(row=r, column=3, sticky="nsew")

            tk.Label(self.device_table, text=resource_key, borderwidth=1, relief="solid", padx=6, pady=2, anchor="w").grid(row=r, column=4, sticky="nsew")
            tk.Label(self.device_table, text=idn, borderwidth=1, relief="solid", padx=6, pady=2, anchor="w").grid(row=r, column=5, sticky="nsew")

            def _apply_change(*_, rk=resource_key, tvar=type_var, nvar=num_var, lvar=label_var):
                t = trim(tvar.get())
                n = trim(nvar.get())
                comb = combine_label(t, n)
                lvar.set(comb)
                self.sessions[rk]["label_type"] = t
                self.sessions[rk]["label_num"] = n if n in LABEL_NUMBERS else "No Number"
                self.sessions[rk]["label"] = comb
                if rk == self.connected_resource:
                    self._update_idn_banner()
                self._check_labels_filled()

            type_var.trace_add("write", _apply_change)
            num_var.trace_add("write", _apply_change)

            self.device_rows.append({
                "resource": resource_key,
                "type_var": type_var,
                "num_var": num_var,
                "label_var": label_var,
            })

        self._check_labels_filled()

    def _check_labels_filled(self):
        if not self.device_rows:
            self.create_btn.config(state="disabled")
            return
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
                        inst.write_termination = wterm
                    if hasattr(inst, "read_termination"):
                        inst.read_termination = rterm
                    try:
                        inst.write("")
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

        if sel in self.sessions:
            self.connected_resource = sel
            self.inst = self.sessions[sel]["inst"].inst
            self._update_idn_banner()
            self.status.set("Activated existing connection.")
            self._log(f"[ACTIVATE] {sel}")
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

            self.sessions[sel] = {
                "inst": dev, "idn": idn,
                "label": "",
                "label_type": "",
                "label_num": "No Number",
            }
            self.connected_resource = sel
            self.inst = dev.inst
            self._update_idn_banner()
            self._log(f"[CONNECT] Connected {sel}  IDN: {idn or '(no response)'}")
            self.status.set("Connected.")
            self._refresh_devices_table()
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

                if not self.connected_resource:
                    self.connected_resource = resource_key
                    self.inst = dev.inst
                    self.resource_var.set(resource_key)
                    self._update_idn_banner()
            except Exception as e:
                self._log(f"[ERROR] Failed to connect {resource_key}: {e}")

        self.status.set(f"Connected {connected_count} device(s).")
        self._refresh_devices_table()
        self._busy(False, "Ready.")

    def disconnect_current(self):
        try:
            if self.inst and self.connected_resource:
                res = self.connected_resource
                try:
                    self.inst.close()
                except Exception:
                    pass
                if res in self.sessions:
                    try:
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

    # ---------- PSU quick controls ----------
    def _psu_require_connected_ps(self):
        if not self._check_connected():
            return False
        try:
            info = self.sessions.get(self.connected_resource, {})
            if info.get("label_type", "") != "ps":
                self._log("[INFO] Active device is not labeled as 'ps'. Proceeding anyway.")
        except Exception:
            pass
        return True

    def _psu_map_channel_for_e3631a(self, ch: str) -> Optional[str]:
        c = trim(ch).upper()
        return _E3631A_CHANNELS.get(c, None)

    def _psu_select_channel_generic(self, ch: str):
        n = trim(ch).upper().replace("CH", "")
        if not n.isdigit():
            raise ValueError("Channel must be numeric for this PSU profile.")
        self.inst.write(f"INST:NSEL {n}")

    def _psu_readback_generic(self, ch: str):
        self._psu_select_channel_generic(ch)
        v = self.inst.query("VOLT?").strip()
        i = self.inst.query("CURR?").strip()
        return v, i

    def _psu_set_generic(self, ch: str, volt: Optional[str], curr: Optional[str]):
        self._psu_select_channel_generic(ch)
        cmds = []
        if volt is not None and volt != "":
            v = _format_float(volt)
            cmds.append(f"VOLT {v}")
        if curr is not None and curr != "":
            c = _format_float(curr)
            cmds.append(f"CURR {c}")
        if not cmds:
            raise ValueError("Provide at least one of Voltage or Current.")
        for c in cmds:
            self.inst.write(c)
            self._log(f"[PSU/GENERIC] {c}")

    def _psu_readback_e3631a(self, ch: str):
        out = self._psu_map_channel_for_e3631a(ch)
        if not out:
            raise ValueError("E3631A channel must be one of P6V/P25V/N25V or 1/2/3.")
        resp = self.inst.query(f"APPLy? {out}").strip()
        try:
            v, i = resp.split(",")
            return v.strip().strip('"'), i.strip().strip('"')
        except Exception:
            return resp, ""

    def _psu_set_e3631a(self, ch: str, volt: Optional[str], curr: Optional[str]):
        out = self._psu_map_channel_for_e3631a(ch)
        if not out:
            raise ValueError("E3631A channel must be one of P6V/P25V/N25V or 1/2/3.")

        v_to_set = None
        i_to_set = None
        if (volt is None or volt == "") or (curr is None or curr == ""):
            v_now, i_now = self._psu_readback_e3631a(out)
            if v_now != "":
                v_to_set = v_now
            if i_now != "":
                i_to_set = i_now

        if volt is not None and volt != "":
            v_to_set = _format_float(volt)
        if curr is not None and curr != "":
            i_to_set = _format_float(curr)

        if v_to_set is None and i_to_set is None:
            raise ValueError("Provide at least one of Voltage or Current.")

        if v_to_set is None:
            v_to_set = "DEF"
        if i_to_set is None:
            i_to_set = "DEF"

        cmd = f"APPLy {out},{v_to_set},{i_to_set}"
        self.inst.write(cmd)
        self._log(f"[PSU/E3631A] {cmd}")

    def psu_set_voltage(self):
        if not self._psu_require_connected_ps():
            return
        ch = self.psu_channel_var.get()
        v = self.psu_voltage_var.get()
        if not trim(v):
            messagebox.showinfo("Missing voltage", "Enter Voltage (V).")
            return
        try:
            if self.psu_profile == "E3631A":
                self._psu_set_e3631a(ch, volt=v, curr=None)
            else:
                self._psu_set_generic(ch, volt=v, curr=None)
            self.status.set("PSU voltage set.")
        except Exception as e:
            messagebox.showerror("PSU Set Voltage failed", str(e))

    def psu_set_current(self):
        if not self._psu_require_connected_ps():
            return
        ch = self.psu_channel_var.get()
        i = self.psu_current_var.get()
        if not trim(i):
            messagebox.showinfo("Missing current", "Enter Current limit (A).")
            return
        try:
            if self.psu_profile == "E3631A":
                self._psu_set_e3631a(ch, volt=None, curr=i)
            else:
                self._psu_set_generic(ch, volt=None, curr=i)
            self.status.set("PSU current limit set.")
        except Exception as e:
            messagebox.showerror("PSU Set Current failed", str(e))

    def psu_set_both(self):
        if not self._psu_require_connected_ps():
            return
        ch = self.psu_channel_var.get()
        v = self.psu_voltage_var.get()
        i = self.psu_current_var.get()
        if not trim(v) and not trim(i):
            messagebox.showinfo("Missing values", "Enter Voltage and/or Current.")
            return
        try:
            if self.psu_profile == "E3631A":
                self._psu_set_e3631a(ch, volt=v if trim(v) else None, curr=i if trim(i) else None)
            else:
                self._psu_set_generic(ch, volt=v if trim(v) else None, curr=i if trim(i) else None)
            self.status.set("PSU voltage/current set.")
        except Exception as e:
            messagebox.showerror("PSU Set Both failed", str(e))

    def psu_read_back(self):
        if not self._psu_require_connected_ps():
            return
        ch = self.psu_channel_var.get()
        try:
            if self.psu_profile == "E3631A":
                v, i = self._psu_readback_e3631a(ch)
            else:
                v, i = self._psu_readback_generic(ch)
            self._log(f"[PSU/READ] CH={ch}  V={v}  I={i}")
            self.status.set("PSU read-back done.")
        except Exception as e:
            messagebox.showerror("PSU Read Back failed", str(e))

    # ---------- script generation ----------
    @staticmethod
    def _sanitize_label(name: str) -> str:
        name = trim(name)
        if not name:
            return ""
        safe = re.sub(r"\W", "_", name)
        if re.match(r"^\d", safe):
            safe = "_" + safe
        return safe

    @staticmethod
    def _resource_to_value(resource: str) -> str:
        m = re.match(r"^ASRL(\d+)", resource.strip(), flags=re.IGNORECASE)
        if m:
            return f"COM{m.group(1)}"
        return resource

    def create_scripts(self):
        labels = []
        items = []
        dict_entries = []

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

            key = t.upper()
            if n and n != "No Number":
                key = f"{key}{n}"
            dict_entries.append((t, n, key))

        dups = {x for x in labels if labels.count(x) > 1}
        if dups:
            messagebox.showerror("Duplicate labels", f"Labels must be unique. Duplicates: {', '.join(sorted(dups))}")
            return

        lines = []
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        lines.append("# Auto-generated by General SCPI GUI")
        lines.append(f"# Generated: {ts}")
        lines.append("")
        lines.append("class TemplateConnection:")
        lines.append("    def __init__(self):")

        for label, resource in items:
            value = self._resource_to_value(resource)
            lines.append(f"        self.{label} = ('{value}')")

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

        grouped = {}
        for t, n, key in dict_entries_sorted:
            grouped.setdefault(t, []).append(key)

        if dict_entries_sorted:
            max_key_len = max(len(k) for _, _, k in dict_entries_sorted)
            def fmt_token(k: str) -> str:
                pad = " " * (max_key_len - len(k))
                return f"'{k}'{pad} : ['X']"

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

if __name__ == "__main__":
    app = GeneralSCPIGUI()
    app.mainloop()
