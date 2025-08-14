# general_scpi_gui.py
# Revised: adopt connection pattern from connection_gui.py
# - Robust ASRL(serial) open with baud/termination trials
# - Standard open for non-serial resources
# - Clean handling of read/write terminations as literal "\n" etc.

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

class DeviceShell:
    """Lightweight holder for a PyVISA instrument."""
    def __init__(self, pyvisa_instr):
        self.inst = pyvisa_instr

class GeneralSCPIGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("General SCPI GUI (PyVISA)")
        self.geometry("980x700")

        # VISA / connection state
        self.rm = None
        self.sessions = {}           # resource_key -> {"inst": DeviceShell, "idn": str, "label": str}
        self.scanned_resources = []  # list of strings
        self.connected_resource = None  # currently "active" resource key
        self.inst = None                # currently active pyvisa instrument

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        conn = ttk.LabelFrame(self, text="Connection")
        conn.pack(fill="x", padx=10, pady=(10, 8))

        ttk.Button(conn, text="Scan VISA", command=self.scan_resources).grid(row=0, column=0, padx=6, pady=8)
        ttk.Label(conn, text="Resource:").grid(row=0, column=1, padx=(12, 6), pady=8, sticky="e")

        self.resource_var = tk.StringVar()
        self.resource_combo = ttk.Combobox(conn, textvariable=self.resource_var, width=42, state="readonly")
        self.resource_combo.grid(row=0, column=2, padx=(0, 6), pady=8, sticky="w")

        ttk.Button(conn, text="Connect Selected", command=self.connect_selected).grid(row=0, column=3, padx=6, pady=8)
        ttk.Button(conn, text="Connect All", command=self.connect_all).grid(row=0, column=4, padx=6, pady=8)
        ttk.Button(conn, text="Disconnect", command=self.disconnect_current).grid(row=0, column=5, padx=6, pady=8)

        self.idn_label = ttk.Label(conn, text="[IDN] - Not connected")
        self.idn_label.grid(row=1, column=0, columnspan=6, padx=6, pady=(0, 8), sticky="w")

        # Simple label editor for current connection (optional convenience)
        labelf = ttk.Frame(conn)
        labelf.grid(row=2, column=0, columnspan=6, sticky="we", padx=6, pady=(0, 8))
        ttk.Label(labelf, text="Label (current):").pack(side="left", padx=(0, 6))
        self.cur_label_var = tk.StringVar(value="")
        self.cur_label_entry = ttk.Entry(labelf, textvariable=self.cur_label_var, width=32)
        self.cur_label_entry.pack(side="left")
        ttk.Button(labelf, text="Save Label", command=self._save_current_label).pack(side="left", padx=6)

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
        else:
            self.idn_label.config(text="[IDN] - Not connected")

    def _save_current_label(self):
        key = self.connected_resource
        if not key or key not in self.sessions:
            messagebox.showinfo("No active device", "Connect to a device first.")
            return
        new_label = (self.cur_label_var.get() or "").strip()
        self.sessions[key]["label"] = new_label
        self._update_idn_banner()

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
            self.cur_label_var.set(self.sessions[sel].get("label", ""))
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

            # store session and activate
            self.sessions[sel] = {"inst": dev, "idn": idn, "label": ""}
            self.connected_resource = sel
            self.inst = dev.inst
            self.cur_label_var.set("")
            self.idn_label.config(text=f"[IDN] {idn or '(no response)'}  ({sel})")
            self._log(f"[CONNECT] Connected {sel}  IDN: {idn or '(no response)'}")
            self.status.set("Connected.")
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

                self.sessions[resource_key] = {"inst": dev, "idn": idn, "label": ""}
                self._log(f"[INFO] Connected: {idn} ({resource_key})")
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

if __name__ == "__main__":
    app = GeneralSCPIGUI()
    app.mainloop()
