# scpi_tabs/function_generator_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class FunctionGeneratorTab:
    """Function Generator tab UI + basic SCPI ops.
    IDNs: 33250A, 33612A
    """

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Function Generator")

        self.model_var = tk.StringVar(value="")
        self.waveform_var = tk.StringVar(value="SIN")
        self.freq_var = tk.StringVar(value="1000")
        self.amp_var = tk.StringVar(value="1.0")
        self.offset_var = tk.StringVar(value="0.0")
        self._build_ui(self.frame)

    def _build_ui(self, parent):
        f = ttk.LabelFrame(parent, text="Function Generator Controls")
        f.pack(fill="x", padx=10, pady=10)

        ttk.Label(f, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(f, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Waveform:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.wave_combo = ttk.Combobox(f, textvariable=self.waveform_var, state="readonly",
                                       values=["SIN","SQU","RAMP","PULSE","NOIS","DC"], width=10)
        self.wave_combo.grid(row=0, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Freq (Hz):").grid(row=1, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.freq_var, width=12).grid(row=1, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Amp (Vpp):").grid(row=1, column=2, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.amp_var, width=10).grid(row=1, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Offset (V):").grid(row=1, column=4, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.offset_var, width=10).grid(row=1, column=5, padx=(0,12), pady=8, sticky="w")

        ttk.Button(f, text="Apply", command=self.apply).grid(row=2, column=0, padx=6, pady=8)
        ttk.Button(f, text="Output ON", command=lambda: self.output(True)).grid(row=2, column=1, padx=6, pady=8)
        ttk.Button(f, text="Output OFF", command=lambda: self.output(False)).grid(row=2, column=2, padx=6, pady=8)

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

            sequences = [
                [f"APPL:{wave} {freq},{amp},{offs}"],
                [f"FUNC {wave}", f"FREQ {freq}", f"VOLT {amp}", f"VOLT:OFFS {offs}"],
                [f"FUNC {wave}", f"FREQuency {freq}", f"VOLTage {amp}", f"VOLTage:OFFSet {offs}"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Apply -> W={wave}, F={freq}, A={amp}, O={offs}")
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
        except Exception as e:
            messagebox.showerror("FGEN Output failed", str(e))
