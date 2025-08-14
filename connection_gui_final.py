# general_scpi_gui.py
# General SCPI GUI with robust ASRL (serial) connection logic
# - Single window for any instrument
# - VISA scan, connect/disconnect
# - Built-in general SCPI commands (IDN/CLS/RST/OPC/WAI/TST/ESE/ESR/SRE/STB/SYST:ERR)
# - Param field for commands needing a value (e.g., *ESE, *SRE)
# - Custom SCPI write/query
# - Log window
# - Robust serial open: tries multiple baud/data/parity/stop/EOL/flow presets and alternate probe commands

import time
import tkinter as tk
from tkinter import ttk, messagebox
import pyvisa
from pyvisa import constants as pv


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


class GeneralSCPIGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("General SCPI GUI (PyVISA)")
        self.geometry("980x720")
        self.rm = None
        self.inst = None
        self.connected_resource = None
        self._build_ui()

    # ----------------------------- UI -----------------------------
    def _build_ui(self):
        # Connection bar
        conn = ttk.LabelFrame(self, text="Connection")
        conn.pack(fill="x", padx=10, pady=(10, 8))

        ttk.Button(conn, text="Scan VISA", command=self.scan_resources).grid(row=0, column=0, padx=6, pady=8)
        ttk.Label(conn, text="Resource:").grid(row=0, column=1, padx=(12, 6), pady=8, sticky="e")
        self.resource_var = tk.StringVar()
        self.resource_combo = ttk.Combobox(conn, textvariable=self.resource_var, width=44, state="readonly")
        self.resource_combo.grid(row=0, column=2, padx=(0, 6), pady=8, sticky="w")

        ttk.Button(conn, text="Connect", command=self.connect_selected).grid(row=0, column=3, padx=6, pady=8)
        ttk.Button(conn, text="Disconnect", command=self.disconnect).grid(row=0, column=4, padx=6, pady=8)

        self.idn_label = ttk.Label(conn, text="[IDN] - Not connected")
        self.idn_label.grid(row=1, column=0, columnspan=5, padx=6, pady=(0, 8), sticky="w")

        # Command panel
        cmdf = ttk.LabelFrame(self, text="General SCPI Command")
        cmdf.pack(fill="x", padx=10, pady=(0, 8))

        ttk.Label(cmdf, text="Command:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        self.cmd_var = tk.StringVar(value=COMMANDS[0])
        self.cmd_combo = ttk.Combobox(cmdf, textvariable=self.cmd_var, values=COMMANDS, width=30, state="readonly")
        self.cmd_combo.grid(row=0, column=1, padx=(0, 8), pady=8, sticky="w")

        ttk.Label(cmdf, text="Param (if needed):").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.param_var = tk.StringVar(value="")
        ttk.Entry(cmdf, textvariable=self.param_var, width=18).grid(row=0, column=3, padx=(0, 8), pady=8, sticky="w")

        ttk.Button(cmdf, text="Write", command=self.do_write).grid(row=0, column=4, padx=6, pady=8)
        ttk.Button(cmdf, text="Query", command=self.do_query).grid(row=0, column=5, padx=6, pady=8)

        ttk.Label(cmdf, text="Custom SCPI:").grid(row=1, column=0, padx=6, pady=(0, 8), sticky="e")
        self.custom_var = tk.StringVar()
        ttk.Entry(cmdf, textvariable=self.custom_var).grid(row=1, column=1, columnspan=3, padx=(0, 8), pady=(0, 8), sticky="we")
        ttk.Button(cmdf, text="Write (custom)", command=self.custom_write).grid(row=1, column=4, padx=6, pady=(0, 8))
        ttk.Button(cmdf, text="Query (custom)", command=self.custom_query).grid(row=1, column=5, padx=6, pady=(0, 8))

        cmdf.grid_columnconfigure(1, weight=1)

        # Log
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(logf, height=18)
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
            self._log(f"[CONNECT] Opening {sel} ...")

            idn = ""
            inst = None

            if sel.upper().startswith("ASRL"):
                # Robust serial open using multiple presets
                inst, idn = self._open_serial_robust(sel)
                if inst is None:
                    raise RuntimeError("Failed to open ASRL with common presets. Check baud/terminations/flow control.")
                self._log("[ASRL] Connected using robust preset search.")
            else:
                # GPIB/USB/LAN: simpler path
                inst = self.rm.open_resource(sel, access_mode=pv.AccessModes.no_lock, open_timeout=5000)
                try:
                    inst.timeout = 1500
                    inst.write_timeout = 1500
                    if hasattr(inst, "read_termination"):
                        inst.read_termination = "\n"
                    if hasattr(inst, "write_termination"):
                        inst.write_termination = "\n"
                except Exception:
                    pass
                try:
                    idn = inst.query("*IDN?").strip()
                except Exception:
                    idn = ""

            self.inst = inst
            self.connected_resource = sel
            self.idn_label.config(text=f"[IDN] {idn or '(no response)'}  ({sel})")
            self._log(f"[CONNECT] Connected {sel}  IDN: {idn or '(no response)'}")
            self.status.set("Connected.")
        except pyvisa.errors.VisaIOError as e:
            messagebox.showerror("Connect failed", f"{type(e).__name__}: {e}")
            self.status.set("Connect failed.")
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))
            self.status.set("Connect failed.")

    def _open_serial_robust(self, resource_key):
        """Open an ASRL resource and try common serial baud/termination combos.
        Returns (inst, idn_str) or (None, "").
        """
        try:
            inst = (self.rm or pyvisa.ResourceManager()).open_resource(
                resource_key,
                access_mode=pv.AccessModes.no_lock,
                open_timeout=5000,
            )
        except Exception:
            return None, ""

        # Baseline sane defaults
        try:
            inst.timeout = 600
            inst.write_timeout = 600
            if hasattr(inst, "data_bits"):
                inst.data_bits = 8
            if hasattr(inst, "parity"):
                inst.parity = pv.Parity.none
            if hasattr(inst, "stop_bits"):
                inst.stop_bits = pv.StopBits.one
            if hasattr(inst, "rtscts"):
                inst.rtscts = False
            if hasattr(inst, "xonxoff"):
                inst.xonxoff = False
        except Exception:
            pass

        baud_candidates = [115200, 57600, 38400, 19200, 9600, 4800]
        # (write_termination, read_termination)
        term_candidates = [("\r\n", "\n"), ("\n", "\n"), ("\r", "\r"), ("\r\n", "\r\n")]
        # (data_bits, parity, stop_bits)
        frame_candidates = [
            (8, pv.Parity.none, pv.StopBits.one),  # 8N1
            (7, pv.Parity.even, pv.StopBits.one),  # 7E1 (legacy HP/Agilent)
            (7, pv.Parity.odd, pv.StopBits.one),   # 7O1 (some older gear)
        ]
        # flow control options to try (if supported by backend)
        flow_candidates = [None, "xonxoff", "rtscts"]

        probes = ["*IDN?", "IDN?", "SYST:VERS?", "VER?"]

        def set_flow(inst, mode):
            try:
                if mode is None:
                    if hasattr(inst, "xonxoff"):
                        inst.xonxoff = False
                    if hasattr(inst, "rtscts"):
                        inst.rtscts = False
                elif mode == "xonxoff" and hasattr(inst, "xonxoff"):
                    inst.xonxoff = True
                elif mode == "rtscts" and hasattr(inst, "rtscts"):
                    inst.rtscts = True
            except Exception:
                pass

        for baud in baud_candidates:
            # set baud if available
            try:
                if hasattr(inst, "baud_rate"):
                    inst.baud_rate = baud
            except Exception:
                pass
            for db, pr, sb in frame_candidates:
                try:
                    if hasattr(inst, "data_bits"):
                        inst.data_bits = db
                    if hasattr(inst, "parity"):
                        inst.parity = pr
                    if hasattr(inst, "stop_bits"):
                        inst.stop_bits = sb
                except Exception:
                    pass
                for wterm, rterm in term_candidates:
                    for flow in flow_candidates:
                        set_flow(inst, flow)
                        try:
                            if hasattr(inst, "write_termination"):
                                inst.write_termination = wterm
                            if hasattr(inst, "read_termination"):
                                inst.read_termination = rterm

                            # Try to wake the device / clear buffers
                            try:
                                inst.clear()
                            except Exception:
                                pass
                            for wake in ("", "\r", "\n"):
                                try:
                                    inst.write(wake)
                                except Exception:
                                    pass
                            time.sleep(0.12)

                            # Try probes; prefer explicit write/read to avoid query hang
                            for q in probes:
                                try:
                                    inst.write(q)
                                    time.sleep(0.08)
                                    resp = ""
                                    try:
                                        resp = inst.read().strip()
                                    except Exception:
                                        # Try read_bytes fallback if available
                                        try:
                                            if hasattr(inst, "read_bytes"):
                                                raw = inst.read_bytes(256)
                                                resp = raw.decode(errors="ignore").strip()
                                        except Exception:
                                            resp = ""
                                    if resp:
                                        self._log(
                                            f"[ASRL] Working preset: baud={baud}, frame={db}{pr.name[0].upper()}{int(sb.value)} "
                                            f"term=({repr(wterm)}, {repr(rterm)}) flow={flow}; probe={q} -> {resp}"
                                        )
                                        return inst, resp
                                except Exception:
                                    continue
                        except Exception:
                            continue

        # No joy
        try:
            inst.close()
        except Exception:
            pass
        return None, ""

    def disconnect(self):
        try:
            if self.inst:
                res = self.connected_resource or "(unknown)"
                self.inst.close()
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
        if not self.inst:
            messagebox.showinfo("Not connected", "Connect to a VISA resource first.")
            return False
        return True

    # -------------------------- Command I/O -------------------------
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
