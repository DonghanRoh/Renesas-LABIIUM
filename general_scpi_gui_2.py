# general_scpi_gui.py
# Row-click activation + model-aware PSU panel between General SCPI and Log
# Supports: E3631A (P6V/P25V/N25V), HMP4040 (1..4), HMP4030 (1..3), HM8143 (U1/U2)
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

        # ---- 저장 디렉토리 변수 추가 ----
        self.save_dir_var = tk.StringVar(value=os.getcwd())

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

        # ---- 저장 경로 선택 UI ----
        ttk.Label(toolbar, text="Save Dir:").pack(side="left", padx=(0, 4))
        ttk.Entry(toolbar, textvariable=self.save_dir_var, width=40).pack(side="left", padx=(0, 4))
        ttk.Button(toolbar, text="Browse...", command=self.browse_save_dir).pack(side="left")

        self.create_btn = ttk.Button(toolbar, text="Create Scripts", command=self.create_scripts, state="disabled")
        self.create_btn.pack(side="right")

        self.device_table = ttk.Frame(devicesf)
        self.device_table.pack(fill="x", padx=6, pady=6)
        self._build_devices_table_headers()

        # ----- General SCPI -----
        # (기존 코드 그대로 유지 — DMM/SMU 버튼 포함)

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

        # Add only the log by default
        self.paned.add(self.logf, weight=1)

        # Status bar
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

    # ---------- browse save dir ----------
    def browse_save_dir(self):
        path = filedialog.askdirectory(initialdir=self.save_dir_var.get() or os.getcwd())
        if path:
            self.save_dir_var.set(path)
            self._log(f"[SET] Save directory -> {path}")

    # ---------- devices table ----------
    def _build_devices_table_headers(self):
        for w in self.device_table.winfo_children(): 
            w.destroy()
        self.device_rows = []

        headers = ["#", "Type", "No.", "Label", "VISA Resource", "IDN"]
        for c, text in enumerate(headers):
            lbl = tk.Label(self.device_table, text=text, borderwidth=1, relief="solid",
                           padx=6, pady=4, anchor="w", font=("TkDefaultFont", 9, "bold"))
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

            row_widgets = []
            row_widgets.append(self._make_clickable_cell(str(r), r, 0, resource_key))

            # ---- Type (drop-down, 선택 전용) ----
            type_var = tk.StringVar(value=t_default)
            type_cb = ttk.Combobox(self.device_table, textvariable=type_var, values=LABEL_TYPES, state="readonly", width=12)
            type_cb.grid(row=r, column=1, sticky="nsew")
            type_cb.bind("<Button-1>", lambda e, rk=resource_key: self._activate_resource(rk))
            type_cb.bind("<<ComboboxSelected>>", lambda e, rk=resource_key: self._activate_resource(rk))

            # ---- No. (drop-down, 선택 전용) ----
            num_var = tk.StringVar(value=n_default if n_default in LABEL_NUMBERS else "No Number")
            num_cb = ttk.Combobox(self.device_table, textvariable=num_var, values=LABEL_NUMBERS, state="readonly", width=10)
            num_cb.grid(row=r, column=2, sticky="nsew")
            num_cb.bind("<Button-1>", lambda e, rk=resource_key: self._activate_resource(rk))
            num_cb.bind("<<ComboboxSelected>>", lambda e, rk=resource_key: self._activate_resource(rk))

            # ---- Label (Entry: 입력만 가능) ----
            label_var = tk.StringVar(value=combined)
            entry = ttk.Entry(self.device_table, textvariable=label_var)
            entry.grid(row=r, column=3, sticky="nsew")
            entry.bind("<FocusIn>", lambda e, rk=resource_key: self._activate_resource(rk))
            row_widgets.append(entry)

            # VISA Resource / IDN (클릭 활성화 가능)
            row_widgets.append(self._make_clickable_cell(resource_key, r, 4, resource_key))
            row_widgets.append(self._make_clickable_cell(idn, r, 5, resource_key))

            # ---- Label 자동 생성 / 사용자 입력 반영 ----
            def _apply_change(*_, rk=resource_key, tvar=type_var, nvar=num_var, lvar=label_var):
                t = trim(tvar.get())
                n = trim(nvar.get())
                user_label = trim(lvar.get())

                auto_label = combine_label(t, n)
                label_final = user_label if user_label else auto_label

                lvar.set(label_final)
                self.sessions[rk]["label_type"] = t
                self.sessions[rk]["label_num"] = n if n in LABEL_NUMBERS else "No Number"
                self.sessions[rk]["label"] = label_final
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
        self._update_psu_panel()

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
                messagebox.showerror("Invalid label", "All rows must have a Type selected.")
                return
            labels.append(label); items.append((label, row["resource"]))
            key = t.upper()
            if n and n != "No Number": key = f"{key}{n}"
            dict_entries.append((t, n, key))

        dups = {x for x in labels if labels.count(x) > 1}
        if dups:
            messagebox.showerror("Duplicate labels", f"Labels must be unique. Duplicates: {', '.join(sorted(dups))}")
            return

        lines = []
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        lines += [
            "# Auto-generated by General SCPI GUI",
            f"# Generated: {ts}",
            "",
            "class TemplateConnection:",
            "    def __init__(self):"
        ]
        for label, resource in items:
            value = self._resource_to_value(resource)
            lines.append(f"        self.{label} = ('{value}')")

        def _num_val(num_str: str) -> int:
            if num_str and num_str != "No Number":
                try: return int(num_str)
                except ValueError: return 0
            return 0

        dict_entries_sorted = sorted(
            dict_entries,
            key=lambda x: (TYPE_PRIORITY.get(x[0], 999), _num_val(x[1]), x[2])
        )
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
                if t not in grouped:
                    continue
                width = ALIGN_WIDTHS.get(t, 10)
                row_parts = []
                for k in grouped[t]:
                    pad = " " * (width - len(k))
                    row_parts.append(f"'{k}'{pad}: ['X']")
                if lines[-1].endswith("{"):
                    lines[-1] += row_parts[0] + (
                        "," if len(row_parts) == 1 else ", " + ", ".join(row_parts[1:]) + ","
                    )
                else:
                    lines.append(
                        extra_indent + row_parts[0] + (
                            "," if len(row_parts) == 1 else ", " + ", ".join(row_parts[1:]) + ","
                        )
                    )
            lines[-1] = lines[-1].rstrip(",")
            lines[-1] += "}"

        content = "\n".join(lines) + "\n"

        # ---- 저장 경로 반영 ----
        save_dir = self.save_dir_var.get() or os.getcwd()
        out_path = os.path.join(save_dir, "template_connection.py")

        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(content)
            self._log(f"[SCRIPT] Wrote {out_path}")
            messagebox.showinfo("Success", f"Created {out_path}")
        except Exception as e:
            messagebox.showerror("Write failed", f"Could not create template_connection.py:\n{e}")

    # ---------- helpers ----------
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

    # ---------- event loop ----------
    def mainloop(self, n=0):
        self._update_psu_panel()
        super().mainloop(n)


if __name__ == "__main__":
    app = GeneralSCPIGUI()
    app.mainloop()
