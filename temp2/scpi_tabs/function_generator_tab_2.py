# scpi_tabs/function_generator_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

# ---------- simple numeric extractor ----------
def _fnum(s, default=None):
    try:
        return float(common.extract_number(s))
    except Exception:
        return default

class FunctionGeneratorTab:
    """
    Function Generator UI for Keysight/Agilent 33612A (2-ch) and 33250A (1-ch).
      - Per channel:
          * Waveform dropdown
          * Waveform parameters (numeric only; units shown in labels)
          * Output ON/OFF
          * Output Load (50Ω / High Z / Specify-Ω)
          * Range (Auto / Hold)
          * ONE combined button: "Apply CHx (Waveform + Output/Load/Range)"
      - 33250A shows only CH1. 33612A shows CH1+CH2.
      - Amplitude interpreted as Vpp (VOLT:UNIT VPP)
      - If APPL/commands re-enable autorange, we force HOLD back when requested.
    """

    # SCPI waveform names
    WF_MAP = {
        "Sine": "SIN", "Square": "SQU", "Ramp": "RAMP", "Pulse": "PULS",
        "Arb": "ARB", "Triangle": "TRI", "Noise": "NOIS", "PRBS": "PRBS", "DC": "DC",
    }

    # Base layouts (will be adapted per device)
    PARAM_LAYOUTS_BASE = {
        "Sine":      [("Frequency (Hz)", "freq"),
                      ("Amplitude (Vpp)", "amp"),
                      ("Offset (V)", "offs"),
                      ("Phase (deg)", "phase")],
        "Square":    [("Frequency (Hz)", "freq"),
                      ("Amplitude (Vpp)", "amp"),
                      ("Offset (V)", "offs"),
                      ("Duty Cycle (%)", "duty")],  # duty for SQU
        "Triangle":  [("Frequency (Hz)", "freq"),
                      ("Amplitude (Vpp)", "amp"),
                      ("Offset (V)", "offs"),
                      ("Phase (deg)", "phase")],
        "Ramp":      [("Frequency (Hz)", "freq"),
                      ("Amplitude (Vpp)", "amp"),
                      ("Offset (V)", "offs"),
                      ("Symmetry (%)", "symm")],
        "Pulse":     [("Frequency (Hz)", "freq"),
                      ("Amplitude (Vpp)", "amp"),
                      ("Offset (V)", "offs"),
                      ("Pulse Width (s)", "pwidth"),
                      ("Edge Time (s)", "etime")],  # 33612A also supports separate lead/trail; etime covers 33250A
        # ARB differs by device (srate for 33612A, freq for 33250A) — set at render time
        "Arb_33612A": [("Sample Rate (Sa/s)", "srate"),
                       ("Amplitude (Vpp)", "amp"),
                       ("Offset (V)", "offs"),
                       ("Arb Phase (deg)", "aphase")],
        "Arb_33250A": [("Frequency (Hz)", "freq"),
                       ("Amplitude (Vpp)", "amp"),
                       ("Offset (V)", "offs")],
        # Noise differs by device (bandwidth on 33612A; plain on 33250A)
        "Noise_33612A": [("Bandwidth (Hz)", "bw"),
                         ("Amplitude (Vpp)", "amp"),
                         ("Offset (V)", "offs")],
        "Noise_33250A": [("Amplitude (Vpp)", "amp"),
                         ("Offset (V)", "offs")],
        "PRBS":      [("Bit Rate (Hz)", "brate"),
                      ("Amplitude (Vpp)", "amp"),
                      ("Offset (V)", "offs"),
                      ("Edge Time (s)", "etime"),
                      ("Phase (deg)", "phase")],
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

        # detection flags
        self._is_33612a = False
        self._is_33250a = False

        # Header
        hdr = ttk.LabelFrame(self.frame, text="Function Generator")
        hdr.pack(fill="x", padx=10, pady=10)
        self.model_var = tk.StringVar(value="(No FGEN)")
        ttk.Label(hdr, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(hdr, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")
        for c in range(4): hdr.grid_columnconfigure(c, weight=1)

        # Channels container
        self.ch_container = ttk.Frame(self.frame)
        self.ch_container.pack(fill="both", expand=True, padx=10, pady=(0,10))

        # Build both channel panes; hide CH2 later if 33250A
        self.ch = {"1": self._init_channel_state("1"), "2": self._init_channel_state("2")}
        self.outer_frames = {}
        self._build_channel_ui(self.ch_container, "1", col=0)
        self._build_channel_ui(self.ch_container, "2", col=1)
        self.ch_container.grid_columnconfigure(0, weight=1)
        self.ch_container.grid_columnconfigure(1, weight=1)

    # ---------- per-channel state ----------
    def _init_channel_state(self, ch):
        return {
            "wave_var": tk.StringVar(value="Sine"),
            "param_vars": {},  # key -> StringVar (numeric only)
            "out_var": tk.StringVar(value="Off"),
            "load_mode": tk.StringVar(value="50 Ω"),  # 50 Ω | High Z | Specify
            "load_val": tk.StringVar(value="50"),     # ohms
            "range_mode": tk.StringVar(value="Auto"), # Auto | Hold
            # UI refs
            "paramsf": None,
            "load_entry": None,
        }

    # ---------- UI builders ----------
    def _build_channel_ui(self, parent, ch: str, col: int):
        outer = ttk.LabelFrame(parent, text=f"Channel {ch}")
        outer.grid(row=0, column=col, padx=6, pady=6, sticky="nsew")
        self.outer_frames[ch] = outer

        # Waveform
        ttk.Label(outer, text="Waveform:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        wave_cb = ttk.Combobox(outer, textvariable=self.ch[ch]["wave_var"], state="readonly",
                               values=list(self.WF_MAP.keys()), width=12)
        wave_cb.grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        # Parameters (dynamic)
        paramsf = ttk.LabelFrame(outer, text="Waveform Parameters (numbers only)")
        paramsf.grid(row=1, column=0, columnspan=4, padx=6, pady=6, sticky="nsew")
        self.ch[ch]["paramsf"] = paramsf
        self._render_params_for_wave(ch)  # initial

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

        # Combined apply button
        btns = ttk.Frame(outer)
        btns.grid(row=3, column=0, columnspan=4, padx=6, pady=6, sticky="e")
        ttk.Button(btns, text=f"Apply CH{ch} (Waveform + Output/Load/Range)",
                   command=lambda ch=ch: self.apply_all(ch)).pack(side="left", padx=4)

        for c in range(4):
            outer.grid_columnconfigure(c, weight=1)
            io.grid_columnconfigure(c, weight=1)

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

        # choose layout per device for Arb/Noise
        if wave == "Arb":
            layout = (self.PARAM_LAYOUTS_BASE["Arb_33612A"] if self._is_33612a
                      else self.PARAM_LAYOUTS_BASE["Arb_33250A"])
        elif wave == "Noise":
            layout = (self.PARAM_LAYOUTS_BASE["Noise_33612A"] if self._is_33612a
                      else self.PARAM_LAYOUTS_BASE["Noise_33250A"])
        else:
            layout = self.PARAM_LAYOUTS_BASE.get(wave, self.PARAM_LAYOUTS_BASE["Sine"])

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
        self._is_33250a = ("33250A" in up)

        if not inst or not idn or not (self._is_33612a or self._is_33250a):
            self.model_var.set("(No FGEN)")
            self.set_enabled(False)
            return

        self.model_var.set(idn)
        self.set_enabled(True)

        # Show/Hide channel panes
        if self._is_33250a:
            try: self.outer_frames["2"].grid_remove()
            except Exception: pass
        else:
            try: self.outer_frames["2"].grid()
            except Exception: pass

        # Re-render parameter layouts to reflect device-specific forms
        self._render_params_for_wave("1")
        if self._is_33612a:
            self._render_params_for_wave("2")

    # ---------- SCPI helpers ----------
    def _src(self, ch: str) -> str:
        if self._is_33612a:
            ch = ch if ch in ("1","2") else "1"
            return f"SOUR{ch}:"
        # 33250A: single channel, no numeric suffix needed; also "SOUR:" prefix can be omitted
        return ""

    def _outp(self, ch: str) -> str:
        if self._is_33612a:
            ch = ch if ch in ("1","2") else "1"
            return f"OUTP{ch}:"
        return "OUTP:"

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
            if not inst:
                return

            src  = self._src(ch)
            outp = self._outp(ch)
            wf_name = self.ch[ch]["wave_var"].get()
            wf = self.WF_MAP.get(wf_name, "SIN")

            # ---- 1) Waveform + parameters ----
            # Set function first (prefer FUNC; APPL as alternative)
            common.try_sequences(inst, [[f"{src}FUNC {wf}"], [f"{src}APPL:{wf}"]])

            pv = self.ch[ch]["param_vars"]
            g = lambda k, d=None: _fnum(pv.get(k, tk.StringVar(value="")).get(), d)

            # amplitude unit = VPP
            try: inst.write(f"{src}VOLT:UNIT VPP")
            except Exception: pass

            if wf in ("SIN","TRI","RAMP"):
                freq  = g("freq", None)
                amp   = g("amp",  None)
                offs  = g("offs", 0.0)
                phase = g("phase", None)
                # Prefer granular to avoid side-effects
                if freq  is not None: inst.write(f"{src}FREQ {freq}")
                if amp   is not None: inst.write(f"{src}VOLT {amp}")
                if offs  is not None: inst.write(f"{src}VOLT:OFFS {offs}")
                if phase is not None:
                    common.try_sequences(inst, [[f"{src}PHAS {phase}"], [f"{src}FUNC:PHAS {phase}"]])
                if wf == "RAMP":
                    symm = g("symm", None)
                    if symm is not None:
                        common.try_sequences(inst, [[f"{src}RAMP:SYMM {symm}"], [f"{src}FUNC:RAMP:SYMM {symm}"]])

            elif wf == "SQU":
                freq = g("freq", None)
                amp  = g("amp",  None)
                offs = g("offs", 0.0)
                duty = g("duty", None)
                if freq is not None: inst.write(f"{src}FREQ {freq}")
                if amp  is not None: inst.write(f"{src}VOLT {amp}")
                if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")
                if duty is not None:
                    common.try_sequences(inst, [[f"{src}FUNC:SQU:DCYC {duty}"], [f"{src}PULS:DCYC {duty}"]])

            elif wf == "PULS":
                freq   = g("freq", None)
                amp    = g("amp",  None)
                offs   = g("offs", 0.0)
                pwidth = g("pwidth", None)
                etime  = g("etime",  None)  # edge time (single)
                if freq   is not None: inst.write(f"{src}FREQ {freq}")
                if amp    is not None: inst.write(f"{src}VOLT {amp}")
                if offs   is not None: inst.write(f"{src}VOLT:OFFS {offs}")
                if pwidth is not None:
                    common.try_sequences(inst, [[f"{src}PULS:WIDT {pwidth}"], [f"{src}FUNC:PULS:WIDT {pwidth}"]])
                if etime  is not None:
                    # Single edge-time (works on 33250A). 33612A also accepts LEAD/TRA individually.
                    common.try_sequences(inst, [[f"{src}PULS:TRAN {etime}"],
                                                [f"{src}PULS:TRAN:LEAD {etime}"]])

            elif wf == "ARB":
                if self._is_33612a:
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
                else:
                    # 33250A uses frequency for ARB
                    freq = g("freq", None)
                    amp  = g("amp",  None)
                    offs = g("offs", 0.0)
                    if freq is not None: inst.write(f"{src}FREQ {freq}")
                    if amp  is not None: inst.write(f"{src}VOLT {amp}")
                    if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")

            elif wf == "NOIS":
                if self._is_33612a:
                    bw   = g("bw",   None)
                    amp  = g("amp",  None)
                    offs = g("offs", 0.0)
                    if bw   is not None:
                        common.try_sequences(inst, [[f"{src}NOIS:BAND {bw}"], [f"{src}FUNC:NOIS:BAND {bw}"]])
                    if amp  is not None: inst.write(f"{src}VOLT {amp}")
                    if offs is not None: inst.write(f"{src}VOLT:OFFS {offs}")
                else:
                    amp  = g("amp",  None)
                    offs = g("offs", 0.0)
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
                # Prefer granular; APPL fallback
                wrote = False
                try:
                    inst.write(f"{src}FUNC DC"); inst.write(f"{src}VOLT:OFFS {offs}"); wrote = True
                except Exception:
                    pass
                if not wrote:
                    common.try_sequences(inst, [[f"{src}APPL:DC DEF,DEF,{offs}"]])

            # ---- 2) Output / Load / Range ----
            out_val = "ON" if (self.ch[ch]["out_var"].get() or "Off").lower() == "on" else "OFF"
            common.try_sequences(inst, [[f"{outp}STAT {out_val}"], [f"{outp}{out_val}"], ["OUTP:STAT {0}".format(out_val)]])

            mode = (self.ch[ch]["load_mode"].get() or "50 Ω")
            if mode.startswith("50"):
                inst.write(f"{outp}LOAD 50")
            elif mode.lower().startswith("high"):
                inst.write(f"{outp}LOAD INF")
            else:
                lv = _fnum(self.ch[ch]["load_val"].get(), None)
                if lv is None or lv <= 0:
                    messagebox.showwarning("FGEN", f"CH{ch}: Specify a valid load (ohms).")
                else:
                    inst.write(f"{outp}LOAD {lv}")

            rmode = (self.ch[ch]["range_mode"].get() or "Auto").lower()
            if rmode == "auto":
                common.try_sequences(inst, [[f"{src}VOLT:RANG:AUTO ON"], [f"{src}VOLT:RANG:AUTO ONCE"]])
            else:
                common.try_sequences(inst, [[f"{src}VOLT:RANG:AUTO OFF"], [f"{src}VOLT:RANG:AUTO 0"]])

            # Enforce HOLD again if needed
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
