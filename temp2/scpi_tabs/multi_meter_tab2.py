# scpi_tabs/multi_meter_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

def _fnum(s, default=None):
    try:
        x = float(common.extract_number(s))
        return x
    except Exception:
        return default

def _trim(s):
    return common.trim(s)

class MultiMeterTab:
    """Multi Meter tab UI + extended SCPI ops.
    Supported IDNs: 34410A, 34461A, 34465A, 34470A, DMM4040(4040), Keithley 2000, HP 3458A
    """

    MODES = ["VOLT:DC", "VOLT:AC", "CURR:DC", "CURR:AC",
             "RES", "FRES", "FREQ", "PER", "DIOD", "CONT"]

    TRIG_SOURCES = ["IMM", "BUS", "EXT"]
    AZ_CHOICES = ["AUTO", "ON", "OFF"]                # 다양한 계열 커버
    AC_OPT_TARGETS = ["DET:BAND", "BAND", "APER"]     # AC 옵션 키

    STAT_FUNCS = ["NONE", "AVER", "MIN", "MAX", "SDEV"]  # 일부 장비에서만 지원

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
        self.model_var    = tk.StringVar(value="")
        self.mode_var     = tk.StringVar(value="VOLT:DC")
        self.reading_var  = tk.StringVar(value="")

        self.range_auto   = tk.BooleanVar(value=True)
        self.range_var    = tk.StringVar(value="")     # e.g., 10, 100, etc.
        self.res_var      = tk.StringVar(value="")     # resolution in units or digits (장비에 따라 다르게 시도)

        self.nplc_var     = tk.StringVar(value="10")   # integration time (power line cycles)
        self.azero_var    = tk.StringVar(value="AUTO") # autozero mode

        self.ac_opt_var   = tk.StringVar(value="")     # AC bandwidth/aperture (Hz or s)
        self.term_var     = tk.StringVar(value="FRONT")

        self.trig_src_var   = tk.StringVar(value="IMM")
        self.samp_count_var = tk.StringVar(value="1")
        self.trig_delay_var = tk.StringVar(value="0")

        self.stat_func_var  = tk.StringVar(value="NONE")

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
                                       values=self.MODES, width=10)
        self.mode_combo.grid(row=0, column=3, padx=(0,12), pady=6, sticky="w")

        ttk.Button(top, text="Set Mode", command=self.set_mode).grid(row=0, column=4, padx=6, pady=6)
        ttk.Button(top, text="Read / Fetch", command=self.query_measurement).grid(row=0, column=5, padx=6, pady=6)

        ttk.Label(top, text="Reading:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(top, textvariable=self.reading_var, width=18, state="readonly").grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")

        for c, w in enumerate([0,1,0,1,0,0]):
            top.grid_columnconfigure(c, weight=w)

        # Configure group: range/res, nplc, az, AC opt, terminals
        cfg = ttk.LabelFrame(parent, text="Measure Configuration")
        cfg.pack(fill="x", padx=10, pady=(0,10))

        # Range + Auto
        ttk.Checkbutton(cfg, text="Auto Range", variable=self.range_auto).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(cfg, text="Range:").grid(row=0, column=1, padx=6, pady=6, sticky="e")
        ttk.Entry(cfg, textvariable=self.range_var, width=10).grid(row=0, column=2, padx=(0,12), pady=6, sticky="w")

        # Resolution / Digits
        ttk.Label(cfg, text="Resolution / Digits:").grid(row=0, column=3, padx=6, pady=6, sticky="e")
        ttk.Entry(cfg, textvariable=self.res_var, width=12).grid(row=0, column=4, padx=(0,12), pady=6, sticky="w")

        # NPLC
        ttk.Label(cfg, text="NPLC / Aperture:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(cfg, textvariable=self.nplc_var, width=10).grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")

        # Autozero
        ttk.Label(cfg, text="AutoZero:").grid(row=1, column=2, padx=6, pady=6, sticky="e")
        ttk.Combobox(cfg, textvariable=self.azero_var, state="readonly",
                     values=self.AZ_CHOICES, width=8).grid(row=1, column=3, padx=(0,12), pady=6, sticky="w")

        # AC opt
        ttk.Label(cfg, text="AC Option (Band/Aper):").grid(row=1, column=4, padx=6, pady=6, sticky="e")
        ttk.Entry(cfg, textvariable=self.ac_opt_var, width=12).grid(row=1, column=5, padx=(0,12), pady=6, sticky="w")

        # Terminals
        ttk.Label(cfg, text="Terminals:").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(cfg, textvariable=self.term_var, state="readonly",
                     values=["FRONT", "REAR"], width=8).grid(row=2, column=1, padx=(0,12), pady=6, sticky="w")

        ttk.Button(cfg, text="Apply Settings", command=self.apply_settings).grid(row=2, column=5, padx=6, pady=6, sticky="e")

        for c, w in enumerate([0,1,0,1,0,1]):
            cfg.grid_columnconfigure(c, weight=w)

        # Trigger / Multipoint group
        trg = ttk.LabelFrame(parent, text="Trigger / Multipoint")
        trg.pack(fill="x", padx=10, pady=(0,10))

        ttk.Label(trg, text="Trig Source:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(trg, textvariable=self.trig_src_var, state="readonly",
                     values=self.TRIG_SOURCES, width=8).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        ttk.Label(trg, text="Sample Count:").grid(row=0, column=2, padx=6, pady=6, sticky="e")
        ttk.Entry(trg, textvariable=self.samp_count_var, width=10).grid(row=0, column=3, padx=(0,12), pady=6, sticky="w")

        ttk.Label(trg, text="Trig Delay (s):").grid(row=0, column=4, padx=6, pady=6, sticky="e")
        ttk.Entry(trg, textvariable=self.trig_delay_var, width=10).grid(row=0, column=5, padx=(0,12), pady=6, sticky="w")

        ttk.Button(trg, text="Apply Trigger", command=self.apply_trigger).grid(row=1, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(trg, text="Init (Single)", command=self.init_single).grid(row=1, column=1, padx=6, pady=6, sticky="w")
        ttk.Button(trg, text="Abort", command=self.abort).grid(row=1, column=2, padx=6, pady=6, sticky="w")

        for c, w in enumerate([0,1,0,1,0,1]):
            trg.grid_columnconfigure(c, weight=w)

        # Statistics group (if supported)
        stat = ttk.LabelFrame(parent, text="Statistics (if supported)")
        stat.pack(fill="x", padx=10, pady=(0,10))

        ttk.Label(stat, text="Function:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Combobox(stat, textvariable=self.stat_func_var, state="readonly",
                     values=self.STAT_FUNCS, width=8).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        ttk.Button(stat, text="Enable", command=self.stats_enable).grid(row=0, column=2, padx=6, pady=6, sticky="w")
        ttk.Button(stat, text="Disable", command=self.stats_disable).grid(row=0, column=3, padx=6, pady=6, sticky="w")
        ttk.Button(stat, text="Query", command=self.stats_query).grid(row=0, column=4, padx=6, pady=6, sticky="w")
        ttk.Button(stat, text="Clear", command=self.stats_clear).grid(row=0, column=5, padx=6, pady=6, sticky="w")

        for c, w in enumerate([0,1,0,1,0,1]):
            stat.grid_columnconfigure(c, weight=w)

    def _wire_dynamic_ui(self):
        def on_mode_change(*_):
            mode = (self.mode_var.get() or "").upper()
            # AC 옵션 필드는 AC 모드에서 강조, 그 외에는 그대로
            # RES vs FRES: 4선 모드(FRES) 선택 시 범위/해상도 UI 동일 사용
            # DIOD/CONT: 범위/레졸루션/AC옵션/NPLC 일부 무시될 수 있으나 UI는 유지
            pass
        self.mode_combo.bind("<<ComboboxSelected>>", on_mode_change)

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

    # --------------- Helpers ----------------
    def _sense_path(self) -> str:
        """Return 'SENS:<func>' or safe default."""
        mode = (self.mode_var.get() or "VOLT:DC").upper()
        return f"SENS:{mode}"

    def _conf_tuple(self):
        """Return (range_val_or_None, res_val_or_None, auto_bool)."""
        rng = _fnum(self.range_var.get(), None)
        res = _fnum(self.res_var.get(), None)
        return (rng, res, bool(self.range_auto.get()))

    # --------------- Ops: Mode / Settings ----------------
    def set_mode(self):
        try:
            inst = self.get_inst()
            if not inst: return
            mode = (self.mode_var.get() or "VOLT:DC").upper()
            rng, res, auto = self._conf_tuple()

            # Prefer CONF with range/res if provided and auto off
            if not auto and (rng is not None or res is not None):
                # Try CONF:<mode> range,res
                seq = []
                if rng is not None and res is not None:
                    seq.append([f"CONF:{mode} {rng},{res}"])
                if rng is not None and res is None:
                    # some models accept range only
                    seq.append([f"CONF:{mode} {rng}"])
                if not seq:
                    seq.append([f"CONF:{mode}"])  # fallback
                seq += [
                    [f"FUNC '{mode}'"],
                    [f"FUNC {mode}"],
                ]
                common.try_sequences(inst, seq)
            else:
                # just set function
                common.try_sequences(inst, [
                    [f"CONF:{mode}"],
                    [f"FUNC '{mode}'"],
                    [f"FUNC {mode}"],
                ])

            common.drain_error_queue(inst, self.log, "[DMM]")
            self.log(f"[DMM] Set Mode -> {mode}")
        except Exception as e:
            messagebox.showerror("DMM Set Mode failed", str(e))

    def apply_settings(self):
        """Apply range/auto, resolution, NPLC/Aperture, autozero, AC option, terminals."""
        try:
            inst = self.get_inst()
            if not inst: return
            sense = self._sense_path()
            mode  = (self.mode_var.get() or "VOLT:DC").upper()
            rng, res, auto = self._conf_tuple()
            nplc = _fnum(self.nplc_var.get(), None)
            az   = (self.azero_var.get() or "AUTO").upper()
            acop = _fnum(self.ac_opt_var.get(), None)
            term = (self.term_var.get() or "FRONT").upper()

            # Range + Auto
            if auto:
                common.try_sequences(inst, [
                    [f"{sense}:RANG:AUTO ON"],
                    [f"{sense}:RANG:AUTO 1"],
                ])
            else:
                if rng is not None:
                    common.try_sequences(inst, [
                        [f"{sense}:RANG {rng}"],
                        [f"CONF:{mode} {rng}"],
                    ])
                # Resolution
                if res is not None:
                    # try resolution in absolute units
                    wrote = False
                    try:
                        inst.write(f"{sense}:RES {res}")
                        wrote = True
                    except Exception:
                        pass
                    if not wrote:
                        # try digit-based
                        try:
                            inst.write(f"{sense}:DIG {int(res)}")
                        except Exception:
                            pass

            # NPLC (or Aperture)
            if nplc is not None:
                tried = False
                for cmd in (f"{sense}:NPLC {nplc}", f"{sense}:APER {nplc}"):
                    try:
                        inst.write(cmd)
                        tried = True
                        break
                    except Exception:
                        continue
                if not tried and self._is_3458a:
                    # 3458A specific aperture command (seconds)
                    try:
                        inst.write(f"APER {nplc}")
                    except Exception:
                        pass

            # AutoZero (various dialects)
            if az in ("AUTO","ON","OFF"):
                sequences = []
                if az == "AUTO":
                    sequences += [
                        ["SYST:AZER ON"], ["SYST:AZER:AUTO ON"],
                        ["ZERO:AUTO ON"], ["SENS:ZERO:AUTO ON"],
                    ]
                elif az == "ON":
                    sequences += [
                        ["SYST:AZER ON"], ["SYST:AZER:STAT ON"],
                        ["ZERO:AUTO ON"], ["SENS:ZERO:AUTO ON"],
                    ]
                elif az == "OFF":
                    sequences += [
                        ["SYST:AZER OFF"], ["SYST:AZER:STAT OFF"],
                        ["ZERO:AUTO OFF"], ["SENS:ZERO:AUTO OFF"],
                    ]
                # Try all sequences until one works
                ok = False
                last = None
                for seq in sequences:
                    try:
                        for c in seq:
                            inst.write(c)
                        ok = True
                        break
                    except Exception as e:
                        last = e
                        continue
                if not ok and last:
                    # non-fatal, ignore
                    pass

            # AC-related option (bandwidth or aperture)
            if "AC" in mode and acop is not None:
                common.try_sequences(inst, [
                    [f"{sense}:DET:BAND {acop}"],
                    [f"{sense}:BAND {acop}"],
                    [f"{sense}:APER {acop}"],
                ])

            # Terminals (front/rear)
            common.try_sequences(inst, [
                [f"ROUT:TERM {term}"],
                [f"ROUT:TERM {('FRON' if term=='FRONT' else 'REAR')}"],
            ])

            common.drain_error_queue(inst, self.log, "[DMM]")
            self.log(f"[DMM] Apply Settings -> mode={mode}, auto={auto}, range={rng}, res={res}, "
                     f"nplc/aper={nplc}, az={az}, acopt={acop}, term={term}")
        except Exception as e:
            messagebox.showerror("DMM Apply Settings failed", str(e))

    # --------------- Ops: Trigger / Multipoint ---------------
    def apply_trigger(self):
        try:
            inst = self.get_inst()
            if not inst: return

            src  = (self.trig_src_var.get() or "IMM").upper()
            scnt = _fnum(self.samp_count_var.get(), None)
            dly  = _fnum(self.trig_delay_var.get(), None)

            # Trigger source
            common.try_sequences(inst, [
                [f"TRIG:SOUR {src}"],
                [f"TRIG:SOURCE {src}"],
            ])
            # Sample count
            if scnt is not None:
                common.try_sequences(inst, [
                    [f"SAMP:COUN {int(scnt)}"],
                    [f"SAMP:COUNt {int(scnt)}"],
                ])
            # Trigger delay
            if dly is not None:
                common.try_sequences(inst, [
                    [f"TRIG:DEL {dly}"],
                    [f"TRIG:DELay {dly}"],
                ])

            common.drain_error_queue(inst, self.log, "[DMM]")
            self.log(f"[DMM] Apply Trigger -> src={src}, samp_count={scnt}, delay={dly}")
        except Exception as e:
            messagebox.showerror("DMM Apply Trigger failed", str(e))

    def init_single(self):
        try:
            inst = self.get_inst()
            if not inst: return
            common.try_sequences(inst, [
                ["ABOR", "INIT"],
                ["INIT"],
            ])
            self.log("[DMM] INIT (single)")
            self.status.set("DMM initiated.")
        except Exception as e:
            messagebox.showerror("DMM INIT failed", str(e))

    def abort(self):
        try:
            inst = self.get_inst()
            if not inst: return
            common.try_sequences(inst, [["ABOR"], ["ABORT"]])
            self.log("[DMM] ABORt")
            self.status.set("DMM aborted.")
        except Exception as e:
            messagebox.showerror("DMM Abort failed", str(e))

    # --------------- Ops: Statistics ----------------
    def stats_enable(self):
        try:
            inst = self.get_inst()
            if not inst: return
            func = (self.stat_func_var.get() or "NONE").upper()
            if func == "NONE":
                return
            # enable statistics and set function if supported
            seq = [
                ["CALC:STAT:STATE ON"],
                ["CALC:STAT:FUNC " + ("AVER" if func=="AVER" else func)],
            ]
            # Some models split enable/func order, try both
            common.try_sequences(inst, [seq, seq[::-1]])
            self.log(f"[DMM] Stats Enable -> {func}")
            common.drain_error_queue(inst, self.log, "[DMM]")
        except Exception as e:
            # not fatal
            messagebox.showwarning("DMM Stats Enable", f"Statistics may be unsupported on this model.\n{e}")

    def stats_disable(self):
        try:
            inst = self.get_inst()
            if not inst: return
            common.try_sequences(inst, [["CALC:STAT:STATE OFF"]])
            self.log("[DMM] Stats Disable")
            common.drain_error_queue(inst, self.log, "[DMM]")
        except Exception as e:
            messagebox.showwarning("DMM Stats Disable", f"Statistics may be unsupported.\n{e}")

    def stats_clear(self):
        try:
            inst = self.get_inst()
            if not inst: return
            common.try_sequences(inst, [["CALC:STAT:CLE"]])
            self.log("[DMM] Stats Clear")
            common.drain_error_queue(inst, self.log, "[DMM]")
        except Exception as e:
            messagebox.showwarning("DMM Stats Clear", f"Statistics may be unsupported.\n{e}")

    def stats_query(self):
        try:
            inst = self.get_inst()
            if not inst: return
            # Try typical queries
            def q(cmds):
                for c in cmds:
                    try:
                        return _trim(inst.query(c))
                    except Exception:
                        continue
                return ""
            mean = q(["CALC:STAT:MEAN?", "CALC:STAT:AVER?"])
            sdev = q(["CALC:STAT:STDD?", "CALC:STAT:SDEV?"])
            vmin = q(["CALC:STAT:MIN?"])
            vmax = q(["CALC:STAT:MAX?"])

            msg = f"AVG={mean or 'N/A'}, SDEV={sdev or 'N/A'}, MIN={vmin or 'N/A'}, MAX={vmax or 'N/A'}"
            self.log(f"[DMM] Stats -> {msg}")
            messagebox.showinfo("DMM Statistics", msg)
        except Exception as e:
            messagebox.showwarning("DMM Stats Query", f"Statistics query may be unsupported.\n{e}")

    # --------------- Ops: Measure ----------------
    def query_measurement(self):
        """Best-effort reading: MEAS:<mode>? -> READ? -> INIT;*WAI;FETCh? -> FETCh? -> MEAS?"""
        try:
            inst = self.get_inst()
            if not inst: return
            mode = (self.mode_var.get() or "VOLT:DC").upper()

            candidates = [
                f"MEAS:{mode}?",
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
