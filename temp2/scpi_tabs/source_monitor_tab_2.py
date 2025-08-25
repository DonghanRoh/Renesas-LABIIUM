# scpi_tabs/source_monitor_unit_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

def _fnum(s, default=None):
    try:
        return float(common.extract_number(s))
    except Exception:
        return default

def _trim(s):
    return common.trim(s)

class SourceMonitorUnitTab:
    """Source Monitor Unit tab UI + extended SCPI ops.
    Supported IDNs: Keithley 2420/2440 (2400 classic), 2450/2460/2461 (touch series)
    """

    TRIG_SOURCES = ["IMM", "BUS", "EXT"]
    AVG_TYPES = ["MOV", "REP"]  # moving / repeat

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Source Monitor Unit")

        # runtime detection
        self._is_touch = False   # 2450/2460/2461
        self._is_2400c = False   # 2420/2440 (2400 classic)

        # UI state
        self.model_var = tk.StringVar(value="")
        self.sourcemode_var = tk.StringVar(value="VOLT")  # VOLT or CURR

        self.level_var = tk.StringVar(value="0")          # source level
        self.comp_i_var = tk.StringVar(value="0.01")      # current compliance (A) when sourcing VOLT
        self.comp_v_var = tk.StringVar(value="10")        # voltage compliance (V) when sourcing CURR

        self.v_auto_var = tk.BooleanVar(value=True)
        self.v_range_var = tk.StringVar(value="")
        self.i_auto_var = tk.BooleanVar(value=True)
        self.i_range_var = tk.StringVar(value="")

        self.nplc_var = tk.StringVar(value="1.0")         # integration time (PLC)

        self.avg_on_var = tk.BooleanVar(value=False)
        self.avg_type_var = tk.StringVar(value="MOV")
        self.avg_count_var = tk.StringVar(value="10")

        self.trig_src_var = tk.StringVar(value="IMM")
        self.samp_count_var = tk.StringVar(value="1")
        self.trig_delay_var = tk.StringVar(value="0")

        self.meas_v_var = tk.StringVar(value="")
        self.meas_i_var = tk.StringVar(value="")

        self._build_ui(self.frame)
        self._wire_dynamic_ui()

    # ---------------- UI ----------------
    def _build_ui(self, parent):
        top = ttk.LabelFrame(parent, text="SMU Overview")
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Model:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Label(top, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")

        ttk.Label(top, text="Source Mode:").grid(row=0, column=2, padx=6, pady=6, sticky="e")
        self.mode_combo = ttk.Combobox(top, textvariable=self.sourcemode_var, state="readonly",
                                       values=["VOLT", "CURR"], width=8)
        self.mode_combo.grid(row=0, column=3, padx=(0,12), pady=6, sticky="w")
        ttk.Button(top, text="Set Mode", command=self.set_source_mode).grid(row=0, column=4, padx=6, pady=6)

        # Source group
        src = ttk.LabelFrame(parent, text="Source Settings")
        src.pack(fill="x", padx=10, pady=(0,10))

        ttk.Label(src, text="Level:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(src, textvariable=self.level_var, width=12).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")
        ttk.Button(src, text="Apply Level", command=self.set_level).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(src, text="Output ON", command=lambda: self.output(True)).grid(row=0, column=3, padx=6, pady=6)
        ttk.Button(src, text="Output OFF", command=lambda: self.output(False)).grid(row=0, column=4, padx=6, pady=6)

        ttk.Label(src, text="Compliance I (A) for VOLT src:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(src, textvariable=self.comp_i_var, width=12).grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")

        ttk.Label(src, text="Compliance V (V) for CURR src:").grid(row=1, column=2, padx=6, pady=6, sticky="e")
        ttk.Entry(src, textvariable=self.comp_v_var, width=12).grid(row=1, column=3, padx=(0,12), pady=6, sticky="w")
        ttk.Button(src, text="Apply Compliance", command=self.apply_compliance).grid(row=1, column=4, padx=6, pady=6)

        for c, w in enumerate([0,1,0,1,0]):
            src.grid_columnconfigure(c, weight=w)

        # Sense group (ranges + NPLC + averaging)
        sns = ttk.LabelFrame(parent, text="Sense (Measurement) Configuration")
        sns.pack(fill="x", padx=10, pady=(0,10))

        # Voltage range
        ttk.Checkbutton(sns, text="V Auto Range", variable=self.v_auto_var).grid(row=0, column=0, padx=6, pady=6, sticky="w")
        ttk.Label(sns, text="V Range (V):").grid(row=0, column=1, padx=6, pady=6, sticky="e")
        ttk.Entry(sns, textvariable=self.v_range_var, width=10).grid(row=0, column=2, padx=(0,12), pady=6, sticky="w")

        # Current range
        ttk.Checkbutton(sns, text="I Auto Range", variable=self.i_auto_var).grid(row=0, column=3, padx=6, pady=6, sticky="w")
        ttk.Label(sns, text="I Range (A):").grid(row=0, column=4, padx=6, pady=6, sticky="e")
        ttk.Entry(sns, textvariable=self.i_range_var, width=10).grid(row=0, column=5, padx=(0,12), pady=6, sticky="w")

        # NPLC
        ttk.Label(sns, text="NPLC:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(sns, textvariable=self.nplc_var, width=10).grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")

        # Averaging
        ttk.Checkbutton(sns, text="Averaging ON", variable=self.avg_on_var).grid(row=1, column=2, padx=6, pady=6, sticky="w")
        ttk.Label(sns, text="Type:").grid(row=1, column=3, padx=6, pady=6, sticky="e")
        ttk.Combobox(sns, textvariable=self.avg_type_var, state="readonly", values=self.AVG_TYPES, width=6)\
            .grid(row=1, column=4, padx=(0,12), pady=6, sticky="w")
        ttk.Label(sns, text="Count:").grid(row=1, column=5, padx=6, pady=6, sticky="e")
        ttk.Entry(sns, textvariable=self.avg_count_var, width=8).grid(row=1, column=6, padx=(0,12), pady=6, sticky="w")

        ttk.Button(sns, text="Apply Sense", command=self.apply_sense).grid(row=2, column=6, padx=6, pady=6, sticky="e")

        for c, w in enumerate([0,1,0,1,0,0,1]):
            sns.grid_columnconfigure(c, weight=w)

        # Trigger / Sampling
        trg = ttk.LabelFrame(parent, text="Trigger / Sampling")
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

        # Measurements
        meas = ttk.LabelFrame(parent, text="Measurements")
        meas.pack(fill="x", padx=10, pady=(0,10))

        ttk.Label(meas, text="Measure V (V):").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(meas, textvariable=self.meas_v_var, width=16, state="readonly").grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")
        ttk.Button(meas, text="Query V", command=self.measure_v).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(meas, text="Measure I (A):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(meas, textvariable=self.meas_i_var, width=16, state="readonly").grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")
        ttk.Button(meas, text="Query I", command=self.measure_i).grid(row=1, column=2, padx=6, pady=6)

        ttk.Button(meas, text="Read (V&I)", command=self.measure_vi).grid(row=0, column=3, padx=6, pady=6)

        for c, w in enumerate([0,1,0,1]):
            meas.grid_columnconfigure(c, weight=w)

    def _wire_dynamic_ui(self):
        def on_mode_change(*_):
            # 모드에 따라 컴플라이언스 입력 힌트 강조 등 UI 조정 여지
            pass
        self.mode_combo.bind("<<ComboboxSelected>>", on_mode_change)

    # ---------------- State / Model detect ----------------
    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state=("normal" if enabled else "disabled"))
        except Exception:
            pass

    def update_for_active_device(self):
        inst = self.get_inst()
        idn = self.get_idn()
        if not inst or not idn or not common.is_supported_smu(idn):
            self.model_var.set("(No SMU)")
            self.set_enabled(False)
            return

        up = (idn or "").upper()
        self._is_touch = any(m in up for m in ("2450", "2460", "2461"))
        self._is_2400c = any(m in up for m in ("2420", "2440"))
        self.model_var.set((idn or "").strip())
        self.set_enabled(True)

    # ---------------- Helpers ----------------
    def _sense(self, q: str) -> str:
        """Build SENS:<subtree> path with graceful fallback idea."""
        return f"SENS:{q}"

    def _try_write(self, inst, cmds):
        # cmds: list of command strings to try in order
        for c in cmds:
            try:
                inst.write(c)
                return True
            except Exception:
                continue
        return False

    # ---------------- Ops: Source / Compliance / Output ----------------
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
            # 2450 계열은 센스함수 자동 설정되지만, 안전하게 V/I 모두 반환하도록 FORM 구성
            try:
                # Try to set default read format to include volt & curr (model dep.)
                inst.write("FORM:ELEM VOLT,CURR")
            except Exception:
                pass
            common.drain_error_queue(inst, self.log, "[SMU]")
            self.log(f"[SMU] Set Source Mode -> {mode}")
        except Exception as e:
            messagebox.showerror("SMU Set Mode failed", str(e))

    def set_level(self):
        try:
            inst = self.get_inst()
            if not inst: return
            mode = (self.sourcemode_var.get() or "VOLT").upper()
            val = _fnum(self.level_var.get(), None)
            if val is None:
                messagebox.showinfo("Invalid Level", "Enter a numeric level."); return

            if mode == "VOLT":
                sequences = [[f"SOUR:VOLT {val}"], [f"SOURce:VOLTage {val}"]]
            else:
                sequences = [[f"SOUR:CURR {val}"], [f"SOURce:CURRent {val}"]]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[SMU]")
            self.log(f"[SMU] Apply Level -> {val} ({mode})")
        except Exception as e:
            messagebox.showerror("SMU Apply Level failed", str(e))

    def apply_compliance(self):
        """Set current or voltage compliance depending on source mode."""
        try:
            inst = self.get_inst()
            if not inst: return
            mode = (self.sourcemode_var.get() or "VOLT").upper()

            if mode == "VOLT":
                ilim = _fnum(self.comp_i_var.get(), None)
                if ilim is None:
                    messagebox.showinfo("Invalid Current Limit", "Enter numeric Compliance I (A)."); return
                # Current protection for VOLT source
                seqs = [
                    [f"{self._sense('CURR:PROT')} {ilim}"],
                    [f"SENS:CURR:PROT {ilim}"],
                    [f"SENS:CURRent:PROTection {ilim}"],
                ]
                common.try_sequences(inst, seqs)
                # some models may require enable
                self._try_write(inst, ["SENS:CURR:PROT:STAT ON", "SENS:CURR:PROT:STATe ON"])
                self.log(f"[SMU] Compliance -> I = {ilim} A (for VOLT source)")
            else:
                vlim = _fnum(self.comp_v_var.get(), None)
                if vlim is None:
                    messagebox.showinfo("Invalid Voltage Limit", "Enter numeric Compliance V (V)."); return
                # Voltage protection for CURR source
                seqs = [
                    [f"{self._sense('VOLT:PROT')} {vlim}"],
                    [f"SENS:VOLT:PROT {vlim}"],
                    [f"SENS:VOLTage:PROTection {vlim}"],
                ]
                common.try_sequences(inst, seqs)
                self._try_write(inst, ["SENS:VOLT:PROT:STAT ON", "SENS:VOLT:PROT:STATe ON"])
                self.log(f"[SMU] Compliance -> V = {vlim} V (for CURR source)")

            common.drain_error_queue(inst, self.log, "[SMU]")
        except Exception as e:
            messagebox.showerror("SMU Apply Compliance failed", str(e))

    def output(self, on: bool):
        try:
            inst = self.get_inst()
            if not inst: return
            val = "ON" if on else "OFF"
            sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[SMU]")
            self.log(f"[SMU] Output -> {val}")
            self.status.set(f"SMU output {val}.")
        except Exception as e:
            messagebox.showerror("SMU Output failed", str(e))

    # ---------------- Ops: Sense config ----------------
    def apply_sense(self):
        """Apply ranges, NPLC, and averaging (filter) settings for both V and I."""
        try:
            inst = self.get_inst()
            if not inst: return

            # Voltage range
            if bool(self.v_auto_var.get()):
                common.try_sequences(inst, [
                    [f"SENS:VOLT:RANG:AUTO ON"],
                    [f"SENS:VOLTage:RANGe:AUTO ON"],
                ])
            else:
                vr = _fnum(self.v_range_var.get(), None)
                if vr is not None:
                    common.try_sequences(inst, [
                        [f"SENS:VOLT:RANG {vr}"],
                        [f"SENS:VOLTage:RANGe {vr}"],
                    ])

            # Current range
            if bool(self.i_auto_var.get()):
                common.try_sequences(inst, [
                    [f"SENS:CURR:RANG:AUTO ON"],
                    [f"SENS:CURRent:RANGe:AUTO ON"],
                ])
            else:
                ir = _fnum(self.i_range_var.get(), None)
                if ir is not None:
                    common.try_sequences(inst, [
                        [f"SENS:CURR:RANG {ir}"],
                        [f"SENS:CURRent:RANGe {ir}"],
                    ])

            # NPLC (apply to both V/I if available)
            nplc = _fnum(self.nplc_var.get(), None)
            if nplc is not None:
                self._try_write(inst, [
                    f"SENS:VOLT:NPLC {nplc}",
                    f"SENS:VOLTage:NPLCycles {nplc}",
                ])
                self._try_write(inst, [
                    f"SENS:CURR:NPLC {nplc}",
                    f"SENS:CURRent:NPLCycles {nplc}",
                ])

            # Averaging / Filter
            avg_on = bool(self.avg_on_var.get())
            avg_type = (self.avg_type_var.get() or "MOV").upper()
            avg_cnt = _fnum(self.avg_count_var.get(), None)
            # state
            self._try_write(inst, [
                f"SENS:AVER:STAT {'ON' if avg_on else 'OFF'}",
                f"SENS:AVERage:STATe {'ON' if avg_on else 'OFF'}",
            ])
            # type (MOV/REP)
            self._try_write(inst, [
                f"SENS:AVER:TCON {avg_type}",
                f"SENS:AVERage:TCONtrol {avg_type}",
            ])
            # count
            if avg_cnt is not None:
                self._try_write(inst, [
                    f"SENS:AVER:COUN {int(avg_cnt)}",
                    f"SENS:AVERage:COUNt {int(avg_cnt)}",
                ])

            common.drain_error_queue(inst, self.log, "[SMU]")
            self.log(f"[SMU] Apply Sense -> Vauto={self.v_auto_var.get()}, Vrange={self.v_range_var.get()}, "
                     f"Iauto={self.i_auto_var.get()}, Irange={self.i_range_var.get()}, "
                     f"NPLC={self.nplc_var.get()}, AVG={'ON' if avg_on else 'OFF'} {avg_type} {avg_cnt}")
        except Exception as e:
            messagebox.showerror("SMU Apply Sense failed", str(e))

    # ---------------- Ops: Trigger / Sampling ----------------
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

            self.log(f"[SMU] Apply Trigger -> src={src}, samp_count={scnt}, delay={dly}")
            common.drain_error_queue(inst, self.log, "[SMU]")
        except Exception as e:
            messagebox.showerror("SMU Apply Trigger failed", str(e))

    def init_single(self):
        try:
            inst = self.get_inst()
            if not inst: return
            common.try_sequences(inst, [
                ["ABOR", "INIT"],
                ["INIT"],
            ])
            self.log("[SMU] INIT (single)")
            self.status.set("SMU initiated.")
        except Exception as e:
            messagebox.showerror("SMU INIT failed", str(e))

    def abort(self):
        try:
            inst = self.get_inst()
            if not inst: return
            common.try_sequences(inst, [["ABOR"], ["ABORT"]])
            self.log("[SMU] ABORt")
            self.status.set("SMU aborted.")
        except Exception as e:
            messagebox.showerror("SMU Abort failed", str(e))

    # ---------------- Ops: Measurements ----------------
    def _read_generic(self, queries):
        """Try a list of query strings and return first non-empty response."""
        inst = self.get_inst()
        last_err = None
        for q in queries:
            try:
                r = (inst.query(q) or "").strip()
                if r:
                    return r
            except Exception as e:
                last_err = e
                continue
        if last_err:
            raise last_err
        return ""

    def measure_v(self):
        try:
            inst = self.get_inst()
            if not inst: return
            # many models support MEAS:VOLT? or READ? with FORM:ELEM
            resp = self._read_generic([
                "MEAS:VOLT?",
                "MEAS:VOLT:DC?",
                "READ?",
                "FETCh?",
            ])
            if not resp:
                raise RuntimeError("No response for SMU voltage measure.")
            self.meas_v_var.set(common.extract_number(resp))
            self.log(f"[SMU] Query V -> {resp}")
            common.drain_error_queue(inst, self.log, "[SMU]")
        except Exception as e:
            messagebox.showerror("SMU Query V failed", str(e))

    def measure_i(self):
        try:
            inst = self.get_inst()
            if not inst: return
            resp = self._read_generic([
                "MEAS:CURR?",
                "MEAS:CURR:DC?",
                "READ?",
                "FETCh?",
            ])
            if not resp:
                raise RuntimeError("No response for SMU current measure.")
            self.meas_i_var.set(common.extract_number(resp))
            self.log(f"[SMU] Query I -> {resp}")
            common.drain_error_queue(inst, self.log, "[SMU]")
        except Exception as e:
            messagebox.showerror("SMU Query I failed", str(e))

    def measure_vi(self):
        """Best-effort V&I simultaneous read. Sets FORM:ELEM if possible then READ?/FETCh?."""
        try:
            inst = self.get_inst()
            if not inst: return
            # Try to configure readback format to VOLT,CURR (order can vary by model)
            configured = self._try_write(inst, ["FORM:ELEM VOLT,CURR", "FORM:ELEM CURR,VOLT"])
            # Now read
            resp = self._read_generic([
                "READ?",
                "FETCh?",
                "MEAS?",
            ])
            if not resp:
                raise RuntimeError("No response for SMU V&I read.")
            # Parse first two numbers found
            nums = []
            for part in resp.replace(";", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                try:
                    nums.append(float(common.extract_number(part)))
                except Exception:
                    continue
                if len(nums) >= 2:
                    break
            v_val = ""
            i_val = ""
            # Heuristic: if we set VOLT,CURR then nums[0]=V, nums[1]=I; otherwise guess by magnitude/range is risky
            if configured and "VOLT,CURR" in ("FORM:ELEM VOLT,CURR"):
                if len(nums) >= 1: v_val = nums[0]
                if len(nums) >= 2: i_val = nums[1]
            else:
                # fallback: try to assign in usual order (CURR,VOLT) on some models
                if len(nums) >= 1: i_val = nums[0]
                if len(nums) >= 2: v_val = nums[1]
            if v_val != "": self.meas_v_var.set(str(v_val))
            if i_val != "": self.meas_i_var.set(str(i_val))

            self.log(f"[SMU] Read (V&I) -> {resp}")
            common.drain_error_queue(inst, self.log, "[SMU]")
        except Exception as e:
            messagebox.showerror("SMU Read V&I failed", str(e))
