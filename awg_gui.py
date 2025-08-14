# awg_gui.py
# Purpose: Simple Tkinter GUI to control an Agilent/Keysight 33600-series AWG via PyVISA.
# Notes:
# - No multithreading/asyncio used (as requested).
# - Supports: connect, *IDN?, reset, error queue readout, output on/off, 
#   basic function setup (SINE/SQUARE/ARB), freq/amp/offset/phase, display text,
#   single-line SCPI, and CSV-based ARB upload (time,value or value-only).
# - CSV ARB upload expects either two columns: time(s), value; or one column: value (uniform sample period required input).

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import pyvisa
import csv
import os
import numpy as np

# ----------------------------- Utility helpers -----------------------------

def truncate_arb_name(name: str, maxlen: int = 12) -> str:
    base = os.path.splitext(os.path.basename(name))[0]
    return base[:maxlen]


def safe_float(s: str, default=None):
    try:
        return float(s)
    except Exception:
        return default


# ----------------------------- Main GUI -----------------------------
class AWGGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("AWG GUI (Keysight 33600) — no threading")
        self.geometry("1000x700")

        # VISA session
        self.rm = None
        self.inst = None
        self.connected_resource = tk.StringVar(value="")
        self.idn_text = tk.StringVar(value="[IDN] - Not connected")
        self.status = tk.StringVar(value="Ready.")

        # Channel & basic settings
        self.channel = tk.StringVar(value="1")
        self.func = tk.StringVar(value="SINE")
        self.freq = tk.StringVar(value="1000")          # Hz
        self.amp = tk.StringVar(value="0.5")            # Vpp
        self.offset = tk.StringVar(value="0.0")         # V
        self.phase = tk.StringVar(value="0.0")          # degrees
        self.output_enabled = tk.BooleanVar(value=False)

        # Display text
        self.display_text = tk.StringVar(value="")

        # SCPI single line
        self.scpi_line = tk.StringVar(value="")

        # ARB upload
        self.arb_file = tk.StringVar(value="")
        self.arb_delim = tk.StringVar(value="comma")     # comma/space/tab
        self.arb_scale_mode = tk.StringVar(value="normalize")  # normalize/custom
        self.arb_custom_amp = tk.StringVar(value="0.2")   # Vpp when scale=custom
        self.arb_assumed_dt = tk.StringVar(value="1e-6")  # used if file has 1 column

        self._build_ui()

    # ----------------------------- UI BUILD -----------------------------
    def _build_ui(self):
        # Top connection frame
        cframe = ttk.LabelFrame(self, text="Connection")
        cframe.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Label(cframe, text="VISA Resource:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.resource_entry = ttk.Entry(cframe, textvariable=self.connected_resource, width=45)
        self.resource_entry.grid(row=0, column=1, padx=6, pady=6, sticky="we")
        ttk.Button(cframe, text="Scan", command=self.on_scan).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(cframe, text="Connect", command=self.on_connect).grid(row=0, column=3, padx=6, pady=6)
        ttk.Button(cframe, text="Reset (*RST)", command=self.on_reset).grid(row=0, column=4, padx=6, pady=6)
        ttk.Button(cframe, text="Read Errors", command=self.on_read_errors).grid(row=0, column=5, padx=6, pady=6)

        self.idn_label = ttk.Label(cframe, textvariable=self.idn_text)
        self.idn_label.grid(row=1, column=0, columnspan=6, padx=6, pady=(0, 8), sticky="w")

        cframe.grid_columnconfigure(1, weight=1)

        # Basic setup frame
        bframe = ttk.LabelFrame(self, text="Basic Setup")
        bframe.pack(fill="x", padx=10, pady=10)

        ttk.Label(bframe, text="Channel").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(bframe, textvariable=self.channel, values=["1", "2"], width=6, state="readonly").grid(row=0, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(bframe, text="Function").grid(row=0, column=2, padx=6, pady=6, sticky="e")
        ttk.Combobox(bframe, textvariable=self.func, values=["SINE", "SQUARE", "RAMP", "PULSE", "NOISE", "ARB"], width=10, state="readonly").grid(row=0, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(bframe, text="Freq (Hz)").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(bframe, textvariable=self.freq, width=14).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(bframe, text="Amp (Vpp)").grid(row=1, column=2, padx=6, pady=6, sticky="e")
        ttk.Entry(bframe, textvariable=self.amp, width=10).grid(row=1, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(bframe, text="Offset (V)").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(bframe, textvariable=self.offset, width=10).grid(row=2, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(bframe, text="Phase (deg)").grid(row=2, column=2, padx=6, pady=6, sticky="e")
        ttk.Entry(bframe, textvariable=self.phase, width=10).grid(row=2, column=3, padx=6, pady=6, sticky="w")

        ttk.Checkbutton(bframe, text="Output ON", variable=self.output_enabled, command=self.on_toggle_output).grid(row=0, column=4, padx=8, pady=6, sticky="w")
        ttk.Button(bframe, text="Apply", command=self.on_apply_basic).grid(row=1, column=4, padx=8, pady=6)

        for i in range(5):
            bframe.grid_columnconfigure(i, weight=0)
        bframe.grid_columnconfigure(5, weight=1)

        # Display text frame
        dframe = ttk.LabelFrame(self, text="Front-panel Display Text")
        dframe.pack(fill="x", padx=10, pady=0)
        ttk.Entry(dframe, textvariable=self.display_text).grid(row=0, column=0, padx=6, pady=6, sticky="we")
        ttk.Button(dframe, text="Show", command=self.on_show_text).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(dframe, text="Clear", command=self.on_clear_text).grid(row=0, column=2, padx=6, pady=6)
        dframe.grid_columnconfigure(0, weight=1)

        # SCPI frame
        sframe = ttk.LabelFrame(self, text="SCPI (single line)")
        sframe.pack(fill="x", padx=10, pady=10)
        ttk.Entry(sframe, textvariable=self.scpi_line).grid(row=0, column=0, padx=6, pady=6, sticky="we")
        ttk.Button(sframe, text="Send", command=self.on_send_scpi).grid(row=0, column=1, padx=6, pady=6)
        sframe.grid_columnconfigure(0, weight=1)

        # ARB upload frame
        aframe = ttk.LabelFrame(self, text="ARB Upload (CSV)")
        aframe.pack(fill="x", padx=10, pady=0)

        ttk.Label(aframe, text="File").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(aframe, textvariable=self.arb_file).grid(row=0, column=1, padx=6, pady=6, sticky="we")
        ttk.Button(aframe, text="Browse", command=self.on_browse_file).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(aframe, text="Delimiter").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(aframe, textvariable=self.arb_delim, values=["comma", "space", "tab"], state="readonly", width=8).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(aframe, text="Scale").grid(row=1, column=2, padx=6, pady=6, sticky="e")
        ttk.Combobox(aframe, textvariable=self.arb_scale_mode, values=["normalize", "custom Vpp"], state="readonly", width=14).grid(row=1, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(aframe, text="Custom Vpp").grid(row=1, column=4, padx=6, pady=6, sticky="e")
        ttk.Entry(aframe, textvariable=self.arb_custom_amp, width=10).grid(row=1, column=5, padx=6, pady=6, sticky="w")

        ttk.Label(aframe, text="Assumed dt (s, if 1 col)").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(aframe, textvariable=self.arb_assumed_dt, width=12).grid(row=2, column=1, padx=6, pady=6, sticky="w")

        ttk.Button(aframe, text="Upload to CH", command=self.on_upload_arb).grid(row=2, column=2, padx=6, pady=6)
        ttk.Button(aframe, text="Save to INT: memory", command=self.on_save_arb_internal).grid(row=2, column=3, padx=6, pady=6)

        aframe.grid_columnconfigure(1, weight=1)

        # Log frame
        lframe = ttk.LabelFrame(self, text="Log")
        lframe.pack(fill="both", expand=True, padx=10, pady=(10, 10))
        self.log = tk.Text(lframe, height=12)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        # Status bar
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

    # ----------------------------- VISA helpers -----------------------------
    def _ensure_rm(self):
        if self.rm is None:
            self.rm = pyvisa.ResourceManager()

    def _ensure_inst(self):
        if self.inst is None:
            raise RuntimeError("Not connected to any instrument.")

    def log_line(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.status.set(msg)
        self.update_idletasks()

    def scpi_write(self, cmd: str):
        self._ensure_inst()
        self.log_line(f"-> {cmd}")
        self.inst.write(cmd)

    def scpi_query(self, cmd: str) -> str:
        self._ensure_inst()
        self.log_line(f"-> {cmd}")
        try:
            resp = self.inst.query(cmd).strip()
        except Exception as e:
            resp = f"<query error: {e}>"
        self.log_line(f"<- {resp}")
        return resp

    def _read_error_queue(self):
        self._ensure_inst()
        # Read until +0,"No error"
        out = []
        while True:
            self.inst.write('SYST:ERR?')
            err = self.inst.read()
            out.append(err.strip())
            if err.startswith('+0'):
                break
        return out

    # ----------------------------- Actions -----------------------------
    def on_scan(self):
        try:
            self._ensure_rm()
            resources = list(self.rm.list_resources())
            if not resources:
                messagebox.showinfo("Scan", "No VISA resources found.")
                return
            # Let user pick
            choice = self._simple_choice_dialog("Select VISA Resource", resources)
            if choice:
                self.connected_resource.set(choice)
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))

    def _simple_choice_dialog(self, title, items):
        """Blocking simple choice dialog returning selected item or None."""
        dlg = tk.Toplevel(self)
        dlg.title(title)
        dlg.transient(self)
        dlg.grab_set()
        var = tk.StringVar(value=items)

        lb = tk.Listbox(dlg, listvariable=var, width=80, height=min(12, max(4, len(items))))
        lb.pack(fill="both", expand=True, padx=10, pady=10)

        sel = {"value": None}
        def on_ok():
            try:
                idx = lb.curselection()[0]
                sel["value"] = items[idx]
            except Exception:
                sel["value"] = None
            dlg.destroy()
        def on_cancel():
            sel["value"] = None
            dlg.destroy()

        btnf = ttk.Frame(dlg)
        btnf.pack(fill="x", padx=10, pady=(0,10))
        ttk.Button(btnf, text="OK", command=on_ok).pack(side="right", padx=6)
        ttk.Button(btnf, text="Cancel", command=on_cancel).pack(side="right")

        self.wait_window(dlg)
        return sel["value"]

    def on_connect(self):
        resource = self.connected_resource.get().strip()
        if not resource:
            messagebox.showinfo("Connect", "Enter or choose a VISA resource.")
            return
        try:
            self._ensure_rm()
            if self.inst is not None:
                try:
                    self.inst.close()
                except Exception:
                    pass
                self.inst = None

            self.inst = self.rm.open_resource(resource)
            # Basic terminations/timeouts
            try:
                self.inst.timeout = 2000
                if hasattr(self.inst, 'read_termination'):
                    self.inst.read_termination = "\n"
                if hasattr(self.inst, 'write_termination'):
                    self.inst.write_termination = "\n"
            except Exception:
                pass

            idn = self.scpi_query("*IDN?")
            self.idn_text.set(f"[IDN] {idn} ({resource})")
            self.log_line(f"Connected to {resource}")
        except Exception as e:
            messagebox.showerror("Connect failed", str(e))

    def on_reset(self):
        try:
            self.scpi_write("*RST")
            self.log_line("Device reset issued.")
        except Exception as e:
            messagebox.showerror("Reset", str(e))

    def on_read_errors(self):
        try:
            errs = self._read_error_queue()
            messagebox.showinfo("Error Queue", "\n".join(errs))
        except Exception as e:
            messagebox.showerror("Errors", str(e))

    def on_toggle_output(self):
        try:
            ch = self.channel.get()
            state = 'ON' if self.output_enabled.get() else 'OFF'
            self.scpi_write(f'OUTP{ch} {state}')
        except Exception as e:
            messagebox.showerror("Output", str(e))

    def on_apply_basic(self):
        try:
            ch = self.channel.get()
            func = self.func.get().upper()
            f = safe_float(self.freq.get())
            a = safe_float(self.amp.get())
            o = safe_float(self.offset.get(), 0.0)
            p = safe_float(self.phase.get(), 0.0)
            if f is None or a is None:
                raise ValueError("Frequency and amplitude must be numeric.")

            # Set basic parameters
            self.scpi_write(f'SOUR{ch}:FUNC {func}')
            if func != 'NOISE':
                self.scpi_write(f'SOUR{ch}:FREQ {f}')
                self.scpi_write(f'SOUR{ch}:VOLT {a}')
                self.scpi_write(f'SOUR{ch}:VOLT:OFFS {o}')
                self.scpi_write(f'SOUR{ch}:PHAS {p}')
            self.log_line("Basic settings applied.")
        except Exception as e:
            messagebox.showerror("Apply", str(e))

    def on_show_text(self):
        try:
            txt = self.display_text.get().replace("'", "\'")
            self.scpi_write(f"DISP:TEXT '{txt}'")
        except Exception as e:
            messagebox.showerror("Display", str(e))

    def on_clear_text(self):
        try:
            self.scpi_write("DISP:TEXT ''")
        except Exception as e:
            messagebox.showerror("Display", str(e))

    def on_send_scpi(self):
        cmd = self.scpi_line.get().strip()
        if not cmd:
            return
        try:
            if cmd.endswith('?'):
                self.scpi_query(cmd)
            else:
                self.scpi_write(cmd)
        except Exception as e:
            messagebox.showerror("SCPI", str(e))

    # ----------------------------- ARB Handling -----------------------------
    def on_browse_file(self):
        path = filedialog.askopenfilename(title="Select CSV/Dat", filetypes=[
            ("CSV/Dat", "*.csv *.dat *.txt"),
            ("All files", "*.*"),
        ])
        if path:
            self.arb_file.set(path)

    def _read_arb_csv(self, path: str, delim_mode: str):
        """
        Returns (times_or_None, values_array, dt_or_None)
        - If the file has two columns: returns times, values, None
        - If the file has one column: returns None, values, dt from self.arb_assumed_dt
        """
        delim = {"comma": ",", "space": " ", "tab": "\t"}.get(delim_mode, ",")
        times = []
        vals = []
        with open(path, 'r', newline='') as f:
            rdr = csv.reader(f, delimiter=delim)
            for row in rdr:
                if not row:
                    continue
                # allow comments starting with '#'
                if row[0].strip().startswith('#'):
                    continue
                if len(row) >= 2:
                    try:
                        t = float(row[0])
                        v = float(row[1])
                        times.append(t)
                        vals.append(v)
                    except Exception:
                        continue
                else:
                    try:
                        v = float(row[0])
                        vals.append(v)
                    except Exception:
                        continue
        if len(vals) == 0:
            raise ValueError("No valid data parsed from file.")
        values = np.asarray(vals, dtype='f4')
        if times:
            return np.asarray(times, dtype='f8'), values, None
        else:
            dt = safe_float(self.arb_assumed_dt.get())
            if dt is None or dt <= 0:
                raise ValueError("Assumed dt must be a positive number when file has one column.")
            return None, values, dt

    def _compute_sample_rate(self, times: np.ndarray = None, dt: float = None):
        if times is not None:
            if times.size < 2:
                raise ValueError("Not enough time points to infer sample rate.")
            diffs = np.diff(times)
            mean_dt = float(np.mean(diffs))
            if mean_dt <= 0:
                raise ValueError("Non-positive average dt computed.")
            return 1.0 / mean_dt
        else:
            if dt is None or dt <= 0:
                raise ValueError("Invalid dt for sample rate.")
            return 1.0 / dt

    def _prepare_arb_payload(self, values: np.ndarray, scale_mode: str):
        vals = values.astype('f4')
        vmax = float(np.max(np.abs(vals))) if vals.size else 1.0
        if vmax == 0:
            vmax = 1.0
        if scale_mode == "normalize":
            sig = vals / vmax
            vpp = None  # Use GUI amplitude later if desired
        else:
            # Keep as-is, amplitude will be set explicitly
            sig = vals / vmax  # normalize to +/-1 for ARB
            vpp = safe_float(self.arb_custom_amp.get())
            if vpp is None or vpp <= 0:
                raise ValueError("Custom Vpp must be a positive number.")
        return sig.astype('f4'), vpp

    def _ensure_binary_preamble(self):
        # Recommended settings for binary transfer
        try:
            self.scpi_write('FORM:BORD SWAP')  # little endian from PC
        except Exception:
            pass

    def on_upload_arb(self):
        try:
            self._ensure_inst()
            path = self.arb_file.get().strip()
            if not path:
                raise ValueError("Select a file to upload.")
            times, vals, dt = self._read_arb_csv(path, self.arb_delim.get())
            srate = self._compute_sample_rate(times, dt)
            sig, vpp_custom = self._prepare_arb_payload(vals, self.arb_scale_mode.get())

            ch = self.channel.get()
            name = truncate_arb_name(path)

            # Clear volatile, set binary order, send data
            self._ensure_binary_preamble()
            self.scpi_write(f'SOUR{ch}:DATA:VOL:CLE')
            # Write binary values for ARB; datatype 'f' = 32-bit float, little endian (SWAP)
            self.log_line(f"Uploading ARB '{name}' to CH{ch}, samples={sig.size}, srate={srate:.6g} Hz")
            self.inst.write_binary_values(f'SOUR{ch}:DATA:ARB {name},', sig, datatype='f', is_big_endian=False)
            self.scpi_write('*WAI')

            # Select ARB, set rate and amplitude/offset
            self.scpi_write(f'SOUR{ch}:FUNC ARB')
            self.scpi_write(f'SOUR{ch}:FUNC:ARB {name}')
            self.scpi_write(f'SOUR{ch}:FUNC:ARB:SRAT {srate}')

            # Apply amplitude/offset from basic panel or custom Vpp
            if vpp_custom is not None:
                self.scpi_write(f'SOUR{ch}:VOLT {vpp_custom}')
            else:
                a = safe_float(self.amp.get())
                if a is not None and a > 0:
                    self.scpi_write(f'SOUR{ch}:VOLT {a}')
            o = safe_float(self.offset.get(), 0.0)
            self.scpi_write(f'SOUR{ch}:VOLT:OFFS {o}')

            self.log_line("ARB uploaded and applied to channel.")
        except Exception as e:
            messagebox.showerror("ARB Upload", str(e))

    def on_save_arb_internal(self):
        try:
            self._ensure_inst()
            ch = self.channel.get()
            path = self.arb_file.get().strip()
            if not path:
                raise ValueError("Select a file first to derive ARB name.")
            name = truncate_arb_name(path)
            self.scpi_write('MMEM:MDIR "INT:\\remoteAdded"')
            self.scpi_write(f'MMEM:STOR:DATA "INT:\\remoteAdded\\{name}.arb"')
            self.log_line(f"Saved to internal: INT:\\remoteAdded\\{name}.arb")
        except Exception as e:
            messagebox.showerror("Save ARB", str(e))


if __name__ == "__main__":
    app = AWGGUI()
    app.mainloop()
