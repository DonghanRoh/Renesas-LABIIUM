# scpi_tabs/multi_meter_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

# ---- helpers ----
def _fnum(s, default=None):
    try:
        x = float(common.extract_number(s))
        return x
    except Exception:
        return default

def _trim(s):
    return common.trim(s)

class MultiMeterTab:
    """
    Simplified DMM tab:
      - Modes: DCV, DCI only
      - Range: model-specific dropdown
      - Auto Range: dropdown (ON/OFF)
      - Removed: trigger/multipoint/statistics/extra options
    Supported IDNs (detected for range list tailoring):
      - Keysight 3446x (34461A/34465A/34470A)
      - Keysight 34410A
      - Tektronix DMM4040 (4040)
      - Keithley 2000
      - HP 3458A
    """

    # UI-facing modes
    UI_MODES = ["DCV", "DCI"]
    # Mapping to SCPI function names
    MODE_TO_SCPI = {
        "DCV": "VOLT:DC",
        "DCI": "CURR:DC",
    }

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Multi Meter")

        # runtime-detected model hints
        self._is_3458a = False
        self._is_k2000 = False
        self._is_3446x = False  # 34461A/65A/70A
        self._is_34410a = False
        self._is_dmm4040 = False

        # UI state variables
        self.model_var    = tk.StringVar(value="(No DMM)")
        self.mode_var     = tk.StringVar(value="DCV")    # DCV / DCI
        self.reading_var  = tk.StringVar(value="")

        self.auto_var     = tk.StringVar(value="ON")     # Auto Range ON/OFF
        self.range_var    = tk.StringVar(value="")       # human-readable, e.g., "0.1 V" or "0.0001 A"

        self._build_ui(self.frame)
        self._wire_dynamic_ui()

    # ---------------- UI BUILD ----------------
    def _build_ui(self, parent):
        # Top: model + mode + reading/result
        top = ttk.LabelFrame(parent, text="DMM")
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Model:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Label(top, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        ttk.Label(top, text="Mode:").grid(row=0, column=2, padx=6, pady=6, sticky="e")
        self.mode_combo = ttk.Combobox(top, textvariable=self.mode_var, state="readonly",
                                       values=self.UI_MODES, width=8)
        self.mode_combo.grid(row=0, column=3, padx=(0,12), pady=6, sticky="w")

        ttk.Button(top, text="Apply Mode", command=self.set_mode).grid(row=0, column=4, padx=6, pady=6)
        ttk.Button(top, text="Read / Fetch", command=self.query_measurement).grid(row=0, column=5, padx=6, pady=6)

        ttk.Label(top, text="Reading:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(top, textvariable=self.reading_var, width=18, state="readonly").grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")

        for c, w in enumerate([0,1,0,1,0,0]):
            top.grid_columnconfigure(c, weight=w)

        # Configure group: Auto + Range
        cfg = ttk.LabelFrame(parent, text="Measure Configuration")
        cfg.pack(fill="x", padx=10, pady=(0,10))

        # Auto Range (dropdown)
        ttk.Label(cfg, text="Auto Range:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.auto_combo = ttk.Combobox(cfg, textvariable=self.auto_var, state="readonly",
                                       values=["ON", "OFF"], width=8)
        self.auto_combo.grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        # Range (dropdown; populated per model + mode)
        ttk.Label(cfg, text="Range:").grid(row=0, column=2, padx=6, pady=6, sticky="e")
        self.range_combo = ttk.Combobox(cfg, textvariable=self.range_var, state="readonly", width=12)
        self.range_combo.grid(row=0, column=3, padx=(0,12), pady=6, sticky="w")

        ttk.Button(cfg, text="Apply Range", command=self.apply_settings).grid(row=0, column=5, padx=6, pady=6, sticky="e")

        for c, w in enumerate([0,1,0,1,0,1]):
            cfg.grid_columnconfigure(c, weight=w)

    def _wire_dynamic_ui(self):
        # Mode change -> refresh ranges for that mode
        def on_mode_change(*_):
            self._refresh_range_choices()
        self.mode_combo.bind("<<ComboboxSelected>>", on_mode_change)

        # Auto change -> enable/disable range combobox
        def on_auto_change(*_):
            auto = (self.auto_var.get() or "ON").upper()
            try:
                self.range_combo.configure(state=("disabled" if auto == "ON" else "readonly"))
            except Exception:
                pass
        self.auto_combo.bind("<<ComboboxSelected>>", on_auto_change)

    # --------------- State / Model detection ---------------
    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state="normal" if enabled else "disabled")
        except Exception:
            pass

    def update_for_active_device(self):
        inst = self.get_inst()
        idn  = self.get_idn()
        if not inst or not idn or not common.is_supported_dmm(idn):
            self.model_var.set("(No DMM)")
            self.set_enabled(False)
            return

        up = (idn or "").upper()
        self._is_3458a   = ("3458A" in up)
        self._is_k2000   = ("2000" in up) and ("KEITHLEY" in up or "MODEL 2000" in up)
        self._is_3446x   = any(t in up for t in ("34461A","34465A","34470A"))
        self._is_34410a  = ("34410A" in up)
        self._is_dmm4040 = ("4040" in up and "HMP4040" not in up)

        self.model_var.set((idn or "").strip())
        self.set_enabled(True)
        self._refresh_range_choices()
        # reflect auto state in range widget
        try:
            self.range_combo.configure(state=("disabled" if (self.auto_var.get() or "ON").upper() == "ON" else "readonly"))
        except Exception:
            pass

    # --------------- Helpers ----------------
    def _sense_path(self) -> str:
        """Return 'SENS:<func>' based on UI mode."""
        ui_mode = (self.mode_var.get() or "DCV").upper()
        func = self.MODE_TO_SCPI.get(ui_mode, "VOLT:DC")
        return f"SENS:{func}"

    def _meas_query(self) -> str:
        """Return 'MEAS:<func>?' based on UI mode."""
        ui_mode = (self.mode_var.get() or "DCV").upper()
        func = self.MODE_TO_SCPI.get(ui_mode, "VOLT:DC")
        return f"MEAS:{func}?"

    def _range_choices_for_model(self, ui_mode: str):
        """Return list[str] of human-readable ranges for the given mode."""
        ui_mode = (ui_mode or "DCV").upper()

        # Default conservative sets
        default = {
            "DCV": ["0.1 V", "1 V", "10 V", "100 V", "1000 V"],
            "DCI": ["0.0001 A", "0.001 A", "0.01 A", "0.1 A", "1 A"],
        }

        # Keysight 3446x: typical rich range set (keep conservative values; instruments may accept more)
        if self._is_3446x:
            keysight_3446x = {
                "DCV": ["0.1 V", "1 V", "10 V", "100 V", "1000 V"],
                "DCI": ["0.0001 A", "0.001 A", "0.01 A", "0.1 A", "1 A"],
            }
            return keysight_3446x.get(ui_mode, default[ui_mode])

        # Keysight 34410A
        if self._is_34410a:
            a34410a = {
                "DCV": ["0.1 V", "1 V", "10 V", "100 V", "1000 V"],
                "DCI": ["0.0001 A", "0.001 A", "0.01 A", "0.1 A", "1 A"],
            }
            return a34410a.get(ui_mode, default[ui_mode])

        # Keithley 2000 (safe set)
        if self._is_k2000:
            k2000 = {
                "DCV": ["0.1 V", "1 V", "10 V", "100 V", "1000 V"],
                "DCI": ["0.001 A", "0.01 A", "0.1 A", "1 A"],
            }
            return k2000.get(ui_mode, default[ui_mode])

        # Tektronix DMM4040 (safe set)
        if self._is_dmm4040:
            dmm4040 = {
                "DCV": ["0.1 V", "1 V", "10 V", "100 V", "1000 V"],
                "DCI": ["0.0001 A", "0.001 A", "0.01 A", "0.1 A", "1 A"],
            }
            return dmm4040.get(ui_mode, default[ui_mode])

        # HP 3458A (DCV has finer low range; current kept conservative)
        if self._is_3458a:
            a3458a = {
                "DCV": ["0.01 V", "0.1 V", "1 V", "10 V", "100 V", "1000 V"],
                "DCI": ["0.01 A", "0.1 A", "1 A"],
            }
            return a3458a.get(ui_mode, default[ui_mode])

        # Fallback
        return default.get(ui_mode, [])

    def _refresh_range_choices(self):
        """Populate range dropdown according to current mode & model."""
        ui_mode = (self.mode_var.get() or "DCV").upper()
        choices = self._range_choices_for_model(ui_mode)
        try:
            self.range_combo["values"] = choices
        except Exception:
            pass
        # If current selection not in new choices, pick a sensible default
        cur = self.range_var.get()
        if cur not in choices:
            # choose mid or first item
            sel = choices[min(len(choices)//2, len(choices)-1)] if choices else ""
            self.range_var.set(sel)

    # --------------- Ops: Mode / Settings ----------------
    def set_mode(self):
        """Apply DCV/DCI function on the instrument."""
        try:
            inst = self.get_inst()
            if not inst:
                return
            ui_mode = (self.mode_var.get() or "DCV").upper()
            mode_scpi = self.MODE_TO_SCPI.get(ui_mode, "VOLT:DC")

            # Prefer CONF:<mode> first, then FUNC fallback
            common.try_sequences(inst, [
                [f"CONF:{mode_scpi}"],
                [f"FUNC '{mode_scpi}'"],
                [f"FUNC {mode_scpi}"],
            ])

            common.drain_error_queue(inst, self.log, "[DMM]")
            self.log(f"[DMM] Set Mode -> {ui_mode} ({mode_scpi})")
            self.status.set(f"DMM mode set: {ui_mode}")
        except Exception as e:
            messagebox.showerror("DMM Set Mode failed", str(e))

    def apply_settings(self):
        """Apply Auto Range and (if OFF) fixed Range."""
        try:
            inst = self.get_inst()
            if not inst:
                return
            sense = self._sense_path()
            auto = (self.auto_var.get() or "ON").upper()

            # Auto range on/off
            if auto == "ON":
                common.try_sequences(inst, [
                    [f"{sense}:RANG:AUTO ON"],
                    [f"{sense}:RANG:AUTO 1"],
                ])
            else:
                # Fixed range via dropdown value
                rng_val = _fnum(self.range_var.get(), None)
                if rng_val is None:
                    messagebox.showinfo("No Range", "Select a fixed range from the dropdown or set Auto=ON.")
                    return
                common.try_sequences(inst, [
                    [f"{sense}:RANG {rng_val}"],
                ])

            # Reflect auto state in widget interactivity
            try:
                self.range_combo.configure(state=("disabled" if auto == "ON" else "readonly"))
            except Exception:
                pass

            common.drain_error_queue(inst, self.log, "[DMM]")
            self.log(f"[DMM] Apply Settings -> auto={auto}, range={self.range_var.get()}")
            self.status.set(f"DMM settings applied (Auto={auto}).")
        except Exception as e:
            messagebox.showerror("DMM Apply Settings failed", str(e))

    # --------------- Ops: Measure ----------------
    def query_measurement(self):
        """Best-effort single reading based on mode."""
        try:
            inst = self.get_inst()
            if not inst:
                return

            # Try MEAS:<mode>? first, then typical fallbacks
            candidates = [
                self._meas_query(),
                "READ?",
                "INIT;*WAI;FETCh?",
                "FETCh?",
                "MEAS?",
            ]
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
