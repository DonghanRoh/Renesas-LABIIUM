# scpi_tabs/function_generator_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common
import re

# ---------- helpers ----------
_SI = {
    "G": 1e9, "M": 1e6, "k": 1e3,
    "": 1.0,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9
}

def _parse_number_with_unit(label: str, kind: str):
    """
    Convert dropdown labels like '1 kHz', '100 mVpp', '10 ms', '90 °', '50 %', '1 MSa/s'
    into base units:
      kind in {'freq','srate','volt','offs','phase','time','percent','bitrate','band'}
    Returns float value in: Hz, Sa/s, V, V, deg, s, %, Hz, Hz respectively.
    """
    s = (label or "").strip()

    # Normalize special unit tokens
    s = s.replace("°", " deg")
    s = s.replace("Sa/s", "SPS")  # sample-per-second token
    s = s.replace("Vpp", " Vpp")

    # Extract number and unit parts
    m = re.match(r"^\s*([-+]?\d*\.?\d+)\s*([GMkmunµ]?)\s*([A-Za-z%]+)?\s*$", s)
    if not m:
        # fallback: just numeric
        try:
            return float(common.extract_number(s))
        except Exception:
            return 0.0

    val = float(m.group(1))
    pref = m.group(2) or ""
    unit = (m.group(3) or "").lower()

    mul = _SI.get(pref, 1.0)

    if kind in ("freq", "band", "bitrate"):
        # Hz-like
        if "hz" in unit:
            return val * mul
        return val
    if kind == "srate":
        # SPS from 'kSa/s' etc.
        if "sps" in unit:
            return val * mul
        return val
    if kind in ("volt", "offs"):
        # amplitude/offset in V or Vpp (we set VOLT as Vpp)
        # our labels are in Vpp for amplitude and V for offset
        return val * mul
    if kind == "phase":
        # degrees
        return val
    if kind == "time":
        # default seconds if unit absent
        # handle ms/us/ns in 'pref'
        if unit in ("s", "sec", "secs", "second", "seconds", ""):
            return val * mul
        return val
    if kind == "percent":
        return val
    return val

def _si_label(values, unit):
    """Helper to build labels like ['10 kHz', '1 MHz'] from numeric base-unit values."""
    out = []
    for v in values:
        abs_v = abs(v)
        if unit == "Hz" or unit == "SPS":
            if abs_v >= 1e6:
                out.append(f"{v/1e6:g} MHz" if unit=="Hz" else f"{v/1e6:g} MSa/s")
            elif abs_v >= 1e3:
                out.append(f"{v/1e3:g} kHz" if unit=="Hz" else f"{v/1e3:g} kSa/s")
            else:
                out.append(f"{v:g} Hz" if unit=="Hz" else f"{v:g} Sa/s")
        elif unit == "Vpp":
            if abs_v >= 1:
                out.append(f"{v:g} Vpp")
            else:
                out.append(f"{v*1e3:g} mVpp")
        elif unit == "V":
            if abs_v >= 1:
                out.append(f"{v:g} V")
            else:
                out.append(f"{v*1e3:g} mV")
        elif unit == "deg":
            out.append(f"{v:g} °")
        elif unit == "%":
            out.append(f"{v:g} %")
        elif unit == "s":
            if abs_v >= 1:
                out.append(f"{v:g} s")
            elif abs_v >= 1e-3:
                out.append(f"{v*1e3:g} ms")
            elif abs_v >= 1e-6:
                out.append(f"{v*1e6:g} µs")
            else:
                out.append(f"{v*1e9:g} ns")
        else:
            out.append(f"{v:g}")
    return out

