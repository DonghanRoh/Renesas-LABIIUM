# scpi_tabs/multi_meter_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class MultiMeterTab:
    """Multi Meter tab UI + basic SCPI ops.
    IDNs: 34410A, 34461A, 4040*, 34465A, 34470A, 2000, 3458A   (*4040 but not HMP4040)
    """

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Multi Meter")

        self.model_var = tk.StringVar(value="")
        self.mode_var = tk.StringVar(value="VOLT:DC")
        self.reading_var = tk.StringVar(value="")
        self._build_ui(self.frame)

    def _build_ui(self, parent):
        f = ttk.LabelFrame(parent, text="Multi Meter Controls")
        f.pack(fill="x", padx=10, pady=10)

        ttk.Label(f, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(f, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Mode:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.mode_combo = ttk.Combobox(f, textvariable=self.mode_var, state="readonly",
                                       values=["VOLT:DC", "VOLT:AC", "CURR:DC", "RES", "FREQ"], width=12)
        self.mode_combo.grid(row=0, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Button(f, text="Set Mode", command=self.set_mode).grid(row=0, column=4, padx=6, pady=8)
        ttk.Button(f, text="Query Reading", command=self.query_measurement).grid(row=0, column=5, padx=6, pady=8)

        ttk.Label(f, text="Reading:").grid(row=1, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.reading_var, width=18, state="readonly").grid(row=1, column=1, padx=(0,12), pady=8, sticky="w")

        for c, w in enumerate([0,1,0,1,0,0]):
            f.grid_columnconfigure(c, weight=w)

    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state="normal" if enabled else "disabled")
        except Exception:
            pass

    def update_for_active_device(self):
        inst = self.get_inst()
        idn = self.get_idn()
        if not inst or not idn or not common.is_supported_dmm(idn):
            self.model_var.set("(No DMM)")
            self.set_enabled(False)
            return
        self.model_var.set((idn or "").strip())
        self.set_enabled(True)

    # -- ops --
    def set_mode(self):
        try:
            inst = self.get_inst()
            if not inst: return
            idn = (self.get_idn() or "").upper()
            mode = (self.mode_var.get() or "VOLT:DC").upper()
            sequences = [
                [f"CONF:{mode}"],
                [f"FUNC '{mode}'"],
                [f"FUNC {mode}"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[DMM]")
            self.log(f"[DMM] Set Mode -> {mode} | IDN={idn}")
        except Exception as e:
            messagebox.showerror("DMM Set Mode failed", str(e))

    def query_measurement(self):
        try:
            inst = self.get_inst()
            if not inst: return
            mode = (self.mode_var.get() or "VOLT:DC").upper()

            candidates = [f"MEAS:{mode}?", "READ?", "FETCh?", "MEAS?"]
            last_err = None
            for cmd in candidates:
                try:
                    resp = (inst.query(cmd) or "").strip()
                    if resp:
                        self.reading_var.set(common.extract_number(resp))
                        self.log(f"[DMM] {cmd} -> {resp}")
                        common.drain_error_queue(inst, self.log, "[DMM]")
                        return
                except Exception as e:
                    last_err = e
                    continue
            if last_err:
                raise last_err
            raise RuntimeError("No response for DMM measurement.")
        except Exception as e:
            messagebox.showerror("DMM Query failed", str(e))
