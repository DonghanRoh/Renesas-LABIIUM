# scpi_tabs/function_generator_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common
import re

# ---------- simple numeric extractor ----------
def _fnum(s, default=None):
    try:
        return float(common.extract_number(s))
    except Exception:
        return default

class FunctionGeneratorTab:
    """
    Keysight/Agilent 33612A 전용 UI
      - CH1/CH2 각각: Waveform 드롭다운 + 해당 파형의 파라미터를 '숫자'로 입력 (단위 X)
        * 라벨에 단위를 명시: Hz / Vpp / V / deg / % / s / Sa/s
      - CH1/CH2 각각: Output ON/OFF, Output Load(50Ω/High Z/Specify), Range(Auto/Hold)
      - 버튼: 채널별로 단 하나 — "Apply CHx (Waveform + Output/Load/Range)"
    주의: 일부 장비에서 APPL이 autorange를 변경할 수 있어 Range=Hold일 때 다시 OFF 적용.
    """

    # SCPI waveform names
    WF_MAP = {
        "Sine": "SIN", "Square": "SQU", "Ramp": "RAMP", "Pulse": "PULS",
        "Arb": "ARB", "Triangle": "TRI", "Noise": "NOIS", "PRBS": "PRBS", "DC": "DC",
    }

    # Per-waveform parameter layout: (Label with unit, key)
    PARAM_LAYOUTS = {
        "Sine":      [("Frequency (Hz)", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase")],
        "Square":    [("Frequency (Hz)", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase")],
        "Triangle":  [("Frequency (Hz)", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase")],
        "Ramp":      [("Frequency (Hz)", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase"),
                      ("Symmetry (%)", "symm")],
        "Pulse":     [("Frequency (Hz)", "freq"), ("Amplitude (Vpp)", "amp"), ("Offset (V)", "offs"), ("Phase (deg)", "phase"),
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

        # Header
        top = ttk.LabelFrame(self.frame, text="33612A")
        top.pack(fill="x", padx=10, pady=10)
        self.model_var = tk.StringVar(value="(No FGEN)")
        ttk.Label(top, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(top, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")
        for c in range(4): top.grid_columnconfigure(c, weight=1)

        # Two channel panes
        chf = ttk.Frame(self.frame)
        chf.pack(fill="both", expand=True, padx=10, pady=(0,10))

        self.ch = {"1": self._init_channel_state("1"), "2": self._init_channel_state("2")}
        self._build_channel_ui(chf, "1", col=0)
        self._build_channel_ui(chf, "2", col=1)
        chf.grid_columnconfigure(0, weight=1)
        chf.grid_columnconfigure(1, weight=1)

    # ---------- per-channel state ----------
    def _init_channel_state(self, ch):
        return {
            "wave_var": tk.StringVar(value="Sine"),
            "param_vars": {},  # key -> StringVar (numeric text only)
            "out_var": tk.StringVar(value="Off"),
            "load_mode": tk.StringVar(value="50 Ω"),  # 50 Ω | High Z | Specify
            "load_val": tk.StringVar(value="50"),     # ohms (number only)
            "range_mode": tk.StringVar(value="Auto"), # Auto | Hold
            "paramsf": None,
            "load_entry": None,
        }

    # ---------- UI builders ----------
    def _build_channel_ui(self, parent, ch: str, col: int):
        outer = ttk.LabelFrame(parent, text=f"Channel {ch}")
        outer.grid(row=0, column=col, padx=6, pady=6, sticky="nsew")

        # Waveform
        ttk.Label(outer, text="Waveform:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        wave_cb = ttk.Combobox(outer, textvariable=self.ch[ch]["wave_var"], state="readonly",
                               values=list(self.WF_MAP.keys()), width=12)
        wave_cb.grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        # Parameters (dynamic, numeric only)
        paramsf = ttk.LabelFrame(outer, text="Waveform Parameters (numbers only)")
        paramsf.grid(row=1, column=0, columnspan=4, padx=6, pady=6, sticky="nsew")
        self.ch[ch]["paramsf"] = paramsf
        self._render_params_for_wave(ch)

        # Output / Load / Range
        io = ttk.LabelFrame(outer, text="Output / Load / Range")
        io.grid(row=2, column=0, columnspan=4, padx=6, pady=6, sticky="nsew")

        ttk.Label(io, text="Output:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(io, textvariable=self.ch[ch]["out_var"], state="readonly",
                     values=["Off","On"], width=8).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

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
            try: load_en.config(state=("normal" if mode == "Specify" else "disabled"))
            except Exception: pass
        load_cb.bind("<<ComboboxSelected>>", _toggle_load_entry)
        io.after(0, _toggle_load_entry)

        ttk.Label(io, text="Range:").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(io, textvariable=self.ch[ch]["range_mode"], state="readonly",
                     values=["Auto","Hold"], width=8).grid(row=2, column=1, padx=(0,12), pady=6, sticky="w")

        # Single combined button
        btns = ttk.Frame(outer)
        btns.grid(row=3, column=0, columnspan=4, padx=6, pady=6, sticky="e")
        ttk.Button(btns, text=f"Apply CH{ch} (Waveform + Output/Load/Range)",
                   command=lambda ch=ch: self.apply_all(ch)).pack(side="left", padx=4)

        for c in range(4):
            outer.grid_columnconfigure(c, weight=1)
            io.grid_columnconfigure(c, weight=1)

        # Re-render params on waveform change
        wave_cb.bind("<<ComboboxSelected>>", lambda *_: self._render_params_for_wave(ch))

    # ---------- dynamic params ----------
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
            self.ch[ch]["param_vars"][key] = var

        for c in range(2):
            pf.grid_columnconfigure(c, weight=1)

    # ---------- device state ----------
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

    # ---------- SCPI helpers ----------
    def _src(self, ch: str) -> str:
        ch = ch if ch in ("1","2") else "1"
        return f"SOUR{ch}:"

    def _outp(self, ch: str) -> str:
        ch = ch if ch in ("1","2") else "1"
        return f"OUTP{ch}:"

    # ---------- combined apply ----------
    def apply_all(self, ch: str):
        """
        Apply BOTH:
          1) Waveform + its parameters (numbers only)
          2) Output ON/OFF, Output Load, Range(Auto/Hold)
        for the given channel.
        """
        try:
            inst = self.get_inst()
            if not inst or not self._is_33612a:
                return

            src  = self._src(ch)
            outp = self._outp(ch)
            wf_name = self.ch[ch]["wave_var"].get()
            wf = self.WF_MAP.get(wf_name, "SIN")

            # ---- 1) Waveform + parameters (use granular commands; avoid APPL if possible) ----
            # set function first
            common.try_sequences(inst, [[f"{src}FUNC {wf}"], [f"{src}APPL:{wf}"]])

            pv = self.ch[ch]["param_vars"]
            g = lambda k, d=None: _fnum(pv.get(k, tk.StringVar(value="")).get(), d)

            if wf in ("SIN","SQU","RAMP","TRI","PULS"):
                freq  = g("freq", None)
                amp   = g("amp",  None)
                offs  = g("offs", 0.0)
                phase = g("phase", None)

                # Interpret amplitude as Vpp
                try: inst.write(f"{src}VOLT:UNIT VPP")
                except Exception: pass

                # Prefer granular to avoid autorange side-effects
                if freq  is not None: inst.write(f"{src}FREQ {freq}")
                if amp   is not None: inst.write(f"{src}VOLT {amp}")
                if offs  is not None: inst.write(f"{src}VOLT:OFFS {offs}")
                if phase is not None:
                    common.try_sequences(inst, [[f"{src}PHAS {phase}"], [f"{src}FUNC:PHAS {phase}"]])

                if wf == "RAMP":
                    symm = g("symm", None)
                    if symm is not None:
                        common.try_sequences(inst, [[f"{src}RAMP:SYMM {symm}"], [f"{src}FUNC:RAMP:SYMM {symm}"]])

                if wf == "PULS":
                    pwidth = g("pwidth", None)
                    lead   = g("lead",   None)
                    trail  = g("trail",  None)
                    if pwidth is not None:
                        common.try_sequences(inst, [[f"{src}PULS:WIDT {pwidth}"], [f"{src}FUNC:PULS:WIDT {pwidth}"]])
                    if lead   is not None:
                        common.try_sequences(inst, [[f"{src}PULS:TRAN:LEAD {lead}"], [f"{src}PULS:TRAN:LEADing {lead}"]])
                    if trail  is not None:
                        common.try_sequences(inst, [[f"{src}PULS:TRAN:TRA {trail}"], [f"{src}PULS:TRAN:TRAiling {trail}"]])

            elif wf == "ARB":
                srate = g("srate", None)
                amp   = g("amp",   None)
                offs  = g("offs",  0.0)
                aphase= g("aphase",None)
                if srate is not None:
                    common.try_sequences(inst, [[f"{src}ARB:SRAT {srate}"], [f"{src}ARB:SRATe {srate}"]])
                if aphase is not None:
                    common.try_sequences(inst, [[f"{src}ARB:PHAS {aphase}"], [f"{src}FUNC:ARB:PHAS {aphase}"]])
                if amp  is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "NOIS":
                bw   = g("bw",   None)
                amp  = g("amp",  None)
                offs = g("offs", 0.0)
                if bw   is not None:
                    common.try_sequences(inst, [[f"{src}NOIS:BAND {bw}"], [f"{src}FUNC:NOIS:BAND {bw}"]])
                if amp  is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "PRBS":
                br    = g("brate", None)
                etime = g("etime", None)
                amp   = g("amp",   None)
                offs  = g("offs",  0.0)
                phase = g("phase", None)
                if br    is not None:
                    common.try_sequences(inst, [[f"{src}PRBS:BRAT {br}"], [f"{src}FUNC:PRBS:BRAT {br}"]])
                if etime is not None:
                    common.try_sequences(inst, [[f"{src}PRBS:TRAN {etime}"], [f"{src}FUNC:PRBS:TRAN {etime}"]])
                if phase is not None:
                    common.try_sequences(inst, [[f"{src}PHAS {phase}"], [f"{src}FUNC:PHAS {phase}"]])
                if amp   is not None: inst.write(f"{src}VOLT {amp}")
                if offs  is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "DC":
                offs = g("offs", 0.0)
                # Use granular first; APPL as fallback
                wrote = False
                try:
                    inst.write(f"{src}FUNC DC"); inst.write(f"{src}VOLT:OFFS {offs}"); wrote = True
                except Exception:
                    pass
                if not wrote:
                    common.try_sequences(inst, [[f"{src}APPL:DC DEF,DEF,{offs}"]])

            # ---- 2) Output / Load / Range ----
            # Output
            out_val = "ON" if (self.ch[ch]["out_var"].get() or "Off").lower() == "on" else "OFF"
            common.try_sequences(inst, [[f"{outp}STAT {out_val}"], [f"{outp}{out_val}"], ["OUTP:STAT {0}".format(out_val)]])

            # Load
            mode = (self.ch[ch]["load_mode"].get() or "50 Ω")
            if mode.startswith("50"):
                inst.write(f"{outp}LOAD 50")
            elif mode.lower().startswith("high"):
                inst.write(f"{outp}LOAD INF")
            else:
                lv = _fnum(self.ch[ch]["load_val"].get(), None)
                if lv is None or lv <= 0:
                    messagebox.showwarning("FGEN", f"CH{ch}: Specify a valid load (ohms, number only).")
                else:
                    inst.write(f"{outp}LOAD {lv}")

            # Range
            rmode = (self.ch[ch]["range_mode"].get() or "Auto").lower()
            if rmode == "auto":
                common.try_sequences(inst, [[f"{src}VOLT:RANG:AUTO ON"], [f"{src}VOLT:RANG:AUTO ONCE"]])
            else:
                common.try_sequences(inst, [[f"{src}VOLT:RANG:AUTO OFF"], [f"{src}VOLT:RANG:AUTO 0"]])

            # If APPL re-enabled autorange on this model, enforce HOLD again
            if rmode == "hold":
                try:
                    common.try_sequences(inst, [[f"{src}VOLT:RANG:AUTO OFF"], [f"{src}VOLT:RANG:AUTO 0"]])
                except Exception:
                    pass

            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] CH{ch} APPLY -> WF={wf_name}, OUT={out_val}, LOAD={mode}({self.ch[ch]['load_val'].get()}), RANGE={rmode}")
            self.status.set(f"Applied to CH{ch}.")
        except Exception as e:
            messagebox.showerror("FGEN Apply failed", str(e))
