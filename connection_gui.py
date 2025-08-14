# hmp4040_gui_all_connect_minimal.py
import tkinter as tk
from tkinter import ttk, messagebox

import pyvisa
from hmp4040 import hmp4040 as HMP4040Class


# -----------------------------
# Mock instrument for simulation (IDN만 지원)
# -----------------------------
class MockInstrument:
    def write(self, cmd: str):
        pass

    def query(self, cmd: str) -> str:
        cmd = cmd.strip().upper()
        if cmd == "*IDN?":
            return "Rohde&Schwarz,HMP4040,Mock,1.00"
        return ""

    def close(self):
        pass


# -----------------------------
# Minimal GUI: scan/connect/list/log
# -----------------------------
class HMP4040GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HMP4040 Control GUI (minimal)")
        self.geometry("900x500")

        self.rm = None
        self.sessions = {}
        self.scanned_resources = []
        self.current_resource_key = None
        self.current_idn = None

        self.simulated = tk.BooleanVar(value=False)
        self.sel_label_var = tk.StringVar(value="")

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        # Top: Connection
        topbar = ttk.LabelFrame(self, text="Connection")
        topbar.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Checkbutton(topbar, text="Simulated", variable=self.simulated,
                        command=self._on_toggle_sim).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(topbar, text="Scan", command=self.scan_resources).grid(row=0, column=1, padx=6, pady=6, sticky="w")
        ttk.Button(topbar, text="Connect All", command=self.connect_all).grid(row=0, column=2, padx=6, pady=6, sticky="w")

        self.idn_label = ttk.Label(topbar, text="[IDN] - Not connected")
        self.idn_label.grid(row=0, column=3, padx=6, pady=6, sticky="w")

        # Devices table
        devf = ttk.LabelFrame(self, text="Devices (scanned & connected)")
        devf.pack(fill="both", expand=False, padx=10, pady=(10, 10))

        columns = ("resource", "idn", "label")
        self.dev_tree = ttk.Treeview(devf, columns=columns, show="headings", height=6)
        self.dev_tree.heading("resource", text="VISA Resource")
        self.dev_tree.heading("idn", text="IDN")
        self.dev_tree.heading("label", text="Label")
        self.dev_tree.column("resource", width=250, anchor="w")
        self.dev_tree.column("idn", width=350, anchor="w")
        self.dev_tree.column("label", width=200, anchor="w")
        self.dev_tree.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self.dev_tree.bind("<<TreeviewSelect>>", self._on_tree_selection)

        editor = ttk.Frame(devf)
        editor.pack(fill="x", padx=6, pady=(6, 6))
        ttk.Label(editor, text="Label for selected:").grid(row=0, column=0, padx=(0, 6), pady=4, sticky="e")
        self.sel_label_entry = ttk.Entry(editor, textvariable=self.sel_label_var, width=40)
        self.sel_label_entry.grid(row=0, column=1, padx=(0, 6), pady=4, sticky="we")
        ttk.Button(editor, text="Save Label", command=self._save_selected_label).grid(row=0, column=2, padx=6, pady=4)
        editor.grid_columnconfigure(1, weight=1)

        # Log with Clear Log
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_toolbar = ttk.Frame(logf)
        log_toolbar.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(log_toolbar, text="Clear Log", command=self.clear_log).pack(side="right")

        self.log = tk.Text(logf, height=12)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

        self._on_toggle_sim()

    # ---------- helpers ----------
    def _busy(self, on=True, msg=None):
        self.config(cursor="watch" if on else "")
        if msg:
            self.status.set(msg)
        self.update_idletasks()

    def log_line(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def clear_log(self):
        self.log.delete("1.0", "end")
        self.status.set("Log cleared.")

    def _update_idn_banner(self):
        if self.current_resource_key and self.current_resource_key in self.sessions:
            info = self.sessions[self.current_resource_key]
            label = info.get("label") or ""
            idn = info.get("idn") or ""
            base = f"[IDN] {idn} ({self.current_resource_key})"
            self.idn_label.config(text=(f"{label} | {base}" if label else base))
        else:
            self.idn_label.config(text="[IDN] - Not connected")

    def _on_toggle_sim(self, *_):
        self.status.set("Simulated mode ON" if self.simulated.get() else "Simulated mode OFF")

    def _on_tree_selection(self, event=None):
        sel = self.dev_tree.selection()
        if not sel:
            return
        key = sel[0]
        if key in self.sessions:
            self.current_resource_key = key
            self.current_idn = self.sessions[key].get("idn", "")
            self.sel_label_var.set(self.sessions[key].get("label", ""))
            self._update_idn_banner()

    def _save_selected_label(self):
        sel = self.dev_tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Please select a device in the table first.")
            return
        key = sel[0]
        if key not in self.sessions:
            return
        new_label = (self.sel_label_var.get() or "").strip()
        self.sessions[key]["label"] = new_label
        vals = list(self.dev_tree.item(key, "values"))
        if len(vals) == 3:
            vals[2] = new_label
            self.dev_tree.item(key, values=vals)
        if key == self.current_resource_key:
            self._update_idn_banner()

    # ---------- connection ----------
    def scan_resources(self):
        try:
            self._busy(True, "Scanning VISA resources...")
            if self.simulated.get():
                self.scanned_resources = [f"SIMULATED{i}" for i in range(1, 4)]
            else:
                self.rm = self.rm or pyvisa.ResourceManager()
                self.scanned_resources = list(self.rm.list_resources())
            if not self.scanned_resources:
                self.status.set("No VISA resources found.")
                self.log_line("[SCAN] No VISA resources found.")
            else:
                self.status.set(f"Found {len(self.scanned_resources)} resource(s).")
                self.log_line(f"[SCAN] {len(self.scanned_resources)} resource(s) found:")
                for r in self.scanned_resources:
                    self.log_line(f"  - {r}")
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))
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
                if resource_key.startswith("SIMULATED"):
                    inst = MockInstrument()
                else:
                    self.rm = self.rm or pyvisa.ResourceManager()
                    inst = self.rm.open_resource(resource_key)
                    try:
                        inst.timeout = 1000
                        inst.write_timeout = 1000
                        inst.read_termination = "\n"
                        inst.write_termination = "\n"
                    except Exception:
                        pass

                idn = inst.query("*IDN?").strip()
                wrapper = HMP4040Class(pyvisa_instr=inst)

                self.sessions[resource_key] = {
                    "inst": inst,
                    "wrapper": wrapper,
                    "idn": idn,
                    "label": "",
                }
                self.dev_tree.insert("", "end", iid=resource_key, values=(resource_key, idn, ""))
                self.log_line(f"[INFO] Connected: {idn} ({resource_key})")
                connected_count += 1
            except Exception as e:
                self.log_line(f"[ERROR] Failed to connect {resource_key}: {e}")

        if connected_count and not self.current_resource_key:
            first = self.dev_tree.get_children()
            if first:
                self.dev_tree.selection_set(first[0])
                self.dev_tree.focus(first[0])
                self._on_tree_selection()

        self.status.set(f"Connected {connected_count} device(s).")
        self._busy(False, "Ready.")


if __name__ == "__main__":
    app = HMP4040GUI()
    app.mainloop()
