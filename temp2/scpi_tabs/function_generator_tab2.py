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
    s = s.replace("°", " deg").replace("Sa/s", " SPS").replace("Vpp", " Vpp").replace("Vrms"," Vrms").replace("dBm"," dBm")
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
    v, u = _num_si(s)
    if v is None:
        return default
    u = u.lower()
    if kind in ("freq","bitrate","band"):
        return v
    if kind == "srate":  # Sa/s
        return v
    if kind in ("volt","offs"):
        # we treat numbers as volts regardless of 'v','vpp' tokens; caller should know context
        return v
    if kind == "phase":
        return v
    if kind == "time":
        return v
    if kind == "percent":
        return v
    return v

def _fnum(s, default=0.0):
    try:
        return float(common.extract_number(s))
    except Exception:
        return float(default)

class FunctionGeneratorTab:
    """
    Keysight/Agilent 33612A 전용 간소 UI
      - 파형: 드롭다운
      - 파라미터: 모두 수동 입력(Entry), 파형에 따라 필요한 필드만 표시
      - 채널1/채널2 각각: Output ON/OFF, Output Load(50Ω/High Z/Specify), Range(Auto/Hold)
    주의: APPLy 명령이 Autorange를 다시 켤 수 있으므로, Range=Hold일 때는 파형 적용 후 Autorange OFF 재적용.
    """

    WF_MAP = {
        "Sine": "SIN", "Square": "SQU", "Ramp": "RAMP", "Pulse": "PULS",
        "Arb": "ARB", "Triangle": "TRI", "Noise": "NOIS", "PRBS": "PRBS", "DC": "DC",
    }

    # ---- UI state ----
    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Function Generator")

        self._is_33612a = False

        # top-level controls for waveform setup (target channel to apply)
        self.model_var = tk.StringVar(value="(No FGEN)")
        self.target_ch_var = tk.StringVar(value="1")
        self.wave_var = tk.StringVar(value="Sine")

        # dynamic param vars (created per waveform)
        self._param_vars = {}  # name -> tk.StringVar

        # per-channel output/load/range state
        self.ch = {
            "1": {
                "out_var": tk.StringVar(value="Off"),
                "load_mode": tk.StringVar(value="50 Ω"),   # "50 Ω" | "High Z" | "Specify"
                "load_val": tk.StringVar(value="50"),
                "range_mode": tk.StringVar(value="Auto"),  # "Auto" | "Hold"
            },
            "2": {
                "out_var": tk.StringVar(value="Off"),
                "load_mode": tk.StringVar(value="50 Ω"),
                "load_val": tk.StringVar(value="50"),
                "range_mode": tk.StringVar(value="Auto"),
            },
        }

        self._build_ui(self.frame)
        self._wire_events()

    # ================= UI =================
    def _build_ui(self, parent):
        # ---- Waveform & Parameters ----
        top = ttk.LabelFrame(parent, text="33612A Waveform Setup")
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(top, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(top, text="Channel:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        ttk.Combobox(top, textvariable=self.target_ch_var, state="readonly", values=["1","2"], width=6)\
            .grid(row=0, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Label(top, text="Waveform:").grid(row=1, column=0, padx=6, pady=8, sticky="e")
        self.wave_combo = ttk.Combobox(top, textvariable=self.wave_var, state="readonly",
                                       values=list(self.WF_MAP.keys()), width=12)
        self.wave_combo.grid(row=1, column=1, padx=(0,12), pady=8, sticky="w")

        # dynamic parameter frame (entries only)
        self.paramsf = ttk.LabelFrame(parent, text="Parameters (manual input)")
        self.paramsf.pack(fill="x", padx=10, pady=(0,10))

        # parameter rows will be created by _render_params_for_wave
        self._render_params_for_wave("Sine")

        # apply waveform button
        btns = ttk.Frame(parent)
        btns.pack(fill="x", padx=10, pady=(0,10))
        ttk.Button(btns, text="Apply Waveform To Channel", command=self.apply_waveform).pack(side="left", padx=6)

        # ---- Per-Channel Output/Load/Range ----
        chf = ttk.LabelFrame(parent, text="Channel Outputs")
        chf.pack(fill="x", padx=10, pady=(0,10))

        self._make_channel_block(chf, "1", col=0)
        self._make_channel_block(chf, "2", col=1)

        for c in range(2):
            chf.grid_columnconfigure(c, weight=1)

    def _make_channel_block(self, parent, ch, col=0):
        f = ttk.LabelFrame(parent, text=f"Channel {ch}")
        f.grid(row=0, column=col, padx=6, pady=6, sticky="nsew")

        # Output
        ttk.Label(f, text="Output:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(f, textvariable=self.ch[ch]["out_var"], state="readonly",
                     values=["Off","On"], width=8).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        # Load
        ttk.Label(f, text="Output Load:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        load_cb = ttk.Combobox(f, textvariable=self.ch[ch]["load_mode"], state="readonly",
                               values=["50 Ω","High Z","Specify"], width=10)
        load_cb.grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")

        ttk.Label(f, text="Ω (Specify):").grid(row=1, column=2, padx=6, pady=6, sticky="e")
        load_en = ttk.Entry(f, textvariable=self.ch[ch]["load_val"], width=10)
        load_en.grid(row=1, column=3, padx=(0,12), pady=6, sticky="w")

        def _toggle_load_entry(*_):
            mode = (self.ch[ch]["load_mode"].get() or "50 Ω")
            state = "normal" if mode == "Specify" else "disabled"
            try: load_en.config(state=state)
            except Exception: pass
        load_cb.bind("<<ComboboxSelected>>", _toggle_load_entry)
        f.after(0, _toggle_load_entry)  # init

        # Range
        ttk.Label(f, text="Range:").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(f, textvariable=self.ch[ch]["range_mode"], state="readonly",
                     values=["Auto","Hold"], width=8).grid(row=2, column=1, padx=(0,12), pady=6, sticky="w")

        # Apply button
        ttk.Button(f, text=f"Apply CH{ch}", command=lambda ch=ch: self.apply_channel_settings(ch))\
            .grid(row=3, column=0, columnspan=4, padx=6, pady=8, sticky="e")

        for c in range(4):
            f.grid_columnconfigure(c, weight=1)

    def _wire_events(self):
        self.wave_combo.bind("<<ComboboxSelected>>", lambda *_: self._render_params_for_wave(self.wave_var.get()))

    def _clear_params(self):
        for w in list(self.paramsf.winfo_children()):
            try: w.destroy()
            except Exception: pass
        self._param_vars.clear()

    def _render_params_for_wave(self, wave_name: str):
        """Build parameter entries depending on waveform; all are free-text Entries."""
        self._clear_params()
        w = wave_name
        row = 0

        def add_param(label, key, hint=""):
            ttk.Label(self.paramsf, text=label + ":").grid(row=row, column=0, padx=6, pady=6, sticky="e")
            var = tk.StringVar(value="")
            e = ttk.Entry(self.paramsf, textvariable=var, width=18)
            e.grid(row=row, column=1, padx=(0,12), pady=6, sticky="w")
            if hint:
                ttk.Label(self.paramsf, text=hint, foreground="#666").grid(row=row, column=2, padx=6, pady=6, sticky="w")
            self._param_vars[key] = var

        # Common sets per waveform
        if w in ("Sine","Square","Ramp","Triangle"):
            add_param("Frequency", "freq", "e.g. 1 kHz")
            add_param("Amplitude (Vpp)", "amp", "e.g. 2 Vpp")
            add_param("Offset (V)", "offs", "e.g. 0.1 V")
            add_param("Phase (deg)", "phase", "e.g. 0")
            if w == "Ramp":
                add_param("Symmetry (%)", "symm", "e.g. 50")
        elif w == "Pulse":
            add_param("Frequency", "freq", "e.g. 10 kHz")
            add_param("Amplitude (Vpp)", "amp", "e.g. 1 Vpp")
            add_param("Offset (V)", "offs", "e.g. 0 V")
            add_param("Phase (deg)", "phase", "e.g. 0")
            add_param("Pulse Width (s)", "pwidth", "e.g. 10 us")
            add_param("Lead Edge (s)", "lead", "e.g. 10 ns")
            add_param("Trail Edge (s)", "trail", "e.g. 10 ns")
        elif w == "Arb":
            add_param("Sample Rate (Sa/s)", "srate", "e.g. 1 MSa/s")
            add_param("Amplitude (Vpp)", "amp", "e.g. 1 Vpp")
            add_param("Offset (V)", "offs", "e.g. 0 V")
            add_param("Arb Phase (deg)", "aphase", "e.g. 0")
        elif w == "Noise":
            add_param("Bandwidth (Hz)", "bw", "e.g. 1 MHz")
            add_param("Amplitude (Vpp)", "amp", "e.g. 0.5 Vpp")
            add_param("Offset (V)", "offs", "e.g. 0 V")
        elif w == "PRBS":
            add_param("Bit Rate (Hz)", "brate", "e.g. 1 MHz")
            add_param("Amplitude (Vpp)", "amp", "e.g. 1 Vpp")
            add_param("Offset (V)", "offs", "e.g. 0 V")
            add_param("Edge Time (s)", "etime", "e.g. 10 ns")
            add_param("Phase (deg)", "phase", "e.g. 0")
        elif w == "DC":
            add_param("Offset (V)", "offs", "e.g. -2.5 V")
        else:
            # default
            add_param("Frequency", "freq"); add_param("Amplitude (Vpp)", "amp"); add_param("Offset (V)", "offs"); add_param("Phase (deg)", "phase")

        for c in range(3):
            self.paramsf.grid_columnconfigure(c, weight=1)

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
            common.try_sequences(inst, [[f"{outp}STAT {val}"], [f"{outp}{val}"], ["OUTP:STAT {0}".format(val)]])

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
                common.try_sequences(inst, [[f"{src}VOLT:RANG:AUTO ON"], [f"{src}VOLT:RANG:AUTO ONCE"]])
            else:
                common.try_sequences(inst, [[f"{src}VOLT:RANG:AUTO OFF"], [f"{src}VOLT:RANG:AUTO 0"]])

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
                common.try_sequences(self.get_inst(), [[f"{src}VOLT:RANG:AUTO OFF"], [f"{src}VOLT:RANG:AUTO 0"]])
        except Exception:
            pass

    def apply_waveform(self):
        """Apply waveform + manually-entered parameters to the selected channel."""
        try:
            inst = self.get_inst()
            if not inst or not self._is_33612a: return
            ch = (self.target_ch_var.get() or "1").strip()
            src = self._src(ch)
            wf_name = self.wave_var.get()
            wf = self.WF_MAP.get(wf_name, "SIN")

            # switch function first
            common.try_sequences(inst, [[f"{src}FUNC {wf}"], [f"{src}APPL:{wf}"]])

            # read params (text -> base units)
            gv = lambda key, kind, default=None: _parse(self._param_vars.get(key, tk.StringVar(value="")).get(), kind, default)

            if wf in ("SIN","SQU","RAMP","TRI","PULS"):
                freq  = gv("freq","freq", None)
                amp   = gv("amp","volt", None)
                offs  = gv("offs","offs", 0.0)
                phase = gv("phase","phase", None)

                # set unit to VPP (we interpret amplitude as Vpp)
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
                    common.try_sequences(inst, [[f"{src}PHAS {phase}"], [f"{src}FUNC:PHAS {phase}"]])

                if wf == "RAMP":
                    symm = gv("symm","percent", None)
                    if symm is not None:
                        common.try_sequences(inst, [[f"{src}RAMP:SYMM {symm}"], [f"{src}FUNC:RAMP:SYMM {symm}"]])

                if wf == "PULS":
                    pwidth = gv("pwidth","time", None)
                    lead   = gv("lead","time", None)
                    trail  = gv("trail","time", None)
                    if pwidth is not None:
                        common.try_sequences(inst, [[f"{src}PULS:WIDT {pwidth}"], [f"{src}FUNC:PULS:WIDT {pwidth}"]])
                    if lead   is not None:
                        common.try_sequences(inst, [[f"{src}PULS:TRAN:LEAD {lead}"], [f"{src}PULS:TRAN:LEADing {lead}"]])
                    if trail  is not None:
                        common.try_sequences(inst, [[f"{src}PULS:TRAN:TRA {trail}"], [f"{src}PULS:TRAN:TRAiling {trail}"]])

            elif wf == "ARB":
                srate = gv("srate","srate", None)
                amp   = gv("amp","volt", None)
                offs  = gv("offs","offs", 0.0)
                aphase= gv("aphase","phase", None)
                if srate is not None:
                    common.try_sequences(inst, [[f"{src}ARB:SRAT {srate}"], [f"{src}ARB:SRATe {srate}"]])
                if aphase is not None:
                    common.try_sequences(inst, [[f"{src}ARB:PHAS {aphase}"], [f"{src}FUNC:ARB:PHAS {aphase}"]])
                if amp is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "NOIS":
                bw   = gv("bw","band", None)
                amp  = gv("amp","volt", None)
                offs = gv("offs","offs", 0.0)
                if bw  is not None:
                    common.try_sequences(inst, [[f"{src}NOIS:BAND {bw}"], [f"{src}FUNC:NOIS:BAND {bw}"]])
                if amp is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "PRBS":
                br   = gv("brate","bitrate", None)
                et   = gv("etime","time", None)
                amp  = gv("amp","volt", None)
                offs = gv("offs","offs", 0.0)
                phase= gv("phase","phase", None)
                if br is not None:
                    common.try_sequences(inst, [[f"{src}PRBS:BRAT {br}"], [f"{src}FUNC:PRBS:BRAT {br}"]])
                if et is not None:
                    common.try_sequences(inst, [[f"{src}PRBS:TRAN {et}"], [f"{src}FUNC:PRBS:TRAN {et}"]])
                if phase is not None:
                    common.try_sequences(inst, [[f"{src}PHAS {phase}"], [f"{src}FUNC:PHAS {phase}"]])
                if amp is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "DC":
                offs = gv("offs","offs", 0.0)
                common.try_sequences(inst, [[f"{src}APPL:DC DEF,DEF,{offs}"], [f"{src}FUNC DC", f"{src}VOLT:OFFS {offs}"]])

            # Ensure HOLD range is kept if user requested it (APPL may re-enable autorange)
            self._reapply_range_if_hold(ch)

            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Apply Waveform -> CH={ch}, WF={wf_name}")
            self.status.set("Waveform applied.")
        except Exception as e:
            messagebox.showerror("FGEN Apply failed", str(e))
