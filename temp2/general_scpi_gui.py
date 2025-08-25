# general_scpi_gui.py
# Refactored: Tab UIs split into scpi_tabs/* modules and imported here.
# Keeps: Connection, Devices table, General SCPI panel incl. DMM/SMU/PSU label buttons, Script generation

import os
import re
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import pyvisa
from pyvisa import constants as pv  # parity/stopbits constants

from scpi_tabs import (
    PowerSupplyTab, MultiMeterTab, SourceMonitorUnitTab, FunctionGeneratorTab, common
)

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

LABEL_TYPES = ["ps", "mm", "smu", "fgen", "scope", "eload", "na", "tm", "temp_force"]
LABEL_NUMBERS = ["No Number", "1", "2", "3", "4", "5"]
TYPE_PRIORITY = {t: i for i, t in enumerate(["ps", "mm", "smu", "fgen", "scope", "eload", "na", "tm", "temp_force"])}

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
        self.geometry("1200x1000")

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

        # Script save dir & file name
        self.save_dir_var = tk.StringVar(value=os.getcwd())
        self.save_filename_var = tk.StringVar(value="template_connection.py")

        # Notebook / Tabs
        self.notebook = None
        self.log_tab = None

        # Tabs (modular)
        self.psu_tab = None
        self.dmm_tab = None
        self.smu_tab = None
        self.fgen_tab = None

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

        # DMM/SMU/PSU label controls
        ttk.Label(cmdf, text="DMM Display:").grid(row=2, column=0, padx=6, pady=(0, 8), sticky="e")
        dmm_btns = ttk.Frame(cmdf)
        dmm_btns.grid(row=2, column=1, columnspan=2, padx=(0, 8), pady=(0, 8), sticky="w")
        ttk.Button(dmm_btns, text="Show Label", command=self.dmm_show_label).grid(row=0, column=0, padx=(0, 8), pady=0, sticky="w")
        ttk.Button(dmm_btns, text="Clear", command=self.dmm_clear_label).grid(row=0, column=1, pady=0, sticky="w")

        ttk.Separator(cmdf, orient="vertical").grid(row=2, column=3, sticky="ns", padx=12, pady=(0, 8))

        ttk.Label(cmdf, text="SMU Display:").grid(row=2, column=4, padx=6, pady=(0, 8), sticky="e")
        ttk.Button(cmdf, text="Show Label", command=self.smu_show_label).grid(row=2, column=5, padx=(0, 8), pady=(0, 8), sticky="w")
        ttk.Button(cmdf, text="Clear", command=self.smu_clear_label).grid(row=2, column=6, padx=(0, 8), pady=(0, 8), sticky="w")

        ttk.Label(cmdf, text="PSU Display:").grid(row=3, column=0, padx=6, pady=(0, 8), sticky="e")
        psu_btns = ttk.Frame(cmdf)
        psu_btns.grid(row=3, column=1, columnspan=2, padx=(0, 8), pady=(0, 8), sticky="w")
        ttk.Button(psu_btns, text="Show Label", command=self.psu_show_label_text).grid(row=0, column=0, padx=(0, 8), pady=0, sticky="w")
        ttk.Button(psu_btns, text="Clear", command=self.psu_clear_label_text).grid(row=0, column=1, pady=0, sticky="w")

        # ----- Notebook + Tabs (imported) -----
        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        # Log tab
        self.log_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.log_tab, text="Log")
        self.logf = ttk.LabelFrame(self.log_tab, text="Log")
        log_toolbar = ttk.Frame(self.logf)
        log_toolbar.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(log_toolbar, text="Clear Log", command=self.clear_log).pack(side="right")
        self.log = tk.Text(self.logf, height=18)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)
        self.logf.pack(fill="both", expand=True, padx=0, pady=0)

        # Import된 탭 클래스 생성
        self.psu_tab = PowerSupplyTab(
            notebook=self.notebook,
            get_inst=lambda: self.inst,
            get_idn=self._active_idn,
            log_fn=self._log,
            status_var=tk.StringVar()  # status는 메인 status와 별개; 필요시 연결 가능
        )
        self.dmm_tab = MultiMeterTab(
            notebook=self.notebook,
            get_inst=lambda: self.inst,
            get_idn=self._active_idn,
            log_fn=self._log,
            status_var=tk.StringVar()
        )
        self.smu_tab = SourceMonitorUnitTab(
            notebook=self.notebook,
            get_inst=lambda: self.inst,
            get_idn=self._active_idn,
            log_fn=self._log,
            status_var=tk.StringVar()
        )
        self.fgen_tab = FunctionGeneratorTab(
            notebook=self.notebook,
            get_inst=lambda: self.inst,
            get_idn=self._active_idn,
            log_fn=self._log,
            status_var=tk.StringVar()
        )

        # Status bar
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

        # 초기 상태 업데이트
        self._update_all_tabs()

    # ---------- helpers ----------
    def _set_tab_enabled(self, tab_frame, enabled: bool):
        try:
            self.notebook.tab(tab_frame, state=("normal" if enabled else "disabled"))
        except Exception:
            pass

    def _active_idn(self) -> str:
        if self.connected_resource and self.connected_resource in self.sessions:
            return self.sessions[self.connected_resource].get("idn", "")
        return ""

    def _busy(self, on=True, msg=None):
        self.config(cursor="watch" if on else "")
        if msg: self.status.set(msg)
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

    def _update_all_tabs(self):
        self.psu_tab.update_for_active_device()
        self.dmm_tab.update_for_active_device()
        self.smu_tab.update_for_active_device()
        self.fgen_tab.update_for_active_device()

    # ---------- devices table ----------
    def _build_devices_table_headers(self):
        for w in self.device_table.winfo_children(): w.destroy()
        self.device_rows = []
        headers = ["#", "Type", "No.", "Label", "VISA Resource", "IDN"]
        for c, text in enumerate(headers):
            lbl = tk.Label(self.device_table, text=text, borderwidth=1, relief="solid",
                           padx=6, pady=4, anchor="w", font=("TkDefaultFont", 9, "bold"))
            lbl.grid(row=0, column=c, sticky="nsew")
        for c, weight in enumerate([0, 1, 0, 1, 2, 3]):
            self.device_table.grid_columnconfigure(c, weight=weight)

    def _activate_resource(self, resource_key: str):
        if resource_key not in self.sessions:
            messagebox.showinfo("Not connected", "This resource is not connected.")
            return
        self.connected_resource = resource_key
        self.inst = self.sessions[resource_key]["inst"].inst
        self._update_idn_banner()
        self._log(f"[ACTIVATE] {resource_key}")
        self.status.set("Activated.")
        self._refresh_row_highlights()
        self._update_all_tabs()

    def _refresh_row_highlights(self):
        for row in self.device_rows:
            widgets = row.get("widgets", [])
            bg = self._row_active_bg if row["resource"] == self.connected_resource else self._row_default_bg
            for w in widgets:
                try: w.config(bg=bg)
                except Exception: pass

    def _make_clickable_cell(self, text, r, c, resource_key):
        lbl = tk.Label(self.device_table, text=text, borderwidth=1, relief="solid", padx=6, pady=2, anchor="w")
        if self._row_default_bg is None:
            self._row_default_bg = lbl.cget("bg")
        lbl.bind("<Button-1>", lambda e, rk=resource_key: self._activate_resource(rk))
        lbl.grid(row=r, column=c, sticky="nsew")
        return lbl

    def _refresh_devices_table(self):
        self._build_devices_table_headers()
        for r, resource_key in enumerate(sorted(self.sessions.keys()), start=1):
            info = self.sessions[resource_key]
            idn = info.get("idn", "")
            t_default = info.get("label_type", "")
            n_default = info.get("label_num", "No Number")
            combined = info.get("label", "")

            row_widgets = []
            row_widgets.append(self._make_clickable_cell(str(r), r, 0, resource_key))

            type_var = tk.StringVar(value=t_default)
            type_cb = ttk.Combobox(self.device_table, textvariable=type_var, values=LABEL_TYPES, state="readonly", width=12)
            type_cb.grid(row=r, column=1, sticky="nsew")
            type_cb.bind("<Button-1>", lambda e, rk=resource_key: self._activate_resource(rk))
            type_cb.bind("<<ComboboxSelected>>", lambda e, rk=resource_key: self._activate_resource(rk))

            num_var = tk.StringVar(value=n_default if n_default in LABEL_NUMBERS else "No Number")
            num_cb = ttk.Combobox(self.device_table, textvariable=num_var, values=LABEL_NUMBERS, state="readonly", width=10)
            num_cb.grid(row=r, column=2, sticky="nsew")
            num_cb.bind("<Button-1>", lambda e, rk=resource_key: self._activate_resource(rk))
            num_cb.bind("<<ComboboxSelected>>", lambda e, rk=resource_key: self._activate_resource(rk))

            label_var = tk.StringVar(value=combined)
            entry = ttk.Entry(self.device_table, textvariable=label_var)
            entry.grid(row=r, column=3, sticky="nsew")
            entry.bind("<FocusIn>", lambda e, rk=resource_key: self._activate_resource(rk))
            row_widgets.append(entry)

            row_widgets.append(self._make_clickable_cell(resource_key, r, 4, resource_key))
            row_widgets.append(self._make_clickable_cell(idn, r, 5, resource_key))

            def _apply_change(*_, rk=resource_key, tvar=type_var, nvar=num_var, lvar=label_var):
                t = trim(tvar.get())
                n = trim(nvar.get())
                current_label = trim(lvar.get())

                auto_label = combine_label(t, n)

                if not current_label or current_label == self.sessions[rk].get("auto_label", ""):
                    lvar.set(auto_label)
                    self.sessions[rk]["label"] = auto_label
                else:
                    self.sessions[rk]["label"] = current_label

                self.sessions[rk]["auto_label"] = auto_label
                self.sessions[rk]["label_type"] = t
                self.sessions[rk]["label_num"] = n if n in LABEL_NUMBERS else "No Number"

                if rk == self.connected_resource:
                    self._update_idn_banner()
                self._check_labels_filled()

            type_var.trace_add("write", _apply_change)
            num_var.trace_add("write", _apply_change)
            label_var.trace_add("write", _apply_change)

            self.device_rows.append({
                "resource": resource_key,
                "type_var": type_var,
                "num_var": num_var,
                "label_var": label_var,
                "widgets": row_widgets,
            })

        self._check_labels_filled()
        self._refresh_row_highlights()
        self._update_all_tabs()

    def _check_labels_filled(self):
        if not self.device_rows:
            self.create_btn.config(state="disabled"); return
        all_filled = all(trim(row["label_var"].get()) for row in self.device_rows)
        self.create_btn.config(state=("normal" if all_filled else "disabled"))

    # ---------- scanning / connection ----------
    def scan_resources(self):
        try:
            self._busy(True, "Scanning VISA resources...")
            self.rm = self.rm or pyvisa.ResourceManager()
            self.scanned_resources = list(self.rm.list_resources())
            if not self.scanned_resources:
                self.status.set("No VISA resources found.")
                self._log("[SCAN] No VISA resources found.")
                self.resource_combo["values"] = []; self.resource_var.set("")
            else:
                self.status.set(f"Found {len(self.scanned_resources)} resource(s).")
                self._log(f"[SCAN] {len(self.scanned_resources)} resource(s) found:")
                for r in self.scanned_resources: self._log(f"  - {r}")
                self.resource_combo["values"] = self.scanned_resources
                if not self.resource_var.get(): self.resource_var.set(self.scanned_resources[0])
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def _try_open_serial(self, resource_key):
        self.rm = self.rm or pyvisa.ResourceManager()
        baud_candidates = [115200, 38400, 19200, 9600]
        term_candidates = [("\r\n", "\n"), ("\n", "\n"), ("\r", "\r"), ("\r\n", "\r\n")]
        try:
            inst = self.rm.open_resource(resource_key)
        except Exception:
            return None, ""
        try:
            inst.timeout = 500; inst.write_timeout = 500
            inst.data_bits = 8
            inst.parity = getattr(pv.Parity, "none", 0)
            inst.stop_bits = getattr(pv.StopBits, "one", 10)
            if hasattr(inst, "rtscts"): inst.rtscts = False
            if hasattr(inst, "xonxoff"): inst.xonxoff = False
        except Exception:
            pass
        for baud in baud_candidates:
            try:
                if hasattr(inst, "baud_rate"): inst.baud_rate = baud
            except Exception:
                pass
            for wterm, rterm in term_candidates:
                try:
                    if hasattr(inst, "write_termination"): inst.write_termination = wterm
                    if hasattr(inst, "read_termination"):  inst.read_termination  = rterm
                    try: inst.write("")
                    except Exception: pass
                    try: idn = inst.query("*IDN?").strip()
                    except Exception: idn = ""
                    if idn: return DeviceShell(inst), idn
                except Exception:
                    continue
        try: inst.close()
        except Exception: pass
        return None, ""

    def _open_nonserial(self, resource_key):
        self.rm = self.rm or pyvisa.ResourceManager()
        inst = self.rm.open_resource(resource_key)
        try:
            inst.timeout = 1000; inst.write_timeout = 1000
            if hasattr(inst, "read_termination"):  inst.read_termination  = "\n"
            if hasattr(inst, "write_termination"): inst.write_termination = "\n"
        except Exception:
            pass
        return DeviceShell(inst)

    def connect_all(self):
        if not self.scanned_resources:
            messagebox.showinfo("Nothing to connect", "Scan resources first."); return
        self._busy(True, "Connecting to all scanned instruments...")
        connected_count = 0
        for resource_key in self.scanned_resources:
            if resource_key in self.sessions: continue
            try:
                if resource_key.upper().startswith("ASRL"):
                    dev, idn = self._try_open_serial(resource_key)
                    if dev is None:
                        self._log(f"[ERROR] Failed to connect {resource_key}: no response on serial."); continue
                else:
                    dev = self._open_nonserial(resource_key)
                    try: idn = dev.inst.query("*IDN?").strip()
                    except Exception: idn = ""
                self.sessions[resource_key] = {"inst": dev, "idn": idn, "label": "", "label_type": "", "label_num": "No Number"}
                self._log(f"[INFO] Connected: {idn or '(no response)'} ({resource_key})")
                connected_count += 1
                if not self.connected_resource:
                    self._activate_resource(resource_key)
            except Exception as e:
                self._log(f"[ERROR] Failed to connect {resource_key}: {e}")
        self.status.set(f"Connected {connected_count} device(s).")
        self._refresh_devices_table()
        self._busy(False, "Ready.")

    def disconnect_current(self):
        try:
            if self.inst and self.connected_resource:
                res = self.connected_resource
                try: self.inst.close()
                except Exception: pass
                if res in self.sessions:
                    try: self.sessions[res]["inst"].inst.close()
                    except Exception: pass
                    del self.sessions[res]
                self.inst = None; self.connected_resource = None
                self._log(f"[DISCONNECT] Closed {res}")
                self.idn_label.config(text="[IDN] - Not connected")
                self.status.set("Disconnected.")
                self._refresh_devices_table()
                # Disable all tabs
                self.psu_tab.set_enabled(False)
                self.dmm_tab.set_enabled(False)
                self.smu_tab.set_enabled(False)
                self.fgen_tab.set_enabled(False)
            else:
                self.status.set("Nothing to disconnect.")
        except Exception as e:
            messagebox.showerror("Disconnect failed", str(e))

    # ---------- generic SCPI ----------
    def _check_connected(self):
        if not self.inst:
            messagebox.showinfo("Not connected", "Activate a connected device by clicking a cell in the table, or connect devices first.")
            return False
        return True

    def _format_selected_command(self, for_query: bool) -> str:
        tpl = trim(self.cmd_var.get()); param = trim(self.param_var.get())
        if "{param}" in tpl:
            if not param and not tpl.endswith("?"): self._log("[WARN] No parameter provided; sending without value.")
            cmd = tpl.replace("{param}", param)
        else:
            cmd = tpl if (for_query or not param) else f"{tpl} {param}"
        if for_query and not cmd.endswith("?"):
            base_up = cmd.upper().split(" ")[0]
            if base_up in QUERYABLE_BASES: cmd = cmd + "?"
        return cmd

    def do_write(self):
        if not self._check_connected(): return
        cmd = self._format_selected_command(False)
        if cmd.endswith("?"):
            messagebox.showinfo("Use Query", "This looks like a query. Use the Query button."); return
        try:
            self.inst.write(cmd); self._log(f"[WRITE] {cmd}")
        except Exception as e:
            messagebox.showerror("Write failed", str(e))

    def do_query(self):
        if not self._check_connected(): return
        cmd = self._format_selected_command(True)
        if not cmd.endswith("?"):
            messagebox.showinfo("Not a query", "This command is not a query."); return
        try:
            resp = self.inst.query(cmd).strip(); self._log(f"[QUERY] {cmd} -> {resp}")
        except Exception as e:
            messagebox.showerror("Query failed", str(e))

    def custom_write(self):
        if not self._check_connected(): return
        cmd = trim(self.custom_var.get())
        if not cmd:
            messagebox.showinfo("No command", "Enter a custom SCPI command."); return
        if cmd.endswith("?"):
            messagebox.showinfo("Use Query", "Custom command ends with '?'."); return
        try:
            self.inst.write(cmd); self._log(f"[WRITE] {cmd}")
        except Exception as e:
            messagebox.showerror("Write failed", str(e))

    def custom_query(self):
        if not self._check_connected(): return
        cmd = trim(self.custom_var.get())
        if not cmd:
            messagebox.showinfo("No command", "Enter a custom SCPI command."); return
        if not cmd.endswith("?"):
            messagebox.showinfo("Not a query", "Custom query must end with '?'."); return
        try:
            resp = self.inst.query(cmd).strip(); self._log(f"[QUERY] {cmd} -> {resp}")
        except Exception as e:
            messagebox.showerror("Query failed", str(e))

    # ---------- Label display ops (DMM/SMU/PSU) ----------
    def _active_type_num(self):
        if self.connected_resource and self.connected_resource in self.sessions:
            info = self.sessions[self.connected_resource]
            t = trim(info.get("label_type", ""))
            n = trim(info.get("label_num", ""))
            return t, n
        return "", ""

    def dmm_show_label(self):
        try:
            if not self._check_connected(): return
            idn = self._active_idn()
            if not common.is_supported_dmm(idn):
                messagebox.showinfo("Not a supported DMM", "The active device is not a supported DMM.")
                return
            t, n = self._active_type_num()
            if not t:
                messagebox.showinfo("Missing Type", "Select Type in the Devices table (e.g., mm)."); return
            label_text = (t + (n if n and n != "No Number" else "")).strip()
            msg = label_text.replace("'", "''")

            idn_up = (idn or "").upper()
            if "MODEL 2000" in idn_up:
                for c in ["DISP:ENAB ON", f"DISP:TEXT:DATA '{msg}'", "DISP:TEXT:STAT ON"]:
                    self.inst.write(c)
                common.drain_error_queue(self.inst, self._log, "[DMM]")
            else:
                sequences = [
                    [f"DISP:TEXT:STAT ON", f"DISP:TEXT '{msg}'"],
                    [f"DISPlay:TEXT:STATe ON", f"DISPlay:TEXT '{msg}'"],
                    [f"DISP:TEXT '{msg}'"],
                    [f"SYST:DISP:TEXT '{msg}'"],
                    [f"DISP:WIND:TEXT '{msg}'"],
                    [f"DISP:WIND1:TEXT '{msg}'"],
                ]
                common.try_sequences(self.inst, sequences)
                common.drain_error_queue(self.inst, self._log, "[DMM]")
            self._log(f"[DMM] Show Label -> '{label_text}' | IDN={idn}")
            self.status.set("DMM label shown.")
        except Exception as e:
            messagebox.showerror("DMM Show Label failed", str(e))

    def dmm_clear_label(self):
        try:
            if not self._check_connected(): return
            idn = self._active_idn()
            if not common.is_supported_dmm(idn):
                messagebox.showinfo("Not a supported DMM", "The active device is not a supported DMM."); return
            idn_up = (idn or "").upper()
            if "MODEL 2000" in idn_up:
                for c in ["DISP:TEXT:STAT OFF", "DISP:TEXT:DATA ''"]:
                    self.inst.write(c)
                common.drain_error_queue(self.inst, self._log, "[DMM]")
            else:
                sequences = [
                    ["DISP:TEXT:CLEar"], ["DISPlay:TEXT:CLEar"], ["DISP:TEXT ''"],
                    ["DISP:TEXT:STAT OFF"], ["SYST:DISP:TEXT ''"], ["DISP:WIND:TEXT:CLEar"],
                ]
                common.try_sequences(self.inst, sequences)
                common.drain_error_queue(self.inst, self._log, "[DMM]")
            self._log(f"[DMM] Clear Label | IDN={idn}")
            self.status.set("DMM label cleared.")
        except Exception as e:
            messagebox.showerror("DMM Clear Label failed", str(e))

    def smu_show_label(self):
        try:
            if not self._check_connected(): return
            idn = self._active_idn()
            if not common.is_supported_smu(idn):
                messagebox.showinfo("Not a supported SMU", "Supported: Keithley 2420/2440/2450/2460/2461."); return
            t, n = self._active_type_num()
            if not t:
                messagebox.showinfo("Missing Type", "Select Type in the Devices table (e.g., smu)."); return

            label_text = (t + (n if n and n != "No Number" else "")).strip()
            msg = label_text.replace("'", "''")
            idn_up = (idn or "").upper()

            if any(m in idn_up for m in ("2450", "2460", "2461")):
                common.drain_error_queue(self.inst, self._log, "[SMU-2450] PRE")
                self.inst.write("DISP:ENAB ON")
                self.inst.write(f"DISP:USER1:TEXT '{msg}'")
                self.inst.write("DISPlay:SCReen USER")
                common.drain_error_queue(self.inst, self._log, "[SMU-2450] POST")
            elif "2420" in idn_up or "2440" in idn_up:
                sequences = [
                    ["DISP:ENAB ON", f"DISP:WIND:TEXT:DATA '{msg}'", "DISP:WIND:TEXT:STAT ON"],
                    ["DISPlay:ENABle ON", f"DISPlay:WINDow:TEXT:DATA '{msg}'", "DISPlay:WINDow:TEXT:STATe ON"],
                ]
                common.try_sequences(self.inst, sequences)
                common.drain_error_queue(self.inst, self._log, "[SMU-2400]")
            else:
                try:
                    common.drain_error_queue(self.inst, self._log, "[SMU] PRE")
                    self.inst.write("DISP:ENAB ON")
                    self.inst.write(f"DISP:USER1:TEXT '{msg}'")
                    self.inst.write("DISPlay:SCReen USER")
                    common.drain_error_queue(self.inst, self._log, "[SMU] POST")
                except Exception:
                    sequences = [
                        [f"DISP:WIND:TEXT:DATA '{msg}'", "DISP:WIND:TEXT:STAT ON"],
                        [f"DISPlay:WINDow:TEXT:DATA '{msg}'", "DISPlay:WINDow:TEXT:STATe ON"],
                    ]
                    common.try_sequences(self.inst, sequences)
                    common.drain_error_queue(self.inst, self._log, "[SMU] POST-FB")

            self._log(f"[SMU] Show Label -> '{label_text}' | IDN={idn}")
            self.status.set("SMU label shown.")
        except Exception as e:
            messagebox.showerror("SMU Show Label failed", str(e))

    def smu_clear_label(self):
        try:
            if not self._check_connected(): return
            idn = self._active_idn()
            if not common.is_supported_smu(idn):
                messagebox.showinfo("Not a supported SMU", "Supported: Keithley 2420/2440/2450/2460/2461."); return

            idn_up = (idn or "").upper()
            if any(m in idn_up for m in ("2450", "2460", "2461")):
                common.drain_error_queue(self.inst, self._log, "[SMU-2450] PRE")
                self.inst.write("DISP:USER1:TEXT ''")
                self.inst.write("DISPlay:SCReen HOME")
                common.drain_error_queue(self.inst, self._log, "[SMU-2450] POST")
            elif "2420" in idn_up or "2440" in idn_up:
                sequences = [
                    ["DISP:WIND:TEXT:STAT OFF", "DISP:WIND:TEXT:DATA ''"],
                    ["DISPlay:WINDow:TEXT:STATe OFF", "DISPlay:WINDow:TEXT:DATA ''"],
                ]
                common.try_sequences(self.inst, sequences)
                common.drain_error_queue(self.inst, self._log, "[SMU-2400]")
            else:
                try:
                    common.drain_error_queue(self.inst, self._log, "[SMU] PRE")
                    self.inst.write("DISP:USER1:TEXT ''")
                    self.inst.write("DISPlay:SCReen HOME")
                    common.drain_error_queue(self.inst, self._log, "[SMU] POST")
                except Exception:
                    sequences = [
                        ["DISP:WIND:TEXT:STAT OFF", "DISP:WIND:TEXT:DATA ''"],
                        ["DISPlay:WINDow:TEXT:STATe OFF", "DISPlay:WINDow:TEXT:DATA ''"],
                    ]
                    common.try_sequences(self.inst, sequences)
                    common.drain_error_queue(self.inst, self._log, "[SMU] POST-FB")

            self._log(f"[SMU] Clear Label | IDN={idn}")
            self.status.set("SMU label cleared.")
        except Exception as e:
            messagebox.showerror("SMU Clear Label failed", str(e))

    def psu_show_label_text(self):
        try:
            if not self._check_connected(): return
            idn = self._active_idn()
            model = common.detect_psu_model(idn)
            if not model:
                messagebox.showinfo("Not a PSU", "The active device is not a recognized power supply."); return
            t, n = self._active_type_num()
            if not t:
                messagebox.showinfo("Missing Type", "Select Type in the Devices table (e.g., ps)."); return
            label_text = (t + (n if n and n != "No Number" else "")).strip()
            msg = label_text.replace("'", "''")

            # Only E3631A/E3633A label support
            if model not in ("E3631A", "E3633A"):
                messagebox.showwarning("Label Not Supported", f"{model} does not support display text.")
                return

            sequences = [
                ["DISP:TEXT:CLE", f"DISP:TEXT '{msg}'"],
                [f"DISP:TEXT '{msg}'"],
            ]
            common.try_sequences(self.inst, sequences)
            common.drain_error_queue(self.inst, self._log, "[PSU]")
            self._log(f"[PSU] Show Label -> '{label_text}' | IDN={idn}")
            self.status.set("PSU label shown.")
        except Exception as e:
            messagebox.showerror("PSU Show Label failed", str(e))

    def psu_clear_label_text(self):
        try:
            if not self._check_connected(): return
            idn = self._active_idn()
            model = common.detect_psu_model(idn)
            if not model:
                messagebox.showinfo("Not a PSU", "The active device is not a recognized power supply."); return
            if model not in ("E3631A", "E3633A"):
                messagebox.showwarning("Label Not Supported", f"{model} does not support clearing text.")
                return
            sequences = [["DISP:TEXT:CLE"], ["DISP:TEXT ''"]]
            common.try_sequences(self.inst, sequences)
            common.drain_error_queue(self.inst, self._log, "[PSU]")
            self._log(f"[PSU] Clear Label | IDN={idn}")
            self.status.set("PSU label cleared.")
        except Exception as e:
            messagebox.showerror("PSU Clear Label failed", str(e))

    # ---------- script generation ----------
    @staticmethod
    def _sanitize_label(name: str) -> str:
        name = trim(name)
        if not name: return ""
        safe = re.sub(r"\W", "_", name)
        if re.match(r"^\d", safe): safe = "_" + safe
        return safe

    @staticmethod
    def _resource_to_value(resource: str) -> str:
        m = re.match(r"^ASRL(\d+)", resource.strip(), flags=re.IGNORECASE)
        return f"COM{m.group(1)}" if m else resource

    def create_scripts(self):
        labels, items, dict_entries = [], [], []
        for row in self.device_rows:
            label_raw = row["label_var"].get()
            t = trim(row["type_var"].get()); n = trim(row["num_var"].get())
            label = self._sanitize_label(label_raw)
            if not label or not t:
                messagebox.showerror("Invalid label", "All rows must have a Type selected."); return
            labels.append(label); items.append((label, row["resource"]))
            key = t.upper()
            if n and n != "No Number": key = f"{key}{n}"
            dict_entries.append((t, n, key))
        dups = {x for x in labels if labels.count(x) > 1}
        if dups:
            messagebox.showerror("Duplicate labels", f"Labels must be unique. Duplicates: {', '.join(sorted(dups))}"); return

        lines = []
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        lines += ["# Auto-generated by General SCPI GUI", f"# Generated: {ts}", "", "class TemplateConnection:", "    def __init__(self):"]
        for label, resource in items:
            value = self._resource_to_value(resource)
            lines.append(f"        self.{label} = ('{value}')")

        def _num_val(num_str: str) -> int:
            if num_str and num_str != "No Number":
                try: return int(num_str)
                except ValueError: return 0
            return 0

        dict_entries_sorted = sorted(dict_entries, key=lambda x: (TYPE_PRIORITY.get(x[0], 999), _num_val(x[1]), x[2]))
        grouped = {}
        for t, n, key in dict_entries_sorted:
            grouped.setdefault(t, []).append(key)

        if dict_entries_sorted:
            ALIGN_WIDTHS = {
                "ps": 10, "mm": 10, "smu": 10, "fgen": 10,
                "scope": 10, "eload": 11, "na": 10,
                "tm": 10, "temp_force": 11
            }

            lines.append("        self.inst_dict = {")
            base_indent = " " * 10
            extra_indent = base_indent + " " * 16

            for t in ["ps", "mm", "smu", "fgen", "scope", "eload", "na", "tm", "temp_force"]:
                if t not in grouped: continue
                width = ALIGN_WIDTHS.get(t, 10)
                row_parts = []
                for k in grouped[t]:
                    pad = " " * (width - len(k))
                    row_parts.append(f"'{k}'{pad}: ['X']")
                if lines[-1].endswith("{"):
                    lines[-1] += row_parts[0] + ("," if len(row_parts) == 1 else ", " + ", ".join(row_parts[1:]) + ",")
                else:
                    lines.append(extra_indent + row_parts[0] + ("," if len(row_parts) == 1 else ", " + ", ".join(row_parts[1:]) + ","))

            lines[-1] = lines[-1].rstrip(",")
            lines[-1] += "}"

        content = "\n".join(lines) + "\n"

        save_dir = self.save_dir_var.get() or os.getcwd()
        fname_in = trim(self.save_filename_var.get()) or "template_connection.py"
        fname = re.sub(r"[^A-Za-z0-9_.-]", "_", fname_in)
        if not fname.lower().endswith(".py"):
            fname += ".py"
        out_path = os.path.join(save_dir, fname)

        try:
            os.makedirs(save_dir, exist_ok=True)
        except Exception:
            pass

        try:
            with open(out_path, "w", encoding="utf-8") as f: f.write(content)
            self._log(f"[SCRIPT] Wrote {out_path}")
            messagebox.showinfo("Success", f"Created {out_path}")
        except Exception as e:
            messagebox.showerror("Write failed", f"Could not create {fname}:\n{e}")

    # ---------- browse save dir ----------
    def browse_save_dir(self):
        path = filedialog.askdirectory(initialdir=self.save_dir_var.get() or os.getcwd())
        if path:
            self.save_dir_var.set(path)
            self._log(f"[SET] Save directory -> {path}")

    # ---------- event loop ----------
    def mainloop(self, n=0):
        self._update_all_tabs()
        super().mainloop(n)

if __name__ == "__main__":
    app = GeneralSCPIGUI()
    app.mainloop()