class FunctionGeneratorTab:
    """
    Minimal 33612A UI:
      - Channel (1/2), Output (Off/On) — dropdowns
      - Waveform — dropdown
      - Parameters — per-waveform dropdowns (no free text)
    Removed: load/impedance, range, duty, units switching, read-back, 33250A support.
    """

    # Display names -> SCPI tokens
    WF_MAP = {
        "Sine": "SIN",
        "Square": "SQU",
        "Ramp": "RAMP",
        "Pulse": "PULS",
        "Arb": "ARB",
        "Triangle": "TRI",
        "Noise": "NOIS",
        "PRBS": "PRBS",
        "DC": "DC",
    }

    # Predefined parameter sets (base-unit values)
    PARAM_CHOICES = {
        "Sine": {
            "Frequency": _si_label([10, 100, 1e3, 10e3, 100e3, 1e6], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0, 2.0, 5.0, 10.0], "Vpp"),
            "Offset":    _si_label([-2.0, -1.0, 0.0, 1.0, 2.0], "V"),
            "Phase":     _si_label([0, 45, 90, 180], "deg"),
        },
        "Square": {
            "Frequency": _si_label([10, 100, 1e3, 10e3, 100e3, 1e6], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0, 2.0, 5.0, 10.0], "Vpp"),
            "Offset":    _si_label([-2.0, -1.0, 0.0, 1.0, 2.0], "V"),
            "Phase":     _si_label([0, 90, 180], "deg"),
        },
        "Ramp": {
            "Frequency": _si_label([10, 100, 1e3, 10e3, 100e3], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0, 2.0, 5.0], "Vpp"),
            "Offset":    _si_label([-1.0, 0.0, 1.0], "V"),
            "Phase":     _si_label([0, 90, 180], "deg"),
            "Symmetry":  _si_label([10, 25, 50, 75, 90], "%"),
        },
        "Pulse": {
            "Frequency":   _si_label([10, 100, 1e3, 10e3, 100e3], "Hz"),
            "Amplitude":   _si_label([0.1, 0.5, 1.0, 2.0, 5.0], "Vpp"),
            "Offset":      _si_label([-1.0, 0.0, 1.0], "V"),
            "Phase":       _si_label([0, 90, 180], "deg"),
            "Pulse Width": _si_label([1e-6, 10e-6, 100e-6, 1e-3, 10e-3], "s"),
            "Lead Edge":   _si_label([5e-9, 10e-9, 20e-9, 50e-9, 100e-9], "s"),
            "Trail Edge":  _si_label([5e-9, 10e-9, 20e-9, 50e-9, 100e-9], "s"),
        },
        "Arb": {
            "Sample Rate": _si_label([1e5, 1e6, 10e6, 100e6], "SPS"),
            "Amplitude":   _si_label([0.1, 0.5, 1.0, 2.0], "Vpp"),
            "Offset":      _si_label([-0.5, 0.0, 0.5, 1.0], "V"),
            "Arb Phase":   _si_label([0, 90, 180], "deg"),
        },
        "Triangle": {
            "Frequency": _si_label([10, 100, 1e3, 10e3, 100e3], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0, 2.0, 5.0], "Vpp"),
            "Offset":    _si_label([-1.0, 0.0, 1.0], "V"),
            "Phase":     _si_label([0, 90, 180], "deg"),
        },
        "Noise": {
            "Bandwidth": _si_label([10e3, 100e3, 1e6, 10e6], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0], "Vpp"),
            "Offset":    _si_label([-0.5, 0.0, 0.5], "V"),
        },
        "PRBS": {
            "Bit Rate": _si_label([1e3, 10e3, 100e3, 1e6, 10e6], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0, 2.0], "Vpp"),
            "Offset":     _si_label([-0.5, 0.0, 0.5], "V"),
            "Edge Time":  _si_label([5e-9, 10e-9, 20e-9, 50e-9], "s"),
            "Phase":      _si_label([0, 90, 180], "deg"),
        },
        "DC": {
            "Offset": _si_label([-5.0, -2.0, -1.0, 0.0, 1.0, 2.0, 5.0], "V"),
        },
    }

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Function Generator")

        # runtime detection (33612A only UI)
        self._is_33612a = False

        # UI state
        self.model_var = tk.StringVar(value="(No FGEN)")
        self.ch_var = tk.StringVar(value="1")
        self.out_var = tk.StringVar(value="Off")
        self.wave_var = tk.StringVar(value="Sine")

        # dynamic param widgets: name -> (label, combobox, var)
        self._param_widgets = {}

        self._build_ui(self.frame)
        self._wire_events()

    # ----------- UI -----------
    def _build_ui(self, parent):
        top = ttk.LabelFrame(parent, text="Keysight/Agilent 33612A")
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(top, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(top, text="Channel:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.ch_combo = ttk.Combobox(top, textvariable=self.ch_var, state="readonly", values=["1","2"], width=6)
        self.ch_combo.grid(row=0, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Label(top, text="Output:").grid(row=0, column=4, padx=6, pady=8, sticky="e")
        self.out_combo = ttk.Combobox(top, textvariable=self.out_var, state="readonly", values=["Off","On"], width=6)
        self.out_combo.grid(row=0, column=5, padx=(0,12), pady=8, sticky="w")

        ttk.Label(top, text="Waveform:").grid(row=1, column=0, padx=6, pady=8, sticky="e")
        self.wave_combo = ttk.Combobox(top, textvariable=self.wave_var, state="readonly",
                                       values=list(self.WF_MAP.keys()), width=12)
        self.wave_combo.grid(row=1, column=1, padx=(0,12), pady=8, sticky="w")

        # dynamic params frame
        self.paramsf = ttk.LabelFrame(parent, text="Parameters")
        self.paramsf.pack(fill="x", padx=10, pady=(0,10))

        # buttons
        btns = ttk.Frame(parent)
        btns.pack(fill="x", padx=10, pady=(0,10))
        ttk.Button(btns, text="Apply Settings", command=self.apply).pack(side="left", padx=6)
        ttk.Button(btns, text="Set Output", command=self.apply_output).pack(side="left", padx=6)

        # seed first render
        self._render_params_for_wave("Sine")

    def _wire_events(self):
        self.wave_combo.bind("<<ComboboxSelected>>", lambda *_: self._render_params_for_wave(self.wave_var.get()))

    def _clear_params(self):
        for w in list(self._param_widgets.values()):
            try:
                w[0].destroy(); w[1].destroy()
            except Exception:
                pass
        self._param_widgets.clear()

    def _render_params_for_wave(self, wave_name: str):
        self._clear_params()
        wave = wave_name if wave_name in self.PARAM_CHOICES else "Sine"
        row = 0
        for pname, options in self.PARAM_CHOICES[wave].items():
            ttk.Label(self.paramsf, text=f"{pname}:").grid(row=row, column=0, padx=6, pady=6, sticky="e")
            var = tk.StringVar(value=options[0] if options else "")
            cb = ttk.Combobox(self.paramsf, textvariable=var, state="readonly", values=options, width=16)
            cb.grid(row=row, column=1, padx=(0,12), pady=6, sticky="w")
            self._param_widgets[pname] = (cb, var)
            row += 1

        # column stretch
        for c, w in enumerate([0,1]):
            self.paramsf.grid_columnconfigure(c, weight=w)

    # ----------- device state -----------
    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state=("normal" if enabled else "disabled"))
        except Exception:
            pass

    def update_for_active_device(self):
        inst = self.get_inst()
        idn = (self.get_idn() or "").strip()
        up = idn.upper()
        self._is_33612a = ("33612A" in up)
        if not inst or not idn or not self._is_33612a:
            self.model_var.set("(No FGEN)")
            self.set_enabled(False)
            return
        self.model_var.set(idn)
        self.set_enabled(True)

    # ----------- SCPI helpers -----------
    def _src(self) -> str:
        ch = (self.ch_var.get() or "1").strip()
        if ch not in ("1","2"): ch = "1"
        return f"SOUR{ch}:"

    def _outp(self) -> str:
        ch = (self.ch_var.get() or "1").strip()
        if ch not in ("1","2"): ch = "1"
        return f"OUTP{ch}:"

    # ----------- apply ops -----------
    def apply_output(self):
        try:
            inst = self.get_inst()
            if not inst or not self._is_33612a: return
            outp = self._outp()
            val = "ON" if (self.out_var.get() or "Off").lower() == "on" else "OFF"
            common.try_sequences(inst, [
                [f"{outp}STAT {val}"],
                [f"{outp}{val}"],
            ])
            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Output -> {val} (CH={self.ch_var.get()})")
            self.status.set(f"FGEN output {val}.")
        except Exception as e:
            messagebox.showerror("FGEN Output failed", str(e))

    def apply(self):
        """
        Apply waveform + parameters from dropdowns.
        Only minimal 33612A commands are used; where syntax differs, try_sequences covers variants.
        """
        try:
            inst = self.get_inst()
            if not inst or not self._is_33612a: return

            src = self._src()
            wave_name = self.wave_var.get()
            wf = self.WF_MAP.get(wave_name, "SIN")

            # Switch function first
            common.try_sequences(inst, [
                [f"{src}FUNC {wf}"],
                [f"{src}APPL:{wf}"],
            ])

            # Pull params (strings) and convert
            def get(name, kind):
                _, var = self._param_widgets.get(name, (None, None))
                if not var: return None
                return _parse_number_with_unit(var.get(), kind)

            # Common params
            freq   = get("Frequency", "freq")
            amp    = get("Amplitude", "volt")
            offs   = get("Offset", "offs")
            phase  = get("Phase", "phase")

            # Waveform-specific
            symm   = get("Symmetry", "percent")
            pwidth = get("Pulse Width", "time")
            lead   = get("Lead Edge", "time")
            trail  = get("Trail Edge", "time")
            srate  = get("Sample Rate", "srate")
            aphase = get("Arb Phase", "phase")
            bw     = get("Bandwidth", "band")
            brate  = get("Bit Rate", "bitrate")
            etime  = get("Edge Time", "time")

            # Apply amplitude unit (Vpp) to be explicit
            try:
                inst.write(f"{src}VOLT:UNIT VPP")
            except Exception:
                pass

            # Apply basics via APPL if available, else separate commands
            if wf in ("SIN", "SQU", "RAMP", "TRI", "PULS"):
                if freq is not None and amp is not None and offs is not None:
                    common.try_sequences(inst, [
                        [f"{src}APPL:{wf} {freq},{amp},{offs}"],
                    ])
                else:
                    # fallback granular
                    if freq is not None: inst.write(f"{src}FREQ {freq}")
                    if amp  is not None: inst.write(f"{src}VOLT {amp}")
                    if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")
                if phase is not None:
                    common.try_sequences(inst, [
                        [f"{src}PHAS {phase}"],
                        [f"{src}FUNC:PHAS {phase}"],
                    ])
                if wf == "RAMP" and symm is not None:
                    common.try_sequences(inst, [
                        [f"{src}FUNC:RAMP:SYMM {symm}"],
                        [f"{src}RAMP:SYMM {symm}"],
                    ])
                if wf == "PULS":
                    if pwidth is not None:
                        common.try_sequences(inst, [
                            [f"{src}PULS:WIDT {pwidth}"],
                            [f"{src}FUNC:PULS:WIDT {pwidth}"],
                        ])
                    if lead is not None:
                        common.try_sequences(inst, [
                            [f"{src}PULS:TRAN:LEAD {lead}"],
                            [f"{src}PULS:TRAN:LEADing {lead}"],
                        ])
                    if trail is not None:
                        common.try_sequences(inst, [
                            [f"{src}PULS:TRAN:TRA {trail}"],
                            [f"{src}PULS:TRAN:TRAiling {trail}"],
                        ])

            elif wf == "ARB":
                if srate is not None:
                    common.try_sequences(inst, [
                        [f"{src}ARB:SRAT {srate}"],
                        [f"{src}ARB:SRATe {srate}"],
                    ])
                if aphase is not None:
                    common.try_sequences(inst, [
                        [f"{src}FUNC:ARB:PHAS {aphase}"],
                        [f"{src}ARB:PHAS {aphase}"],
                    ])
                if amp  is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "NOIS":
                if bw is not None:
                    common.try_sequences(inst, [
                        [f"{src}FUNC:NOIS:BAND {bw}"],
                        [f"{src}NOIS:BAND {bw}"],
                    ])
                if amp  is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "PRBS":
                if brate is not None:
                    common.try_sequences(inst, [
                        [f"{src}FUNC:PRBS:BRAT {brate}"],
                        [f"{src}PRBS:BRAT {brate}"],
                    ])
                if etime is not None:
                    common.try_sequences(inst, [
                        [f"{src}FUNC:PRBS:TRAN {etime}"],
                        [f"{src}PRBS:TRAN {etime}"],
                    ])
                if phase is not None:
                    common.try_sequences(inst, [
                        [f"{src}PHAS {phase}"],
                        [f"{src}FUNC:PHAS {phase}"],
                    ])
                if amp  is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "DC":
                if offs is not None:
                    common.try_sequences(inst, [
                        [f"{src}APPL:DC DEF,DEF,{offs}"],
                        [f"{src}FUNC DC", f"{src}VOLT:OFFS {offs}"],
                    ])

            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Apply -> CH={self.ch_var.get()}, WF={wave_name}")
            self.status.set("FGEN settings applied.")
        except Exception as e:
            messagebox.showerror("FGEN Apply failed", str(e))
