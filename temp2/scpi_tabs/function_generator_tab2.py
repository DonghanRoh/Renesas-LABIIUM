# scpi_tabs/function_generator_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common
import re

# ---------- parsing helpers (free-text -> base units) ----------
_SI = {
    "G": 1e9, "M": 1e6, "k": 1e3, "": 1.0, "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12
}
def _num_si(s):
    """Return (value, unit_str) from free text like '2.5 kHz', '10 ms', '500 mVpp'."""
    s = (s or "").strip()
    if not s:
        return None, ""
    # normalize
    s = (s.replace("°", " deg")
           .replace("Sa/s", " SPS")
           .replace("Vpp", " Vpp")
           .replace("Vrms"," Vrms")
           .replace("dBm"," dBm"))
    m = re.search(r"([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*([GMkmunµp]?)\s*([A-Za-z/%]+)?", s)
    if not m:
        try:
            return float(common.extract_number(s)), ""
        except Exception:
            return None, ""
    val = float(m.group(1))
    pref = m.group(2) or ""
    unit = (m.group(3) or "").strip()
    mul = _SI.get(pref, 1.0)
    return val * mul, unit

def _parse(s, kind, default=None):
    """
    kind ∈ {'freq','srate','volt','offs','phase','time','percent','bitrate','band'}
    returns base units: Hz, Sa/s, V, V, deg, s, %, Hz, Hz
    """
    v, _u = _num_si(s)
    if v is None:
        return default
    return v

def _fnum(s, default=0.0):
    try:
        return float(common.extract_number(s))
    except Exception:
        return float(default)

