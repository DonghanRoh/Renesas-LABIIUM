# general_scpi_gui.py
# Purpose: One simple, general-purpose SCPI GUI to talk to (any) instruments via PyVISA
# - Single GUI (no per-model panes)
# - Choose VISA resource, connect/disconnect
# - Choose a general SCPI command from a list (e.g., *IDN?, *CLS, *RST, *OPC?, *WAI, *TST?, *ESE, *ESR?, *SRE, *STB?, SYST:ERR?)
# - Optional parameter field for commands that take a value (e.g., *ESE, *SRE)
# - Write and Query buttons
# - Log window
# - Synchronous (no threading/asyncio)
# - Graceful handling for serial (ASRL) ports and VI_ERROR_RSRC_BUSY

import tkinter as tk
from tkinter import ttk, messagebox
import pyvisa
from pyvisa import constants as pv

# ----------------------------- Helpers -----------------------------

def trim(s):
    return (s or "").strip()

# A small registry of commands. If a command needs a parameter, include a
# "{param}" token to be replaced by the GUI's parameter field when writing.
# For queries, include the trailing '?' in the template.
COMMANDS = [
    "*IDN?",      # Identity query
    "*CLS",       # Clear status
    "*RST",       # Reset
    "*OPC?",      # Operation complete query (returns '1' when complete)
    "*WAI",       # Wait to continue
    "*TST?",      # Self-test query
    "*ESE {param}",  # Event status enable (0..255)
    "*ESR?",      # Event status register query
    "*SRE {param}",  # Service request enable (0..255)
    "*STB?",      # Status byte query
    "SYST:ERR?",  # System error queue (most instruments)
]

# Commands that are inherently queries (we may auto-append '?' in Query button if missing)
QUERYABLE_BASES = {"*IDN", "*OPC", "*TST", "*ESR", "*STB", "SYST:ERR"}


class GeneralSCPIGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("General SCPI GUI (PyVISA)")
        self.geometry("980x640")

        self.rm = None
        self.inst = None
        self.connected_resource = None

        self._build_ui()

    # ----------------------------- UI -----------------------------
    def _build_ui(self):
        # Connection block
        conn = ttk.LabelFrame(self, text="Connection")
        conn.pack(fill="x", padx=10, pady=(10, 8))

        ttk.Button(conn, text="Scan VISA", command=self.scan_resources).grid(row=0, column=0, padx=6, pady=8)
        ttk.Label(conn, text="Resource:").grid(row=0, column=1, padx=(12, 6), pady=8, sticky="e")
        self.resource_var = tk.StringVar()
        self.resource_combo = ttk.Combobox(conn, textvariable=self.resource_var, width=40, state="readonly")
        self.resource_combo.grid(row=0, column=2, padx=(0, 6), pady=8, sticky="w")

        ttk.Button(conn, text="Connect", command=self.connect_selected).grid(row=0, column=3, padx=6, pady=8)
        ttk.Button(conn, text="Disconnect", command=self.disconnect).grid(row=0, column=4, padx=6, pady=8)

        self.idn_label = ttk.Label(conn, text="[IDN] - Not connected")
        self.idn_label.grid(row=1, column=0, columnspan=5, padx=6, pady=(0, 8), sticky="w")

        for i in range(5):
            conn.grid_columnconfigure(i, weight=0)
        conn.grid_columnconfigure(4, weight=1)

        # Command block
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

        # Optional custom SCPI line (handy when you want something not in the list)
        ttk.Label(cmdf, text="Custom SCPI:").grid(row=1, column=0, padx=6, pady=(0, 8), sticky="e")
        self.custom_var = tk.StringVar()
        ttk.Entry(cmdf, textvariable=self.custom_var).grid(row=1, column=1, columnspan=3, padx=(0, 8), pady=(0, 8), sticky="we")
        ttk.Button(cmdf, text="Write (custom)", command=self.custom_write).grid(row=1, column=4, padx=6, pady=(0, 8))
        ttk.Button(cmdf, text="Query (custom)", command=self.custom_query).grid(row=1, column=5, padx=6, pady=(0, 8))

        cmdf.grid_columnconfigure(1, weight=1)
        cmdf.grid_columnconfigure(3, weight=0)

        # Log block
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(logf, height=16)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        # Status bar
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

    # ---------------------- VISA / Connection ----------------------
    def scan_resources(self):
        try:
            self.rm = self.rm or pyvisa.ResourceManager()
            res = list(self.rm.list_resources())
            if not res:
                self.status.set("No VISA resources found.")
                self._log("[SCAN] No VISA resources found.")
            else:
                self.resource_combo["values"] = res
                self.status.set(f"Found {len(res)} resource(s).")
                self._log("[SCAN] " + ", ".join(res))
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))

    def connect_selected(self):
        sel = trim(self.resource_var.get())
        if not sel:
            messagebox.showinfo("No resource", "Select a VISA resource first.")
            return
        try:
            self.rm = self.rm or pyvisa.ResourceManager()
            self._log(f"[CONNECT] Opening {sel} with no_lock ...")
            inst = self.rm.open_resource(
                sel,
                access_mode=pv.AccessModes.no_lock,
                open_timeout=5000,
            )

            # Basic terminations/timeouts
            try:
                inst.timeout = 3000
                if hasattr(inst, "read_termination"):
                    inst.read_termination = "\n"
                if hasattr(inst, "write_termination"):
                    inst.write_termination = "\n"
            except Exception:
                pass

            # Serial-specific sane defaults (best-effort)
            if sel.upper().startswith("ASRL"):
                try:
                    if hasattr(inst, "baud_rate") and inst.baud_rate is None:
                        inst.baud_rate = 9600
                    if hasattr(inst, "stop_bits") and inst.stop_bits is None:
                        inst.stop_bits = pv.StopBits.one
                    if hasattr(inst, "parity") and inst.parity is None:
                        inst.parity = pv.Parity.none
                    if hasattr(inst, "data_bits") and inst.data_bits is None:
                        inst.data_bits = 8
                    if hasattr(inst, "read_termination"):
                        inst.read_termination = "\n"
                    if hasattr(inst, "write_termination"):
                        inst.write_termination = "\n"
                except Exception:
                    pass

            # Probe *IDN?
            idn = ""
            try:
                idn = inst.query("*IDN?").strip()
            except Exception:
                pass

            self.inst = inst
            self.connected_resource = sel
            self.idn_label.config(text=f"[IDN] {idn or '(no response)'}  ({sel})")
            self._log(f"[CONNECT] Connected {sel}  IDN: {idn or '(no response)'}")
            self.status.set("Connected.")
        except pyvisa.errors.VisaIOError as e:
            if hasattr(pv, "VI_ERROR_RSRC_BUSY") and e.error_code == pv.VI_ERROR_RSRC_BUSY:
                self._log(f"[ERROR] VI_ERROR_RSRC_BUSY on {sel}")
                messagebox.showerror(
                    "Resource Busy",
                    (
                        "VISA reports the resource is busy:\n\n"
                        f"{sel}\n\n"
                        "Another application may be holding the port.\n\n"
                        "Close the other app or click Disconnect there, then try again.\n\n"
                        "Tip: Use this GUI's Disconnect button when done to free the port."
                    ),
                )
            else:
                messagebox.showerror("Connect failed", f"{type(e).__name__}: {e}")
            self.status.set("Connect failed.")
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))
            self.status.set("Connect failed.")

    def disconnect(self):
        try:
            if self.inst is not None:
                res = self.connected_resource or "(unknown)"
                try:
                    self.inst.close()
                finally:
                    self.inst = None
                    self.connected_resource = None
                self._log(f"[DISCONNECT] Closed {res}")
                self.idn_label.config(text="[IDN] - Not connected")
                self.status.set("Disconnected.")
            else:
                self.status.set("Nothing to disconnect.")
        except Exception as e:
            messagebox.showerror("Disconnect failed", str(e))

    def _check_connected(self):
        if self.inst is None:
            messagebox.showinfo("Not connected", "Connect to a VISA resource first.")
            return False
        return True

    # -------------------------- Command I/O -------------------------
    def _format_selected_command(self, for_query: bool):
        """Return the command string built from the selected template and param.
        If for_query is True and the base command is queryable, ensure it ends with '?'.
        """
        tpl = trim(self.cmd_var.get())
        param = trim(self.param_var.get())

        # Fill parameter placeholder if present
        if "{param}" in tpl:
            if not param and not tpl.endswith("?"):
                # SCPI writes that require a parameter should have one.
                # We'll allow empty (some instruments accept defaults), but warn in log.
                self._log("[WARN] No parameter provided; sending without value.")
            cmd = tpl.replace("{param}", param)
        else:
            # If user typed a param anyway, append with a space for writes
            cmd = tpl if (for_query or not param) else f"{tpl} {param}"

        if for_query:
            # If it's already a query, keep as-is
            if cmd.endswith("?"):
                return cmd
            # If base looks queryable, append '?'
            base = cmd.rstrip().rstrip("?")
            # Strip any trailing number/param to check base
            base_up = base.upper().split(" ")[0]
            if base_up in QUERYABLE_BASES:
                cmd = base + "?"
        return cmd

    def do_write(self):
        if not self._check_connected():
            return
        cmd = self._format_selected_command(for_query=False)
        if cmd.endswith("?"):
            messagebox.showinfo("Use Query", "This looks like a query. Use the Query button.")
            return
        try:
            self.inst.write(cmd)
            self._log(f"[WRITE] {cmd}")
            self.status.set("Write complete.")
        except Exception as e:
            messagebox.showerror("Write failed", str(e))

    def do_query(self):
        if not self._check_connected():
            return
        cmd = self._format_selected_command(for_query=True)
        if not cmd.endswith("?"):
            # Not a query; refuse to prevent timeouts
            messagebox.showinfo("Not a query", "This command is not a query. Add '?' or choose a query.")
            return
        try:
            resp = self.inst.query(cmd).strip()
            self._log(f"[QUERY] {cmd} -> {resp}")
            self.status.set("Query complete.")
        except Exception as e:
            messagebox.showerror("Query failed", str(e))

    # ---------------------- Custom SCPI line ------------------------
    def custom_write(self):
        if not self._check_connected():
            return
        cmd = trim(self.custom_var.get())
        if not cmd:
            messagebox.showinfo("No command", "Enter a custom SCPI command.")
            return
        if cmd.endswith("?"):
            messagebox.showinfo("Use Query", "Custom command ends with '?'. Use the Query (custom) button.")
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

    # --------------------------- Logging ----------------------------
    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")


if __name__ == "__main__":
    app = GeneralSCPIGUI()
    app.mainloop()
