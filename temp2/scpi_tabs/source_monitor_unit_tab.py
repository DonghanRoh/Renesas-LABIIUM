# scpi_tabs/source_monitor_unit_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class SourceMonitorUnitTab:
    """Source Monitor Unit tab UI + basic SCPI ops.
    IDNs: Keithley 2420/2440/2450/2460/2461 (MODEL 24xx/246x)
    """

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Source Monitor Unit")

        self.model_var = tk.StringVar(value="")
        self.sourcemode_var = tk.StringVar(value="VOLT")  # VOLT or CURR
        self.level_var = tk.StringVar(value="")
        self.meas_v_var = tk.StringVar(value="")
        self.meas_i_var = tk.StringVar(value="")
        self._build_ui(self.frame)

    def _build_ui(self, parent):
        f = ttk.LabelFrame(parent, text="Source Monitor Unit Controls")
        f.pack(fill="x", padx=10, pady=10)

        ttk.Label(f, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(f, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Source Mode:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.mode_combo = ttk.Combobox(f, textvariable=self.sourcemode_var, state="readonly",
                                       values=["VOLT", "CURR"], width=10)
        self.mode_combo.grid(row=0, column=3, padx=(0,12), pady=8, sticky="w")
        ttk.Button(f, text="Set Mode", command=self.set_source_mode).grid(row=0, column=4, padx=6, pady=8)

        ttk.Label(f, text="Level:").grid(row=1, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.level_var, width=12).grid(row=1, column=1, padx=(0,12), pady=8, sticky="w")
        ttk.Button(f, text="Apply Level", command=self.set_level).grid(row=1, column=2, padx=6, pady=8)
        ttk.Button(f, text="Output ON", command=lambda: self.output(True)).grid(row=1, column=3, padx=6, pady=8)
        ttk.Button(f, text="Output OFF", command=lambda: self.output(False)).grid(row=1, column=4, padx=6, pady=8)

        ttk.Label(f, text="Measure V (V):").grid(row=2, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.meas_v_var, width=14, state="readonly").grid(row=2, column=1, padx=(0,12), pady=8, sticky="w")
        ttk.Button(f, text="Query V", command=self.measure_v).grid(row=2, column=2, padx=6, pady=8)

        ttk.Label(f, text="Measure I (A):").grid(row=3, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.meas_i_var, width=14, state="readonly").grid(row=3, column=1, padx=(0,12), pady=8, sticky="w")
        ttk.Button(f, text="Query I", command=self.measure_i).grid(row=3, column=2, padx=6, pady=8)

        for c, w in enumerate([0,1,0,0,0]):
            f.grid_columnconfigure(c, weight=w)

    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state="normal" if enabled else "disabled")
        except Exception:
            pass

    def update_for_active_device(self):
        inst = self.get_inst()
        idn = self.get_idn()
        if not inst or not idn or not common.is_supported_smu(idn):
            self.model_var.set("(No SMU)")
            self.set_enabled(False)
            return
        self.model_var.set((idn or "").strip())
        self.set_enabled(True)

    # -- ops --
    def set_source_mode(self):
        try:
            inst = self.get_inst()
            if not inst: return
            mode = (self.sourcemode_var.get() or "VOLT").upper()
            sequences = [
                [f"SOUR:FUNC {mode}"],
                [f"SOURce:FUNCTION {mode}"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[SMU]")
            self.log(f"[SMU] Set Source Mode -> {mode}")
        except Exception as e:
            messagebox.showerror("SMU Set Mode failed", str(e))

    def set_level(self):
        try:
            inst = self.get_inst()
            if not inst: return
            mode = (self.sourcemode_var.get() or "VOLT").upper()
            val = float(self.level_var.get())
            if mode == "VOLT":
                sequences = [[f"SOUR:VOLT {val}"], [f"SOURce:VOLTage {val}"]]
            else:
                sequences = [[f"SOUR:CURR {val}"], [f"SOURce:CURRent {val}"]]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[SMU]")
            self.log(f"[SMU] Apply Level -> {val} ({mode})")
        except Exception as e:
            messagebox.showerror("SMU Apply Level failed", str(e))

    def output(self, on: bool):
        try:
            inst = self.get_inst()
            if not inst: return
            val = "ON" if on else "OFF"
            sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[SMU]")
            self.log(f"[SMU] Output -> {val}")
        except Exception as e:
            messagebox.showerror("SMU Output failed", str(e))

    def measure_v(self):
        try:
            inst = self.get_inst()
            if not inst: return
            candidates = ["MEAS:VOLT?", "MEAS:VOLT:DC?", "READ?"]
            for cmd in candidates:
                try:
                    resp = (inst.query(cmd) or "").strip()
                    if resp:
                        self.meas_v_var.set(common.extract_number(resp))
                        self.log(f"[SMU] {cmd} -> {resp}")
                        common.drain_error_queue(inst, self.log, "[SMU]")
                        return
                except Exception:
                    continue
            raise RuntimeError("No response for SMU voltage measure.")
        except Exception as e:
            messagebox.showerror("SMU Query V failed", str(e))

    def measure_i(self):
        try:
            inst = self.get_inst()
            if not inst: return
            candidates = ["MEAS:CURR?", "MEAS:CURR:DC?", "READ?"]
            for cmd in candidates:
                try:
                    resp = (inst.query(cmd) or "").strip()
                    if resp:
                        self.meas_i_var.set(common.extract_number(resp))
                        self.log(f"[SMU] {cmd} -> {resp}")
                        common.drain_error_queue(inst, self.log, "[SMU]")
                        return
                except Exception:
                    continue
            raise RuntimeError("No response for SMU current measure.")
        except Exception as e:
            messagebox.showerror("SMU Query I failed", str(e))