class FunctionGeneratorTab:
    """
    Keysight/Agilent 33612A 전용 UI
      - 채널1/채널2 각각: Waveform 드롭다운 + 해당 파형의 파라미터를 모두 수동 입력(Entry)
      - 채널1/채널2 각각: Output ON/OFF, Output Load(50Ω/High Z/Specify), Range(Auto/Hold)
    주의: APPLy 명령이 Autorange를 다시 켤 수 있으므로, Range=Hold면 파형 적용 후 Autorange OFF 재적용.
    """

    WF_MAP = {
        "Sine": "SIN", "Square": "SQU", "Ramp": "RAMP", "Pulse": "PULS",
        "Arb": "ARB", "Triangle": "TRI", "Noise": "NOIS", "PRBS": "PRBS", "DC": "DC",
    }

    PARAM_LAYOUTS = {
        # label -> key
        "Sine":      [("Frequency", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase")],
        "Square":    [("Frequency", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase")],
        "Triangle":  [("Frequency", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase")],
        "Ramp":      [("Frequency", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase"),
                      ("Symmetry (%)", "symm")],
        "Pulse":     [("Frequency", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase"),
                      ("Pulse Width (s)", "pwidth"), ("Lead Edge (s)", "lead"), ("Trail Edge (s)", "trail")],
        "Arb":       [("Sample Rate (Sa/s)", "srate"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"),
                      ("Arb Phase (deg)", "aphase")],
        "Noise":     [("Bandwidth (Hz)", "bw"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs")],
        "PRBS":      [("Bit Rate (Hz)", "brate"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"),
                      ("Edge Time (s)", "etime"), ("Phase (deg)", "phase")],
        "DC":        [("Offset (V)", "offs")],
    }

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Function Generator")

        self._is_33612a = False

        # ------- top header -------
        top = ttk.LabelFrame(self.frame, text="33612A")
        top.pack(fill="x", padx=10, pady=10)
        self.model_var = tk.StringVar(value="(No FGEN)")
        ttk.Label(top, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(top, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")
        for c in range(4):
            top.grid_columnconfigure(c, weight=1)

        # ------- channels side-by-side -------
        chf = ttk.Frame(self.frame)
        chf.pack(fill="both", expand=True, padx=10, pady=(0,10))

        # Per-channel state + UI containers
        self.ch = {
            "1": self._init_channel_state("1"),
            "2": self._init_channel_state("2"),
        }

        self._build_channel_ui(chf, "1", col=0)
        self._build_channel_ui(chf, "2", col=1)

        chf.grid_columnconfigure(0, weight=1)
        chf.grid_columnconfigure(1, weight=1)

    # ------------- per-channel state -------------
    def _init_channel_state(self, ch):
        return {
            "wave_var": tk.StringVar(value="Sine"),
            "param_vars": {},  # key -> StringVar
            "out_var": tk.StringVar(value="Off"),
            "load_mode": tk.StringVar(value="50 Ω"),
            "load_val": tk.StringVar(value="50"),
            "range_mode": tk.StringVar(value="Auto"),
            # UI handles
            "paramsf": None,
            "load_entry": None,
        }

    # ------------- build per-channel UI -------------
    def _build_channel_ui(self, parent, ch: str, col: int):
        outer = ttk.LabelFrame(parent, text=f"Channel {ch}")
        outer.grid(row=0, column=col, padx=6, pady=6, sticky="nsew")

        # Waveform selector
        ttk.Label(outer, text="Waveform:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        wave_cb = ttk.Combobox(outer, textvariable=self.ch[ch]["wave_var"], state="readonly",
                               values=list(self.WF_MAP.keys()), width=12)
        wave_cb.grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        # Parameters frame (dynamic entries)
        paramsf = ttk.LabelFrame(outer, text="Parameters")
        paramsf.grid(row=1, column=0, columnspan=4, padx=6, pady=6, sticky="nsew")
        self.ch[ch]["paramsf"] = paramsf
        self._render_params_for_wave(ch)  # initial

        # Output/Load/Range block
        io = ttk.LabelFrame(outer, text="Output / Load / Range")
        io.grid(row=2, column=0, columnspan=4, padx=6, pady=6, sticky="nsew")

        # Output
        ttk.Label(io, text="Output:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(io, textvariable=self.ch[ch]["out_var"], state="readonly",
                     values=["Off","On"], width=8).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        # Load
        ttk.Label(io, text="Output Load:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        load_cb = ttk.Combobox(io, textvariable=self.ch[ch]["load_mode"], state="readonly",
                               values=["50 Ω","High Z","Specify"], width=10)
        load_cb.grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")

        ttk.Label(io, text="Ω (Specify):").grid(row=1, column=2, padx=6, pady=6, sticky="e")
        load_en = ttk.Entry(io, textvariable=self.ch[ch]["load_val"], width=10)
        load_en.grid(row=1, column=3, padx=(0,12), pady=6, sticky="w")
        self.ch[ch]["load_entry"] = load_en

        def _toggle_load_entry(*_):
            mode = (self.ch[ch]["load_mode"].get() or "50 Ω")
            state = "normal" if mode == "Specify" else "disabled"
            try: load_en.config(state=state)
            except Exception: pass
        load_cb.bind("<<ComboboxSelected>>", _toggle_load_entry)
        io.after(0, _toggle_load_entry)

        # Range
        ttk.Label(io, text="Range:").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(io, textvariable=self.ch[ch]["range_mode"], state="readonly",
                     values=["Auto","Hold"], width=8).grid(row=2, column=1, padx=(0,12), pady=6, sticky="w")

        # Buttons
        btns = ttk.Frame(outer)
        btns.grid(row=3, column=0, columnspan=4, padx=6, pady=6, sticky="e")
        ttk.Button(btns, text=f"Apply Waveform (CH{ch})", command=lambda ch=ch: self.apply_waveform(ch)).pack(side="left", padx=4)
        ttk.Button(btns, text=f"Apply CH{ch} (Output/Load/Range)", command=lambda ch=ch: self.apply_channel_settings(ch)).pack(side="left", padx=4)

        for c in range(4):
            outer.grid_columnconfigure(c, weight=1)
            io.grid_columnconfigure(c, weight=1)

        # Wire: waveform change -> rebuild params
        wave_cb.bind("<<ComboboxSelected>>", lambda *_: self._render_params_for_wave(ch))

    # ------------- dynamic params per channel -------------
    def _clear_params(self, ch: str):
        pf = self.ch[ch]["paramsf"]
        for w in list(pf.winfo_children()):
            try: w.destroy()
            except Exception: pass
        self.ch[ch]["param_vars"].clear()

    def _render_params_for_wave(self, ch: str):
        pf = self.ch[ch]["paramsf"]
        self._clear_params(ch)
        wave = self.ch[ch]["wave_var"].get()
        layout = self.PARAM_LAYOUTS.get(wave, self.PARAM_LAYOUTS["Sine"])

        for row, (label, key) in enumerate(layout):
            ttk.Label(pf, text=label + ":").grid(row=row, column=0, padx=6, pady=6, sticky="e")
            var = tk.StringVar(value="")
            ent = ttk.Entry(pf, textvariable=var, width=18)
            ent.grid(row=row, column=1, padx=(0,12), pady=6, sticky="w")
            # hints (optional)
            hint = {
                "freq":"e.g. 1 kHz", "amp":"e.g. 2 Vpp", "offs":"e.g. 0.1 V", "phase":"e.g. 0",
                "symm":"e.g. 50", "pwidth":"e.g. 10 us", "lead":"e.g. 10 ns", "trail":"e.g. 10 ns",
                "srate":"e.g. 1 MSa/s", "aphase":"e.g. 0", "bw":"e.g. 1 MHz", "brate":"e.g. 1 MHz",
                "etime":"e.g. 10 ns"
            }.get(key, "")
            if hint:
                ttk.Label(pf, text=hint, foreground="#666").grid(row=row, column=2, padx=6, pady=6, sticky="w")
            self.ch[ch]["param_vars"][key] = var

        for c in range(3):
            pf.grid_columnconfigure(c, weight=1)

    # ================= Device state =================
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
            self.set_enabled(False); return
        self.model_var.set(idn)
        self.set_enabled(True)

    # ================= SCPI helpers =================
    def _src(self, ch: str) -> str:
        ch = ch if ch in ("1","2") else "1"
        return f"SOUR{ch}:"

    def _outp(self, ch: str) -> str:
        ch = ch if ch in ("1","2") else "1"
        return f"OUTP{ch}:"

    # ================= Apply operations =================
    def apply_channel_settings(self, ch: str):
        """Apply Output ON/OFF, Output Load, Range(Auto/Hold) for channel ch."""
        try:
            inst = self.get_inst()
            if not inst or not self._is_33612a: return
            outp = self._outp(ch)
            src  = self._src(ch)

            # Output ON/OFF
            val = "ON" if (self.ch[ch]["out_var"].get() or "Off").lower() == "on" else "OFF"
            common.try_sequences(inst, [
                [f"{outp}STAT {val}"],
                [f"{outp}{val}"],
                ["OUTP:STAT {0}".format(val)]
            ])

            # Output Load
            mode = (self.ch[ch]["load_mode"].get() or "50 Ω")
            if mode.startswith("50"):
                inst.write(f"{outp}LOAD 50")
            elif mode.lower().startswith("high"):
                inst.write(f"{outp}LOAD INF")
            else:
                lv = _parse(self.ch[ch]["load_val"].get(), "volt", None)  # number in ohms; unit token ignored
                if lv is None or lv <= 0:
                    messagebox.showwarning("FGEN", f"CH{ch}: Specify a valid load in ohms.")
                else:
                    inst.write(f"{outp}LOAD {lv}")

            # Range Auto/Hold  (Hold => VOLT:RANG:AUTO OFF)
            rmode = (self.ch[ch]["range_mode"].get() or "Auto").lower()
            if rmode == "auto":
                common.try_sequences(inst, [
                    [f"{src}VOLT:RANG:AUTO ON"],
                    [f"{src}VOLT:RANG:AUTO ONCE"]
                ])
            else:
                common.try_sequences(inst, [
                    [f"{src}VOLT:RANG:AUTO OFF"],
                    [f"{src}VOLT:RANG:AUTO 0"]
                ])

            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] CH{ch} -> OUT={val}, LOAD={mode}({self.ch[ch]['load_val'].get()}), RANGE={rmode}")
            self.status.set(f"Channel {ch} settings applied.")
        except Exception as e:
            messagebox.showerror("FGEN Channel Apply failed", str(e))

    def _reapply_range_if_hold(self, ch: str):
        """Because APPLy turns autorange back on, enforce HOLD again if needed."""
        try:
            if (self.ch[ch]["range_mode"].get() or "Auto").lower() == "hold":
                src = self._src(ch)
                common.try_sequences(self.get_inst(), [
                    [f"{src}VOLT:RANG:AUTO OFF"],
                    [f"{src}VOLT:RANG:AUTO 0"]
                ])
        except Exception:
            pass

    def apply_waveform(self, ch: str):
        """Apply waveform + manually-entered parameters to the given channel."""
        try:
            inst = self.get_inst()
            if not inst or not self._is_33612a: return
            src = self._src(ch)
            wf_name = self.ch[ch]["wave_var"].get()
            wf = self.WF_MAP.get(wf_name, "SIN")

            # switch function first
            common.try_sequences(inst, [
                [f"{src}FUNC {wf}"],
                [f"{src}APPL:{wf}"]
            ])

            # params
            pv = self.ch[ch]["param_vars"]
            gv = lambda key, kind, default=None: _parse(pv.get(key, tk.StringVar(value="")).get(), kind, default)

            if wf in ("SIN","SQU","RAMP","TRI","PULS"):
                freq  = gv("freq","freq", None)
                amp   = gv("amp","volt", None)
                offs  = gv("offs","offs", 0.0)
                phase = gv("phase","phase", None)

                # set unit to VPP (interpret amplitude as Vpp)
                try: inst.write(f"{src}VOLT:UNIT VPP")
                except Exception: pass

                # try APPL first if all three given
                if freq is not None and amp is not None and offs is not None:
                    common.try_sequences(inst, [[f"{src}APPL:{wf} {freq},{amp},{offs}"]])

                # granular fallback
                if freq  is not None: inst.write(f"{src}FREQ {freq}")
                if amp   is not None: inst.write(f"{src}VOLT {amp}")
                if offs  is not None: inst.write(f"{src}VOLT:OFFS {offs}")
                if phase is not None:
                    common.try_sequences(inst, [
                        [f"{src}PHAS {phase}"],
                        [f"{src}FUNC:PHAS {phase}"]
                    ])

                if wf == "RAMP":
                    symm = gv("symm","percent", None)
                    if symm is not None:
                        common.try_sequences(inst, [
                            [f"{src}RAMP:SYMM {symm}"],
                            [f"{src}FUNC:RAMP:SYMM {symm}"]
                        ])

                if wf == "PULS":
                    pwidth = gv("pwidth","time", None)
                    lead   = gv("lead","time", None)
                    trail  = gv("trail","time", None)
                    if pwidth is not None:
                        common.try_sequences(inst, [
                            [f"{src}PULS:WIDT {pwidth}"],
                            [f"{src}FUNC:PULS:WIDT {pwidth}"]
                        ])
                    if lead   is not None:
                        common.try_sequences(inst, [
                            [f"{src}PULS:TRAN:LEAD {lead}"],
                            [f"{src}PULS:TRAN:LEADing {lead}"]
                        ])
                    if trail  is not None:
                        common.try_sequences(inst, [
                            [f"{src}PULS:TRAN:TRA {trail}"],
                            [f"{src}PULS:TRAN:TRAiling {trail}"]
                        ])

            elif wf == "ARB":
                srate = gv("srate","srate", None)
                amp   = gv("amp","volt", None)
                offs  = gv("offs","offs", 0.0)
                aphase= gv("aphase","phase", None)
                if srate is not None:
                    common.try_sequences(inst, [
                        [f"{src}ARB:SRAT {srate}"],
                        [f"{src}ARB:SRATe {srate}"]
                    ])
                if aphase is not None:
                    common.try_sequences(inst, [
                        [f"{src}ARB:PHAS {aphase}"],
                        [f"{src}FUNC:ARB:PHAS {aphase}"]
                    ])
                if amp is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "NOIS":
                bw   = gv("bw","band", None)
                amp  = gv("amp","volt", None)
                offs = gv("offs","offs", 0.0)
                if bw  is not None:
                    common.try_sequences(inst, [
                        [f"{src}NOIS:BAND {bw}"],
                        [f"{src}FUNC:NOIS:BAND {bw}"]
                    ])
                if amp is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "PRBS":
                br   = gv("brate","bitrate", None)
                et   = gv("etime","time", None)
                amp  = gv("amp","volt", None)
                offs = gv("offs","offs", 0.0)
                phase= gv("phase","phase", None)
                if br is not None:
                    common.try_sequences(inst, [
                        [f"{src}PRBS:BRAT {br}"],
                        [f"{src}FUNC:PRBS:BRAT {br}"]
                    ])
                if et is not None:
                    common.try_sequences(inst, [
                        [f"{src}PRBS:TRAN {et}"],
                        [f"{src}FUNC:PRBS:TRAN {et}"]
                    ])
                if phase is not None:
                    common.try_sequences(inst, [
                        [f"{src}PHAS {phase}"],
                        [f"{src}FUNC:PHAS {phase}"]
                    ])
                if amp is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "DC":
                offs = gv("offs","offs", 0.0)
                common.try_sequences(inst, [
                    [f"{src}APPL:DC DEF,DEF,{offs}"],
                    [f"{src}FUNC DC", f"{src}VOLT:OFFS {offs}"]
                ])

            # Ensure HOLD range is kept if requested
            self._reapply_range_if_hold(ch)

            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Apply Waveform -> CH={ch}, WF={wf_name}")
            self.status.set(f"Waveform applied to CH{ch}.")
        except Exception as e:
            messagebox.showerror("FGEN Apply failed", str(e))
