# scpi_tabs/function_generator_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class FunctionGeneratorTab:
    """Function Generator tab UI + extended SCPI ops.
    IDNs: Keysight/Agilent 33250A, 33612A
    """

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Function Generator")

        # State vars
        self.model_var   = tk.StringVar(value="")
        self.waveform_var = tk.StringVar(value="SIN")
        self.freq_var    = tk.StringVar(value="1000")
        self.amp_var     = tk.StringVar(value="1.0")
        self.offset_var  = tk.StringVar(value="0.0")
        self.phase_var   = tk.StringVar(value="0.0")
        self.duty_var    = tk.StringVar(value="50")
        self.load_var    = tk.StringVar(value="INF")

        self._build_ui(self.frame)

    def _build_ui(self, parent):
        f = ttk.LabelFrame(parent, text="Function Generator Controls")
        f.pack(fill="x", padx=10, pady=10)

        # Model
        ttk.Label(f, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(f, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")

        # Waveform
        ttk.Label(f, text="Waveform:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.wave_combo = ttk.Combobox(f, textvariable=self.waveform_var, state="readonly",
                                       values=["SIN","SQU","RAMP","PULSE","NOIS","DC"], width=10)
        self.wave_combo.grid(row=0, column=3, padx=(0,12), pady=8, sticky="w")

        # Frequency, Amplitude, Offset
        ttk.Label(f, text="Freq (Hz):").grid(row=1, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.freq_var, width=12).grid(row=1, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Amp (Vpp):").grid(row=1, column=2, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.amp_var, width=10).grid(row=1, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Offset (V):").grid(row=1, column=4, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.offset_var, width=10).grid(row=1, column=5, padx=(0,12), pady=8, sticky="w")

        # Phase, Duty, Load
        ttk.Label(f, text="Phase (deg):").grid(row=2, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.phase_var, width=10).grid(row=2, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Duty (%):").grid(row=2, column=2, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.duty_var, width=10).grid(row=2, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Load (Ω):").grid(row=2, column=4, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.load_var, width=10).grid(row=2, column=5, padx=(0,12), pady=8, sticky="w")

        # Buttons
        ttk.Button(f, text="Apply", command=self.apply).grid(row=3, column=0, padx=6, pady=8)
        ttk.Button(f, text="Output ON", command=lambda: self.output(True)).grid(row=3, column=1, padx=6, pady=8)
        ttk.Button(f, text="Output OFF", command=lambda: self.output(False)).grid(row=3, column=2, padx=6, pady=8)
        ttk.Button(f, text="Read Back", command=self.read_back).grid(row=3, column=3, padx=6, pady=8)

        for c, w in enumerate([0,1,0,1,0,1]):
            f.grid_columnconfigure(c, weight=w)

    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state="normal" if enabled else "disabled")
        except Exception:
            pass

    def update_for_active_device(self):
        inst = self.get_inst()
        idn = self.get_idn()
        if not inst or not idn or not common.is_supported_fgen(idn):
            self.model_var.set("(No FGEN)")
            self.set_enabled(False)
            return
        self.model_var.set((idn or "").strip())
        self.set_enabled(True)

    # -- ops --
    def apply(self):
        try:
            inst = self.get_inst()
            if not inst: return
            wave = (self.waveform_var.get() or "SIN").upper()
            freq = float(self.freq_var.get())
            amp  = float(self.amp_var.get())
            offs = float(self.offset_var.get())
            pha  = float(self.phase_var.get())
            duty = float(self.duty_var.get())
            load = self.load_var.get().upper()

            sequences = [
                [f"APPL:{wave} {freq},{amp},{offs}"],  # Primary
                [f"FUNC {wave}", f"FREQ {freq}", f"VOLT {amp}", f"VOLT:OFFS {offs}"],
            ]
            common.try_sequences(inst, sequences)

            # Apply duty for square/pulse only
            if wave in ("SQU","PULSE"):
                try:
                    inst.write(f"FUNC:SQU:DCYC {duty}")
                except Exception:
                    inst.write(f"FUNCtion:SQUare:DCYCle {duty}")

            # Apply phase
            try:
                inst.write(f"PHAS {pha}")
            except Exception:
                try:
                    inst.write(f"FUNC:PHAS {pha}")
                except Exception:
                    pass

            # Apply load
            try:
                inst.write(f"OUTP:LOAD {load}")
            except Exception:
                pass

            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Apply -> W={wave}, F={freq}, A={amp}, O={offs}, P={pha}, D={duty}, L={load}")
            self.status.set("FGEN applied.")
        except Exception as e:
            messagebox.showerror("FGEN Apply failed", str(e))

    def output(self, on: bool):
        try:
            inst = self.get_inst()
            if not inst: return
            val = "ON" if on else "OFF"
            sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Output -> {val}")
            self.status.set(f"FGEN output {val}.")
        except Exception as e:
            messagebox.showerror("FGEN Output failed", str(e))

    def read_back(self):
        """Query back current FGEN settings for confirmation."""
        try:
            inst = self.get_inst()
            if not inst: return
            wave = inst.query("FUNC?").strip()
            freq = inst.query("FREQ?").strip()
            amp  = inst.query("VOLT?").strip()
            offs = inst.query("VOLT:OFFS?").strip()
            pha  = inst.query("PHAS?").strip()
            duty = ""
            if wave.upper().startswith("SQU"):
                try: duty = inst.query("FUNC:SQU:DCYC?").strip()
                except Exception: pass
            load = inst.query("OUTP:LOAD?").strip()
            msg = f"Wave={wave}, F={freq}, A={amp}, O={offs}, P={pha}, Duty={duty}, Load={load}"
            self.log(f"[FGEN] Read Back -> {msg}")
            self.status.set("FGEN settings read.")
            messagebox.showinfo("FGEN Settings", msg)
        except Exception as e:
            messagebox.showerror("FGEN Read Back failed", str(e))
