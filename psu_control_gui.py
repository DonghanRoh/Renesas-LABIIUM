# psu_control_gui.py
# Updated to handle VI_ERROR_RSRC_BUSY on ASRL (serial) resources:
# - Use AccessModes.no_lock, longer open_timeout, clear error guidance
# - Add Disconnect button to free the port quickly
# - Better ASRL setup (terminations/timeouts)
#
# Works with HMP4040 and E3631A. Includes Write/Query buttons.

import tkinter as tk
from tkinter import ttk, messagebox
import pyvisa
from pyvisa import constants as pv

def trim(s): return (s or "").strip()

class PSUControlGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("PSU Control (E3631A / HMP4040)")
        self.geometry("980x650")

        self.rm = None
        self.inst = None  # PyVISA resource
        self.connected_resource = None

        self._build_ui()

    def _build_ui(self):
        # Connection area
        conn = ttk.LabelFrame(self, text="Connection")
        conn.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(conn, text="Device type:").grid(row=0, column=0, padx=6, pady=8, sticky="w")
        self.device_type = tk.StringVar(value="HMP4040")
        ttk.Combobox(conn, textvariable=self.device_type, values=["HMP4040", "E3631A"], width=12, state="readonly").grid(row=0, column=1, padx=(0,10), pady=8, sticky="w")

        ttk.Button(conn, text="Scan VISA", command=self.scan_resources).grid(row=0, column=2, padx=6, pady=8)
        ttk.Label(conn, text="Resource:").grid(row=0, column=3, padx=(12,6), pady=8, sticky="e")
        self.resource_var = tk.StringVar()
        self.resource_combo = ttk.Combobox(conn, textvariable=self.resource_var, width=36, state="readonly")
        self.resource_combo.grid(row=0, column=4, padx=(0,6), pady=8, sticky="w")

        ttk.Button(conn, text="Connect", command=self.connect_selected).grid(row=0, column=5, padx=6, pady=8)
        ttk.Button(conn, text="Disconnect", command=self.disconnect).grid(row=0, column=6, padx=6, pady=8)

        self.idn_label = ttk.Label(conn, text="[IDN] - Not connected")
        self.idn_label.grid(row=1, column=0, columnspan=7, padx=6, pady=(0,8), sticky="w")

        for i in range(7):
            conn.grid_columnconfigure(i, weight=0)
        conn.grid_columnconfigure(6, weight=1)

        # Controls frame (two subframes; we show one at a time)
        self.model_frame = ttk.LabelFrame(self, text="Controls")
        self.model_frame.pack(fill="x", padx=10, pady=(0, 6))

        self._build_hmp4040_controls()
        self._build_e3631a_controls()
        self._show_controls_for(self.device_type.get())
        self.device_type.trace_add("write", lambda *_: self._show_controls_for(self.device_type.get()))

        # Generic SCPI
        scpi = ttk.LabelFrame(self, text="Generic SCPI")
        scpi.pack(fill="x", padx=10, pady=(0, 6))

        self.scpi_entry = ttk.Entry(scpi)
        self.scpi_entry.pack(side="left", fill="x", expand=True, padx=6, pady=6)
        ttk.Button(scpi, text="Write", command=self.generic_write).pack(side="left", padx=6, pady=6)
        ttk.Button(scpi, text="Query", command=self.generic_query).pack(side="left", padx=6, pady=6)

        # Log
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(logf, height=14)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        # Status bar
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

    # ----------------------- HMP4040 controls -----------------------

    def _build_hmp4040_controls(self):
        f = ttk.Frame(self.model_frame)
        self.hmp_frame = f

        row = 0
        ttk.Label(f, text="Channel (1-4):").grid(row=row, column=0, padx=6, pady=6, sticky="e")
        self.hmp_channel = tk.IntVar(value=1)
        ttk.Spinbox(f, from_=1, to=4, textvariable=self.hmp_channel, width=5).grid(row=row, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(f, text="Voltage (V):").grid(row=row, column=2, padx=6, pady=6, sticky="e")
        self.hmp_volt = tk.StringVar(value="0.000")
        ttk.Entry(f, textvariable=self.hmp_volt, width=10).grid(row=row, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(f, text="Current limit (A):").grid(row=row, column=4, padx=6, pady=6, sticky="e")
        self.hmp_curr = tk.StringVar(value="0.100")
        ttk.Entry(f, textvariable=self.hmp_curr, width=10).grid(row=row, column=5, padx=6, pady=6, sticky="w")

        row += 1
        ttk.Label(f, text="OVP mode:").grid(row=row, column=0, padx=6, pady=6, sticky="e")
        self.hmp_ovp_mode = tk.StringVar(value="measured")  # measured|protected
        ttk.Combobox(f, textvariable=self.hmp_ovp_mode, values=["measured", "protected"], width=12, state="readonly").grid(row=row, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(f, text="Output state:").grid(row=row, column=2, padx=6, pady=6, sticky="e")
        self.hmp_output_state = tk.StringVar(value="ON")  # ON/OFF
        ttk.Combobox(f, textvariable=self.hmp_output_state, values=["ON", "OFF"], width=8, state="readonly").grid(row=row, column=3, padx=6, pady=6, sticky="w")

        ttk.Button(f, text="Write", command=self.hmp_write).grid(row=row, column=4, padx=6, pady=6, sticky="e")
        ttk.Button(f, text="Query", command=self.hmp_query).grid(row=row, column=5, padx=6, pady=6, sticky="w")

        for c in range(6):
            f.grid_columnconfigure(c, weight=0)

    def hmp_write(self):
        if not self._check_connected(): return
        try:
            ch = self.hmp_channel.get()
            self.inst.write(f"INSTrument:NSELect {ch}")
            v = trim(self.hmp_volt.get())
            i = trim(self.hmp_curr.get())
            ovp = trim(self.hmp_ovp_mode.get())
            out = trim(self.hmp_output_state.get())

            if v:
                self.inst.write(f"SOURce:VOLTage {v}")
                self._log(f"[HMP] Set CH{ch} Voltage -> {v} V")
            if i:
                self.inst.write(f"SOURce:CURRent {i}")
                self._log(f"[HMP] Set CH{ch} Current -> {i} A")
            if ovp:
                self.inst.write(f"VOLTage:PROTection:MODE {ovp}")
                self._log(f"[HMP] Set CH{ch} OVP mode -> {ovp}")
            if out:
                val = "1" if out.upper()=="ON" else "0"
                self.inst.write(f"OUTPut:STATe {val}")
                self._log(f"[HMP] Set CH{ch} Output -> {out}")

            self.status.set("HMP4040: Write complete.")
        except Exception as e:
            messagebox.showerror("HMP4040 Write failed", str(e))

    def hmp_query(self):
        if not self._check_connected(): return
        try:
            ch = self.hmp_channel.get()
            self.inst.write(f"INSTrument:NSELect {ch}")
            v = self.inst.query("SOURce:VOLTage?").strip()
            i = self.inst.query("SOURce:CURRent?").strip()
            ovp = self.inst.query("VOLTage:PROTection:MODE?").strip()
            out = self.inst.query("OUTPut:STATe?").strip()

            self.hmp_volt.set(v)
            self.hmp_curr.set(i)
            self.hmp_ovp_mode.set(ovp)
            self.hmp_output_state.set("ON" if out in ("1","ON") else "OFF")

            meas_v = self.inst.query("MEASure:VOLTage?").strip()
            meas_i = self.inst.query("MEASure:CURRent?").strip()

            self._log(f"[HMP] CH{ch} Vset={v} V, Iset={i} A, OVP={ovp}, OUT={out}; MeasV={meas_v} V, MeasI={meas_i} A")
            self.status.set("HMP4040: Query complete.")
        except Exception as e:
            messagebox.showerror("HMP4040 Query failed", str(e))

    # ----------------------- E3631A controls -----------------------

    def _build_e3631a_controls(self):
        f = ttk.Frame(self.model_frame)
        self.e36_frame = f

        row = 0
        ttk.Label(f, text="Output:").grid(row=row, column=0, padx=6, pady=6, sticky="e")
        self.e36_output = tk.StringVar(value="P6V")  # P6V, P25V, N25V
        ttk.Combobox(f, textvariable=self.e36_output, values=["P6V", "P25V", "N25V"], width=10, state="readonly").grid(row=row, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(f, text="Voltage (V):").grid(row=row, column=2, padx=6, pady=6, sticky="e")
        self.e36_volt = tk.StringVar(value="0.0000")
        ttk.Entry(f, textvariable=self.e36_volt, width=12).grid(row=row, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(f, text="Current (A):").grid(row=row, column=4, padx=6, pady=6, sticky="e")
        self.e36_curr = tk.StringVar(value="0.1000")
        ttk.Entry(f, textvariable=self.e36_curr, width=12).grid(row=row, column=5, padx=6, pady=6, sticky="w")

        ttk.Button(f, text="Write", command=self.e36_write).grid(row=row, column=6, padx=6, pady=6)
        ttk.Button(f, text="Query", command=self.e36_query).grid(row=row, column=7, padx=6, pady=6)

        row += 1
        ttk.Label(f, text="Output (global):").grid(row=row, column=0, padx=6, pady=6, sticky="e")
        self.e36_out_state = tk.StringVar(value="ON")
        ttk.Combobox(f, textvariable=self.e36_out_state, values=["ON","OFF"], width=8, state="readonly").grid(row=row, column=1, padx=6, pady=6, sticky="w")
        ttk.Button(f, text="Apply OUT", command=self.e36_toggle_output).grid(row=row, column=2, padx=6, pady=6, sticky="w")

        for c in range(8):
            f.grid_columnconfigure(c, weight=0)

    def e36_write(self):
        if not self._check_connected(): return
        try:
            out = self.e36_output.get()
            v = trim(self.e36_volt.get())
            i = trim(self.e36_curr.get())
            self.inst.write(f"APPLy {out},{v},{i}")
            self._log(f"[E3631A] APPLy {out},{v},{i}")
            self.status.set("E3631A: Write complete.")
        except Exception as e:
            messagebox.showerror("E3631A Write failed", str(e))

    def e36_query(self):
        if not self._check_connected(): return
        try:
            out = self.e36_output.get()
            resp = self.inst.query(f"APPLy? {out}").strip()
            parts = [p.strip().strip('"') for p in resp.split(",")]
            if len(parts) >= 2:
                self.e36_volt.set(parts[0])
                self.e36_curr.set(parts[1])
            try:
                out_state = self.inst.query("OUTPut:STATe?").strip()
                self.e36_out_state.set("ON" if out_state in ("1","ON") else "OFF")
            except Exception:
                pass

            self._log(f"[E3631A] {out} -> {resp}")
            self.status.set("E3631A: Query complete.")
        except Exception as e:
            messagebox.showerror("E3631A Query failed", str(e))

    def e36_toggle_output(self):
        if not self._check_connected(): return
        try:
            val = "1" if self.e36_out_state.get().upper()=="ON" else "0"
            self.inst.write(f"OUTPut:STATe {val}")
            self._log(f"[E3631A] OUTPut:STATe {val}")
        except Exception as e:
            messagebox.showerror("E3631A Output toggle failed", str(e))

    # ----------------------- Generic SCPI ---------------------------

    def generic_write(self):
        if not self._check_connected(): return
        cmd = trim(self.scpi_entry.get())
        if not cmd:
            messagebox.showinfo("No command", "Enter a SCPI command to write.")
            return
        try:
            self.inst.write(cmd)
            self._log(f"[WRITE] {cmd}")
        except Exception as e:
            messagebox.showerror("Write failed", str(e))

    def generic_query(self):
        if not self._check_connected(): return
        cmd = trim(self.scpi_entry.get())
        if not cmd.endswith("?"):
            messagebox.showinfo("Query needs '?'", "Your SCPI query must end with '?'.")
            return
        try:
            resp = self.inst.query(cmd).strip()
            self._log(f"[QUERY] {cmd} -> {resp}")
        except Exception as e:
            messagebox.showerror("Query failed", str(e))

    # ----------------------- Connection logic ----------------------

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
            # Try no_lock and longer open_timeout (5000 ms)
            self._log(f"[CONNECT] Opening {sel} with no_lock ...")
            inst = self.rm.open_resource(
                sel,
                access_mode=pv.AccessModes.no_lock,
                open_timeout=5000
            )

            # Basic setup
            try:
                inst.timeout = 2000
                if hasattr(inst, "read_termination"):
                    inst.read_termination = "\n"
                if hasattr(inst, "write_termination"):
                    inst.write_termination = "\n"
            except Exception:
                pass

            # For ASRL specifically, assert sane serial params/terms
            if sel.upper().startswith("ASRL"):
                try:
                    # Some VISA backends expose these; some do not.
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
            # Specific handling for resource busy
            if hasattr(pv, "VI_ERROR_RSRC_BUSY") and e.error_code == pv.VI_ERROR_RSRC_BUSY:
                self._log(f"[ERROR] VI_ERROR_RSRC_BUSY on {sel}")
                messagebox.showerror(
                    "Resource Busy",
                    (
                        "VISA reports the resource is busy:\n\n"
                        f"{sel}\n\n"
                        "Another application (likely your first GUI) is holding the serial port.\n\n"
                        "Close the other app or Disconnect it from this port, then click Connect again.\n\n"
                        "Tip: Use this GUI’s Disconnect button when done to free the port."
                    )
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

    def _show_controls_for(self, devtype: str):
        for w in (self.hmp_frame, self.e36_frame):
            w.pack_forget()
        if devtype == "HMP4040":
            self.hmp_frame.pack(fill="x", padx=10, pady=6)
        else:
            self.e36_frame.pack(fill="x", padx=10, pady=6)

    def _log(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")


if __name__ == "__main__":
    app = PSUControlGUI()
    app.mainloop()
