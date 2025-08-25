# scpi_tabs/function_generator_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

def _fnum(s, default=0.0):
    try:
        return float(common.extract_number(s))
    except Exception:
        return float(default)

class FunctionGeneratorTab:
    """Function Generator tab UI + SCPI ops tailored for Keysight/Agilent 33250A (1-ch) & 33612A (2-ch)."""

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Function Generator")

        # runtime detection
        self._is_33612a = False
        self._is_33250a = False

        # State vars
        self.model_var     = tk.StringVar(value="")
        self.waveform_var  = tk.StringVar(value="SIN")
        self.freq_var      = tk.StringVar(value="1000")   # Hz
        self.amp_var       = tk.StringVar(value="1.0")    # amplitude value
        self.amp_unit_var  = tk.StringVar(value="VPP")    # VPP | VRMS | DBM
        self.offset_var    = tk.StringVar(value="0.0")    # V
        self.phase_var     = tk.StringVar(value="0.0")    # deg
        self.duty_var      = tk.StringVar(value="50")     # %
        self.load_var      = tk.StringVar(value="INF")    # 50 | INF | <ohms>
        self.ch_var        = tk.StringVar(value="1")      # 33612A: 1 or 2

        self._build_ui(self.frame)
        self._wire_field_enable_logic()

    # UI ----------------------------
    def _build_ui(self, parent):
        f = ttk.LabelFrame(parent, text="Function Generator Controls")
        f.pack(fill="x", padx=10, pady=10)

        # Row 0: Model + Channel (33612A만 노출)
        ttk.Label(f, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(f, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")

        self.ch_label = ttk.Label(f, text="Channel:")
        self.ch_combo = ttk.Combobox(f, textvariable=self.ch_var, state="readonly", values=["1", "2"], width=6)

        self.ch_label.grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.ch_combo.grid(row=0, column=3, padx=(0,12), pady=8, sticky="w")

        # Row 1: Waveform + Freq + Amp(+unit)
        ttk.Label(f, text="Waveform:").grid(row=1, column=0, padx=6, pady=8, sticky="e")
        self.wave_combo = ttk.Combobox(
            f, textvariable=self.waveform_var, state="readonly",
            values=["SIN", "SQU", "RAMP", "PULSE", "NOIS", "DC"], width=10
        )
        self.wave_combo.grid(row=1, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Freq (Hz):").grid(row=1, column=2, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.freq_var, width=14).grid(row=1, column=3, padx=(0,12), pady=8, sticky="w")

        amp_box = ttk.Frame(f)
        amp_box.grid(row=1, column=4, columnspan=2, padx=(0,12), pady=8, sticky="w")
        ttk.Label(amp_box, text="Amp").pack(side="left")
        ttk.Entry(amp_box, textvariable=self.amp_var, width=10).pack(side="left", padx=(6,6))
        ttk.Combobox(amp_box, textvariable=self.amp_unit_var, state="readonly",
                     values=["VPP", "VRMS", "DBM"], width=6).pack(side="left")

        # Row 2: Offset + Phase + Duty + Load
        ttk.Label(f, text="Offset (V):").grid(row=2, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.offset_var, width=12).grid(row=2, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Phase (deg):").grid(row=2, column=2, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.phase_var, width=12).grid(row=2, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Duty (%):").grid(row=2, column=4, padx=6, pady=8, sticky="e")
        self.duty_entry = ttk.Entry(f, textvariable=self.duty_var, width=10)
        self.duty_entry.grid(row=2, column=5, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Load (Ω):").grid(row=3, column=0, padx=6, pady=8, sticky="e")
        ttk.Entry(f, textvariable=self.load_var, width=12).grid(row=3, column=1, padx=(0,12), pady=8, sticky="w")

        # Row 3: Buttons
        ttk.Button(f, text="Apply", command=self.apply).grid(row=3, column=2, padx=6, pady=8)
        ttk.Button(f, text="Output ON", command=lambda: self.output(True)).grid(row=3, column=3, padx=6, pady=8)
        ttk.Button(f, text="Output OFF", command=lambda: self.output(False)).grid(row=3, column=4, padx=6, pady=8)
        ttk.Button(f, text="Read Back", command=self.read_back).grid(row=3, column=5, padx=6, pady=8)

        for c, w in enumerate([0,1,0,1,0,1]):
            f.grid_columnconfigure(c, weight=w)

    def _wire_field_enable_logic(self):
        def _on_wave_change(*_):
            wave = (self.waveform_var.get() or "").upper()
            # DC: freq/amp 비활성, offset만 사용
            dc = (wave == "DC")
            # SQU/PULSE: duty 활성
            needs_duty = (wave in ("SQU", "PULSE"))

            # Enable/disable by state
            new_state = "disabled" if dc else "normal"
            for var_widget in self._widgets_freq_amp():
                try: var_widget.config(state=new_state)
                except Exception: pass

            try: self.duty_entry.config(state=("normal" if needs_duty else "disabled"))
            except Exception: pass

        self.wave_combo.bind("<<ComboboxSelected>>", _on_wave_change)
        # initialize once
        self.frame.after(0, _on_wave_change)

    def _widgets_freq_amp(self):
        # Find the widgets by a simple traversal; here we rely on the entries added in build
        # Safer: return all Entries bound to self.freq_var and self.amp_var and the amp unit combobox
        entries = []
        def walk(w):
            for ch in w.winfo_children():
                try:
                    # crude: Entry with textvariable matching our StringVars
                    if isinstance(ch, ttk.Entry):
                        tv = ch.cget("textvariable")
                        if tv in (str(self.freq_var), str(self.amp_var)):
                            entries.append(ch)
                except Exception:
                    pass
                walk(ch)
        walk(self.frame)
        # also amp unit combo
        # find Combobox with variable amp_unit_var
        def find_amp_unit(w):
            for ch in w.winfo_children():
                try:
                    if isinstance(ch, ttk.Combobox) and ch.cget("textvariable") == str(self.amp_unit_var):
                        return ch
                except Exception:
                    pass
                ret = find_amp_unit(ch)
                if ret: return ret
            return None
        unit_cb = find_amp_unit(self.frame)
        if unit_cb: entries.append(unit_cb)
        return entries

    # State enable/disable from parent
    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state=("normal" if enabled else "disabled"))
        except Exception:
            pass

    # Device detect/update ----------------
    def update_for_active_device(self):
        inst = self.get_inst()
        idn = (self.get_idn() or "").strip()
        if not inst or not idn or not common.is_supported_fgen(idn):
            self.model_var.set("(No FGEN)")
            self._is_33612a = False
            self._is_33250a = False
            self._hide_channel_controls()
            self.set_enabled(False)
            return

        up = idn.upper()
        self._is_33612a = ("33612A" in up)
        self._is_33250a = ("33250A" in up)
        self.model_var.set(idn)
        self.set_enabled(True)

        if self._is_33612a:
            self._show_channel_controls()
        else:
            self._hide_channel_controls()

    def _show_channel_controls(self):
        try:
            self.ch_label.grid()
            self.ch_combo.grid()
        except Exception:
            pass

    def _hide_channel_controls(self):
        try:
            self.ch_label.grid_remove()
            self.ch_combo.grid_remove()
        except Exception:
            pass

    # SCPI helpers ------------------------
    def _srcp(self) -> str:
        """Return SCPI prefix for source-specific commands."""
        if self._is_33612a:
            ch = (self.ch_var.get() or "1").strip()
            if ch not in ("1", "2"):
                ch = "1"
            return f"SOUR{ch}:"
        # 33250A is single-channel; often bare commands (no SOUR prefix) are fine.
        return ""

    def _outp(self) -> str:
        """Output subsystem prefix (for ON/OFF, LOAD)."""
        if self._is_33612a:
            ch = (self.ch_var.get() or "1").strip()
            if ch not in ("1", "2"):
                ch = "1"
            return f"OUTP{ch}:"
        return "OUTP:"

    # Operations --------------------------
    def apply(self):
        try:
            inst = self.get_inst()
            if not inst:
                return

            wave = (self.waveform_var.get() or "SIN").upper()
            freq = _fnum(self.freq_var, 1000.0)
            amp  = _fnum(self.amp_var, 1.0)
            offs = _fnum(self.offset_var, 0.0)
            pha  = _fnum(self.phase_var, 0.0)
            duty = _fnum(self.duty_var, 50.0)
            load_raw = (self.load_var.get() or "INF").strip().upper()
            unit = (self.amp_unit_var.get() or "VPP").upper()

            # ---- APPL / basic setup ----
            # DC 파형은 장비마다 포맷 차이 → 시퀀스로 시도
            srcp = self._srcp()

            if wave == "DC":
                sequences = [
                    [f"{srcp}APPL:DC DEF,DEF,{offs}"],
                    [f"{srcp}FUNC DC", f"{srcp}VOLT:OFFS {offs}"],
                    [f"APPL:DC {offs}"],  # 33250A 호환
                ]
            else:
                sequences = [
                    [f"{srcp}APPL:{wave} {freq},{amp},{offs}"],
                    [f"{srcp}FUNC {wave}", f"{srcp}FREQ {freq}", f"{srcp}VOLT {amp}", f"{srcp}VOLT:OFFS {offs}"],
                    [f"{srcp}FUNC {wave}", f"{srcp}FREQuency {freq}", f"{srcp}VOLTage {amp}", f"{srcp}VOLTage:OFFSet {offs}"],
                ]
            common.try_sequences(inst, sequences)

            # ---- Amplitude unit (if supported) ----
            # Keysight 계열: VOLT:UNIT {VPP|VRMS|DBM}
            try:
                inst.write(f"{srcp}VOLT:UNIT {unit}")
            except Exception:
                # 일부 구형 FW/모델에서 미지원 → 무시
                pass

            # ---- Duty for SQU/PULSE ----
            if wave in ("SQU", "PULSE"):
                try:
                    inst.write(f"{srcp}FUNC:SQU:DCYC {duty}")
                except Exception:
                    try:
                        inst.write(f"{srcp}PULS:DCYC {duty}")
                    except Exception:
                        try:
                            inst.write(f"FUNC:SQU:DCYC {duty}")
                        except Exception:
                            pass

            # ---- Phase ----
            # Model 별로 PHAS 또는 FUNC:PHAS 지원
            try:
                inst.write(f"{srcp}PHAS {pha}")
            except Exception:
                try:
                    inst.write(f"{srcp}FUNC:PHAS {pha}")
                except Exception:
                    # 구형/제한 모델은 무시
                    pass

            # ---- Load/Impedance ----
            outp = self._outp()
            try:
                # 숫자 또는 INF
                val = load_raw
                if load_raw not in ("INF", "INFinity"):
                    # validate numeric
                    _ = float(common.extract_number(load_raw))
                    val = load_raw
                inst.write(f"{outp}LOAD {val}")
            except Exception:
                pass

            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Apply -> ({'33612A' if self._is_33612a else '33250A'}) "
                     f"CH={self.ch_var.get() if self._is_33612a else '1'}, "
                     f"W={wave}, F={freq}, A={amp} {unit}, O={offs}, P={pha}, D={duty}, L={load_raw}")
            self.status.set("FGEN settings applied.")
        except Exception as e:
            messagebox.showerror("FGEN Apply failed", str(e))

    def output(self, on: bool):
        try:
            inst = self.get_inst()
            if not inst:
                return
            val = "ON" if on else "OFF"
            outp = self._outp()
            sequences = [
                [f"{outp}STAT {val}"],
                [f"{outp}{val}"],     # e.g., OUTP1 ON
                [f"OUTP {val}"],      # 33250A fallback
                [f"OUTPut:STATe {val}"]
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[FGEN]")
            self.log(f"[FGEN] Output -> {val} (CH={self.ch_var.get() if self._is_33612a else '1'})")
            self.status.set(f"FGEN output {val}.")
        except Exception as e:
            messagebox.showerror("FGEN Output failed", str(e))

    def read_back(self):
        """Query back current settings from the active channel/device."""
        try:
            inst = self.get_inst()
            if not inst:
                return

            srcp = self._srcp()
            outp = self._outp()

            # Wave
            try:
                wave = (inst.query(f"{srcp}FUNC?") or "").strip()
            except Exception:
                wave = (inst.query("FUNC?") or "").strip()

            # Freq/Volt/Offset/Phase
            def q(cmds, default=""):
                for c in cmds:
                    try:
                        return (inst.query(c) or "").strip()
                    except Exception:
                        continue
                return default

            freq = q([f"{srcp}FREQ?", "FREQ?"])
            amp  = q([f"{srcp}VOLT?", "VOLT?"])
            unit = q([f"{srcp}VOLT:UNIT?", "VOLT:UNIT?"], default="")
            offs = q([f"{srcp}VOLT:OFFS?", "VOLT:OFFS?"])
            pha  = q([f"{srcp}PHAS?", f"{srcp}FUNC:PHAS?", "PHAS?", "FUNC:PHAS?"], default="")

            duty = ""
            wu = wave.upper()
            if wu.startswith("SQU") or wu.startswith("PULS"):
                duty = q([f"{srcp}FUNC:SQU:DCYC?", f"{srcp}PULS:DCYC?", "FUNC:SQU:DCYC?","PULS:DCYC?"], "")

            load = q([f"{outp}LOAD?", "OUTP:LOAD?"], "")
            out_state = q([f"{outp}STAT?", "OUTP:STAT?"], "")

            msg = (f"Wave={wave}, F={freq}, A={amp}{(' ' + unit) if unit else ''}, "
                   f"O={offs}, P={pha}, Duty={duty}, Load={load}, Output={out_state}")
            self.log(f"[FGEN] Read Back -> {msg}")
            self.status.set("FGEN settings read.")
            messagebox.showinfo("FGEN Settings", msg)
        except Exception as e:
            messagebox.showerror("FGEN Read Back failed", str(e))
