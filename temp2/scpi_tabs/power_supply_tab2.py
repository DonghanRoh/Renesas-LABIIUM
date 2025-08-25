import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class PowerSupplyTab:
    """Power Supply tab UI + rich per-model features.

    Supported models (detected via common.detect_psu_model):
      - E3631A (channels: P6V/P25V/N25V)
      - E3633A (channels: OUT)
      - HMP4040 (channels: 1..4)
      - HMP4030 (channels: 1..3)
      - HM8143  (channels: U1/U2)

    Features:
      - HMP40x0: 멀티채널 체크박스 → 선택 채널에 동시 Set/Output ON/OFF
      - 출력 상태 조회 및 표시(단일/멀티 요약)
      - 보호 기능: OVP/OCP 설정/Enable/조회/클리어(가능한 SCPI 조합 시도)
      - Readback 측정: MEAS:VOLT?/MEAS:CURR? 등 후보 시도
      - 프리셋(1.8V/3.3V/5V/12V) 및 스텝 증감(ΔV/ΔI)
      - Local/Remote 전환(가능한 경우)
    """

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Power Supply")

        # Common state
        self.model_var = tk.StringVar(value="")
        self.channel_var = tk.StringVar(value="")
        self.voltage_var = tk.StringVar(value="")
        self.current_var = tk.StringVar(value="")

        # Output state summary text
        self.output_state_var = tk.StringVar(value="(unknown)")

        # Readback (measured) values
        self.meas_v_var = tk.StringVar(value="")
        self.meas_i_var = tk.StringVar(value="")

        # Protections
        self.ovp_level_var = tk.StringVar(value="")
        self.ovp_enable_var = tk.BooleanVar(value=False)
        self.ocp_level_var = tk.StringVar(value="")
        self.ocp_enable_var = tk.BooleanVar(value=False)

        # Step controls
        self.step_v_var = tk.StringVar(value="0.1")
        self.step_i_var = tk.StringVar(value="0.01")

        # Model-specific
        self._model_panel_container = None
        self._model_panel = None
        self._hmp_channel_vars = []  # for HMP4030/4040 multi-select

        self._build_ui(self.frame)

    # ---------- UI skeleton ----------
    def _build_ui(self, parent):
        # Header
        header = ttk.LabelFrame(parent, text="Power Supply")
        header.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(header, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(header, textvariable=self.model_var).grid(row=0, column=1, padx=(0, 12), pady=8, sticky="w")

        ttk.Label(header, text="Channel:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.channel_combo = ttk.Combobox(header, textvariable=self.channel_var, state="readonly", width=12)
        self.channel_combo.grid(row=0, column=3, padx=(0, 12), pady=8, sticky="w")

        # Model-specific panel placeholder
        self._model_panel_container = ttk.Frame(header)
        self._model_panel_container.grid(row=1, column=0, columnspan=4, sticky="we", padx=6, pady=(0, 6))

        for c, w in enumerate([0, 1, 0, 1]):
            header.grid_columnconfigure(c, weight=w)

        # Output controls
        out = ttk.LabelFrame(parent, text="Outputs")
        out.pack(fill="x", padx=10, pady=(6, 6))

        ttk.Label(out, text="Voltage (V):").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(out, textvariable=self.voltage_var, width=10).grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(out, text="Set V", command=self.set_voltage).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(out, text="Query V (Set)", command=self.query_voltage).grid(row=0, column=3, padx=6, pady=6)

        ttk.Label(out, text="Current Limit (A):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(out, textvariable=self.current_var, width=10).grid(row=1, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(out, text="Set I", command=self.set_current).grid(row=1, column=2, padx=6, pady=6)
        ttk.Button(out, text="Query I (Set)", command=self.query_current).grid(row=1, column=3, padx=6, pady=6)

        ttk.Separator(out, orient="horizontal").grid(row=2, column=0, columnspan=4, sticky="we", padx=6, pady=(6, 6))
        ttk.Button(out, text="Output ON", command=lambda: self.output(True)).grid(row=3, column=2, padx=6, pady=6)
        ttk.Button(out, text="Output OFF", command=lambda: self.output(False)).grid(row=3, column=3, padx=6, pady=6)

        # For HMP: output all ON/OFF handy buttons
        ttk.Button(out, text="[HMP] All ON", command=lambda: self.output_all(True)).grid(row=3, column=0, padx=6, pady=6, sticky="w")
        ttk.Button(out, text="[HMP] All OFF", command=lambda: self.output_all(False)).grid(row=3, column=1, padx=6, pady=6, sticky="w")

        for c, w in enumerate([0, 1, 0, 1]):
            out.grid_columnconfigure(c, weight=w)

        # Output state
        statef = ttk.LabelFrame(parent, text="Output State")
        statef.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(statef, text="State:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(statef, textvariable=self.output_state_var, state="readonly", width=50).grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")
        ttk.Button(statef, text="Query State", command=self.query_output_state).grid(row=0, column=2, padx=6, pady=6)

        # Protections (OVP/OCP)
        prot = ttk.LabelFrame(parent, text="Protections (OVP / OCP)")
        prot.pack(fill="x", padx=10, pady=(0, 6))

        # OVP
        ttk.Label(prot, text="OVP Level (V):").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(prot, textvariable=self.ovp_level_var, width=10).grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Checkbutton(prot, text="Enable OVP", variable=self.ovp_enable_var, command=self.toggle_ovp).grid(row=0, column=2, padx=6, pady=6, sticky="w")
        ttk.Button(prot, text="Set OVP", command=self.set_ovp).grid(row=0, column=3, padx=6, pady=6)
        ttk.Button(prot, text="Query OVP", command=self.query_ovp).grid(row=0, column=4, padx=6, pady=6)
        ttk.Button(prot, text="Clear OVP", command=self.clear_ovp).grid(row=0, column=5, padx=6, pady=6)

        # OCP
        ttk.Label(prot, text="OCP Level (A):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(prot, textvariable=self.ocp_level_var, width=10).grid(row=1, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Checkbutton(prot, text="Enable OCP", variable=self.ocp_enable_var, command=self.toggle_ocp).grid(row=1, column=2, padx=6, pady=6, sticky="w")
        ttk.Button(prot, text="Set OCP", command=self.set_ocp).grid(row=1, column=3, padx=6, pady=6)
        ttk.Button(prot, text="Query OCP", command=self.query_ocp).grid(row=1, column=4, padx=6, pady=6)
        ttk.Button(prot, text="Clear OCP", command=self.clear_ocp).grid(row=1, column=5, padx=6, pady=6)

        for c, w in enumerate([0, 1, 0, 0, 0, 0]):
            prot.grid_columnconfigure(c, weight=w)

        # Readback measure
        meas = ttk.LabelFrame(parent, text="Readback (MEAS)")
        meas.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(meas, text="V_meas (V):").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(meas, textvariable=self.meas_v_var, width=12, state="readonly").grid(row=0, column=1, padx=(0,12), pady=6, sticky="w")
        ttk.Button(meas, text="Query V_meas", command=self.measure_voltage).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(meas, text="I_meas (A):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(meas, textvariable=self.meas_i_var, width=12, state="readonly").grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")
        ttk.Button(meas, text="Query I_meas", command=self.measure_current).grid(row=1, column=2, padx=6, pady=6)

        ttk.Button(meas, text="Query Both", command=self.measure_both).grid(row=0, column=3, rowspan=2, padx=6, pady=6, sticky="ns")

        for c, w in enumerate([0, 1, 0, 0]):
            meas.grid_columnconfigure(c, weight=w)

        # Presets & Step
        pres = ttk.LabelFrame(parent, text="Presets & Step")
        pres.pack(fill="x", padx=10, pady=(0, 10))

        # Presets
        ttk.Label(pres, text="Quick Presets (V):").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Button(pres, text="1.8V", command=lambda: self._apply_preset_v(1.8)).grid(row=0, column=1, padx=4, pady=6)
        ttk.Button(pres, text="3.3V", command=lambda: self._apply_preset_v(3.3)).grid(row=0, column=2, padx=4, pady=6)
        ttk.Button(pres, text="5V",   command=lambda: self._apply_preset_v(5.0)).grid(row=0, column=3, padx=4, pady=6)
        ttk.Button(pres, text="12V",  command=lambda: self._apply_preset_v(12.0)).grid(row=0, column=4, padx=4, pady=6)

        # Step controls
        ttk.Label(pres, text="ΔV:").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(pres, textvariable=self.step_v_var, width=8).grid(row=1, column=1, padx=(0, 6), pady=6, sticky="w")
        ttk.Button(pres, text="+V", command=lambda: self._nudge_value(self.voltage_var, self.step_v_var, True, self.set_voltage)).grid(row=1, column=2, padx=4, pady=6)
        ttk.Button(pres, text="-V", command=lambda: self._nudge_value(self.voltage_var, self.step_v_var, False, self.set_voltage)).grid(row=1, column=3, padx=4, pady=6)

        ttk.Label(pres, text="ΔI:").grid(row=1, column=4, padx=6, pady=6, sticky="e")
        ttk.Entry(pres, textvariable=self.step_i_var, width=8).grid(row=1, column=5, padx=(0, 6), pady=6, sticky="w")
        ttk.Button(pres, text="+I", command=lambda: self._nudge_value(self.current_var, self.step_i_var, True, self.set_current)).grid(row=1, column=6, padx=4, pady=6)
        ttk.Button(pres, text="-I", command=lambda: self._nudge_value(self.current_var, self.step_i_var, False, self.set_current)).grid(row=1, column=7, padx=4, pady=6)

        for c, w in enumerate([0, 0, 0, 0, 0, 0, 0, 1]):
            pres.grid_columnconfigure(c, weight=w)

        # System
        sysf = ttk.LabelFrame(parent, text="System")
        sysf.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(sysf, text="Remote", command=self.to_remote).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(sysf, text="Local",  command=self.to_local).grid(row=0, column=1, padx=6, pady=6)

    # ---------- lifecycle ----------
    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state="normal" if enabled else "disabled")
        except Exception:
            pass

    def update_for_active_device(self):
        inst = self.get_inst()
        idn = self.get_idn()
        if not inst or not idn:
            self.model_var.set("(No PSU)")
            self.channel_combo["values"] = []
            self.set_enabled(False)
            self._destroy_model_panel()
            return

        model = common.detect_psu_model(idn)
        self.model_var.set(model or "(Unknown)")
        chs = common.psu_channel_values(model)

        if not chs:
            self.channel_combo["values"] = []
            self.set_enabled(False)
            self._destroy_model_panel()
            return

        self.set_enabled(True)
        self.channel_combo["values"] = chs
        if len(chs) == 1:
            self.channel_combo.configure(state="disabled")
            self.channel_var.set(chs[0])
        else:
            self.channel_combo.configure(state="readonly")
            if not self.channel_var.get() or self.channel_var.get() not in chs:
                self.channel_var.set(chs[0])

        self._build_model_panel(model)
        self.output_state_var.set("(unknown)")
        self.meas_v_var.set("")
        self.meas_i_var.set("")

    # ---------- model panel builders ----------
    def _destroy_model_panel(self):
        self._hmp_channel_vars = []
        if self._model_panel is not None:
            try:
                self._model_panel.destroy()
            except Exception:
                pass
            self._model_panel = None

    def _build_model_panel(self, model: str):
        self._destroy_model_panel()
        pnl = ttk.Frame(self._model_panel_container)
        self._model_panel = pnl

        if model in ("HMP4040", "HMP4030"):
            ttk.Label(pnl, text="HMP multi-channel: 선택 채널에 동시 적용(Set/Output)").grid(
                row=0, column=0, columnspan=8, sticky="w", padx=4, pady=(2, 4)
            )
            chs = common.psu_channel_values(model)
            self._hmp_channel_vars = []
            for i, ch in enumerate(chs):
                var = tk.BooleanVar(value=False)
                self._hmp_channel_vars.append((ch, var))
                cb = ttk.Checkbutton(pnl, text=f"CH{ch}", variable=var)
                cb.grid(row=1, column=i, padx=4, pady=2, sticky="w")
            tip = ("Tip: 체크박스를 선택하지 않으면 상단 'Channel'의 단일 채널로 동작합니다.")
            ttk.Label(pnl, text=tip, foreground="#666").grid(row=2, column=0, columnspan=8, sticky="w", padx=4, pady=(2, 2))
            for c in range(8):
                pnl.grid_columnconfigure(c, weight=0)

        elif model == "E3631A":
            ttk.Label(pnl, text="Keysight E3631A channels: P6V / P25V / N25V").grid(
                row=0, column=0, sticky="w", padx=4, pady=(2, 2)
            )
        elif model == "E3633A":
            ttk.Label(pnl, text="Keysight E3633A single output: OUT").grid(
                row=0, column=0, sticky="w", padx=4, pady=(2, 2)
            )
        elif model == "HM8143":
            ttk.Label(pnl, text="HAMEG HM8143 channels: U1 / U2 (SU/SI, RU/RI 사용)").grid(
                row=0, column=0, sticky="w", padx=4, pady=(2, 2)
            )
        else:
            ttk.Label(pnl, text="Unknown PSU model detected. Using generic controls.").grid(
                row=0, column=0, sticky="w", padx=4, pady=(2, 2)
            )

        pnl.pack(fill="x", expand=False)

    # ---------- helpers ----------
    def _selected_hmp_channels(self):
        if not self._hmp_channel_vars:
            return []
        return [ch for ch, var in self._hmp_channel_vars if var.get()]

    def _apply_to_channels(self, model: str, channels, setter_fn):
        inst = self.get_inst()
        for ch in channels:
            if model in ("HMP4040", "HMP4030"):
                common.psu_select_channel(inst, model, ch)
                setter_fn(inst, model, ch)
            elif model == "HM8143":
                setter_fn(inst, model, ch)
            else:
                common.psu_select_channel(inst, model, ch)
                setter_fn(inst, model, ch)

    def _parse_onoff(self, s: str) -> str:
        s = (s or "").strip().upper()
        if s in ("1", "ON", "ON,ON", "ON,1"):  # vendor differences
            return "ON"
        if s in ("0", "OFF", "OFF,OFF", "OFF,0"):
            return "OFF"
        return s or "(unknown)"

    def _agg_states_text(self, mapping):
        # mapping: {channel: "ON"/"OFF"/"..."}
        items = [f"{k}:{v}" for k, v in mapping.items()]
        return ", ".join(items) if items else "(none)"

    def _nudge_value(self, target_var: tk.StringVar, step_var: tk.StringVar, up: bool, apply_fn):
        try:
            cur = float((target_var.get() or "0").strip())
            step = float((step_var.get() or "0").strip())
            newv = cur + (step if up else -step)
            target_var.set(f"{newv}")
            apply_fn()
        except Exception as e:
            messagebox.showerror("Step apply failed", str(e))

    def _apply_preset_v(self, v: float):
        self.voltage_var.set(f"{v}")
        self.set_voltage()

    # ---------- operations: set/query setpoints ----------
    def set_voltage(self):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            v = float(self.voltage_var.get())

            if model in ("HMP4040", "HMP4030"):
                channels = self._selected_hmp_channels() or [common.trim(self.channel_var.get())]
            else:
                channels = [common.trim(self.channel_var.get())]

            def _setter(_inst, _model, ch):
                if _model == "HM8143":
                    idx = common.hm8143_ch_index(ch)
                    _inst.write(f"SU{idx}:{v}")
                elif _model in ("HMP4040", "HMP4030"):
                    _inst.write(f"SOUR:VOLT {v}")
                elif _model in ("E3631A", "E3633A"):
                    _inst.write(f"VOLT {v}")

            self._apply_to_channels(model, channels, _setter)
            self.log(f"[PSU] Set V -> {v} on {','.join(channels)} ({model})")
        except Exception as e:
            messagebox.showerror("Set Voltage failed", str(e))

    def set_current(self):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            i = float(self.current_var.get())

            if model in ("HMP4040", "HMP4030"):
                channels = self._selected_hmp_channels() or [common.trim(self.channel_var.get())]
            else:
                channels = [common.trim(self.channel_var.get())]

            def _setter(_inst, _model, ch):
                if _model == "HM8143":
                    idx = common.hm8143_ch_index(ch)
                    _inst.write(f"SI{idx}:{i}")
                elif _model in ("HMP4040", "HMP4030"):
                    _inst.write(f"SOUR:CURR {i}")
                elif _model in ("E3631A", "E3633A"):
                    _inst.write(f"CURR {i}")

            self._apply_to_channels(model, channels, _setter)
            self.log(f"[PSU] Set I -> {i} on {','.join(channels)} ({model})")
        except Exception as e:
            messagebox.showerror("Set Current failed", str(e))

    def query_voltage(self):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                resp = inst.query(f"RU{idx}").strip()
            else:
                common.psu_select_channel(inst, model, ch)
                if model in ("HMP4040", "HMP4030"):
                    resp = inst.query("SOUR:VOLT?").strip()
                elif model in ("E3631A", "E3633A"):
                    resp = inst.query("VOLT?").strip()

            self.voltage_var.set(common.extract_number(resp))
            self.log(f"[PSU] Query V(set) on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Voltage failed", str(e))

    def query_current(self):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                resp = inst.query(f"RI{idx}").strip()
            else:
                common.psu_select_channel(inst, model, ch)
                if model in ("HMP4040", "HMP4030"):
                    resp = inst.query("SOUR:CURR?").strip()
                elif model in ("E3631A", "E3633A"):
                    resp = inst.query("CURR?").strip()

            self.current_var.set(common.extract_number(resp))
            self.log(f"[PSU] Query I(set) on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Current failed", str(e))

    # ---------- operations: output ----------
    def output(self, on: bool):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            val = "ON" if on else "OFF"

            if model in ("HMP4040", "HMP4030"):
                channels = self._selected_hmp_channels() or [common.trim(self.channel_var.get())]

                def _setter(_inst, _model, ch):
                    common.psu_select_channel(_inst, _model, ch)
                    sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
                    common.try_sequences(_inst, sequences)

                self._apply_to_channels(model, channels, _setter)
                self.log(f"[PSU] Output -> {val} on {','.join(channels)} ({model})")
            elif model == "HM8143":
                sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
                common.try_sequences(inst, sequences)
                self.log(f"[PSU] Output -> {val} ({model})")
            else:
                sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
                common.try_sequences(inst, sequences)
                self.log(f"[PSU] Output -> {val} ({model})")
        except Exception as e:
            messagebox.showerror("PSU Output failed", str(e))

    def output_all(self, on: bool):
        """HMP 전용 편의 기능: 모든 채널 일괄 ON/OFF"""
        try:
            inst = self.get_inst(); idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            if model not in ("HMP4040", "HMP4030"):
                messagebox.showinfo("Not HMP", "이 기능은 HMP4030/4040에서만 지원됩니다.")
                return
            val = "ON" if on else "OFF"
            for ch in common.psu_channel_values(model):
                common.psu_select_channel(inst, model, ch)
                sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
                common.try_sequences(inst, sequences)
            self.log(f"[PSU] Output ALL -> {val} ({model})")
        except Exception as e:
            messagebox.showerror("PSU Output(All) failed", str(e))

    def query_output_state(self):
        """단일 채널 또는 HMP 멀티 선택 채널의 출력 상태를 조회하여 요약 표시."""
        try:
            inst = self.get_inst(); idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)

            result = {}
            if model in ("HMP4040", "HMP4030"):
                channels = self._selected_hmp_channels() or [common.trim(self.channel_var.get())]
                for ch in channels:
                    common.psu_select_channel(inst, model, ch)
                    candidates = ["OUTP?", "OUTPut:STATe?"]
                    resp = None
                    for cmd in candidates:
                        try:
                            resp = (inst.query(cmd) or "").strip()
                            if resp:
                                break
                        except Exception:
                            continue
                    result[ch] = self._parse_onoff(resp)
            elif model == "HM8143":
                # 베ンダ 전용 명령이 다를 수 있어 Generic 시도
                candidates = ["OUTP?", "OUTPut:STATe?"]
                resp = None
                for cmd in candidates:
                    try:
                        r = (inst.query(cmd) or "").strip()
                        if r:
                            resp = r
                            break
                    except Exception:
                        continue
                result["ALL"] = self._parse_onoff(resp)
            else:
                candidates = ["OUTP?", "OUTPut:STATe?"]
                resp = None
                for cmd in candidates:
                    try:
                        r = (inst.query(cmd) or "").strip()
                        if r:
                            resp = r
                            break
                    except Exception:
                        continue
                result["OUT"] = self._parse_onoff(resp)

            self.output_state_var.set(self._agg_states_text(result))
            self.log(f"[PSU] Output State -> {self.output_state_var.get()}")
        except Exception as e:
            messagebox.showerror("Query Output State failed", str(e))

    # ---------- operations: protections ----------
    def set_ovp(self):
        try:
            inst = self.get_inst()
            if not inst: return
            v = float(self.ovp_level_var.get())
            sequences = [
                [f"VOLT:PROT {v}"],
                [f"VOLTage:PROTection {v}"],
                [f"VOLTage:PROTection:LEVel {v}"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[PSU/OVP]")
            self.log(f"[PSU] OVP level set -> {v}")
        except Exception as e:
            messagebox.showerror("Set OVP failed", str(e))

    def query_ovp(self):
        try:
            inst = self.get_inst()
            if not inst: return
            # Query level (우선)
            candidates = ["VOLT:PROT?", "VOLTage:PROTection?", "VOLTage:PROTection:LEVel?"]
            resp = None
            for c in candidates:
                try:
                    r = (inst.query(c) or "").strip()
                    if r:
                        resp = r
                        break
                except Exception:
                    continue
            if resp:
                self.ovp_level_var.set(common.extract_number(resp))
                self.log(f"[PSU] OVP level? -> {resp}")

            # Query enable 상태
            candidates_en = ["VOLT:PROT:STAT?", "VOLTage:PROTection:STATe?"]
            resp_en = None
            for c in candidates_en:
                try:
                    r = (inst.query(c) or "").strip()
                    if r:
                        resp_en = r
                        break
                except Exception:
                    continue
            if resp_en:
                self.ovp_enable_var.set(self._parse_onoff(resp_en) == "ON")
                self.log(f"[PSU] OVP enable? -> {resp_en}")

            common.drain_error_queue(inst, self.log, "[PSU/OVP]")
        except Exception as e:
            messagebox.showerror("Query OVP failed", str(e))

    def toggle_ovp(self):
        try:
            inst = self.get_inst()
            if not inst: return
            val = "ON" if self.ovp_enable_var.get() else "OFF"
            sequences = [
                [f"VOLT:PROT:STAT {val}"],
                [f"VOLTage:PROTection:STATe {val}"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[PSU/OVP]")
            self.log(f"[PSU] OVP enable -> {val}")
        except Exception as e:
            messagebox.showerror("Toggle OVP failed", str(e))

    def clear_ovp(self):
        try:
            inst = self.get_inst()
            if not inst: return
            sequences = [
                ["VOLT:PROT:CLE"],
                ["VOLTage:PROTection:CLEar"],
                ["OUTP:PROT:CLE"],     # 일부 장비 호환
                ["OUTPut:PROTection:CLEar"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[PSU/OVP]")
            self.log("[PSU] OVP cleared")
        except Exception as e:
            messagebox.showerror("Clear OVP failed", str(e))

    def set_ocp(self):
        try:
            inst = self.get_inst()
            if not inst: return
            i = float(self.ocp_level_var.get())
            sequences = [
                [f"CURR:PROT {i}"],
                [f"CURRent:PROTection {i}"],
                [f"CURRent:PROTection:LEVel {i}"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[PSU/OCP]")
            self.log(f"[PSU] OCP level set -> {i}")
        except Exception as e:
            messagebox.showerror("Set OCP failed", str(e))

    def query_ocp(self):
        try:
            inst = self.get_inst()
            if not inst: return
            # Level
            candidates = ["CURR:PROT?", "CURRent:PROTection?", "CURRent:PROTection:LEVel?"]
            resp = None
            for c in candidates:
                try:
                    r = (inst.query(c) or "").strip()
                    if r:
                        resp = r
                        break
                except Exception:
                    continue
            if resp:
                self.ocp_level_var.set(common.extract_number(resp))
                self.log(f"[PSU] OCP level? -> {resp}")

            # Enable state
            candidates_en = ["CURR:PROT:STAT?", "CURRent:PROTection:STATe?"]
            resp_en = None
            for c in candidates_en:
                try:
                    r = (inst.query(c) or "").strip()
                    if r:
                        resp_en = r
                        break
                except Exception:
                    continue
            if resp_en:
                self.ocp_enable_var.set(self._parse_onoff(resp_en) == "ON")
                self.log(f"[PSU] OCP enable? -> {resp_en}")

            common.drain_error_queue(inst, self.log, "[PSU/OCP]")
        except Exception as e:
            messagebox.showerror("Query OCP failed", str(e))

    def toggle_ocp(self):
        try:
            inst = self.get_inst()
            if not inst: return
            val = "ON" if self.ocp_enable_var.get() else "OFF"
            sequences = [
                [f"CURR:PROT:STAT {val}"],
                [f"CURRent:PROTection:STATe {val}"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[PSU/OCP]")
            self.log(f"[PSU] OCP enable -> {val}")
        except Exception as e:
            messagebox.showerror("Toggle OCP failed", str(e))

    def clear_ocp(self):
        try:
            inst = self.get_inst()
            if not inst: return
            sequences = [
                ["CURR:PROT:CLE"],
                ["CURRent:PROTection:CLEar"],
                ["OUTP:PROT:CLE"],     # 일부 장비 호환
                ["OUTPut:PROTection:CLEar"],
            ]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[PSU/OCP]")
            self.log("[PSU] OCP cleared")
        except Exception as e:
            messagebox.showerror("Clear OCP failed", str(e))

    # ---------- operations: readback ----------
    def measure_voltage(self):
        try:
            inst = self.get_inst(); idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)

            # 채널 지정 필요 시 선택
            if model not in ("HM8143",):
                common.psu_select_channel(inst, model, common.trim(self.channel_var.get()))

            candidates = ["MEAS:VOLT?", "MEAS:VOLT:DC?"]
            resp = None
            for c in candidates:
                try:
                    r = (inst.query(c) or "").strip()
                    if r:
                        resp = r
                        break
                except Exception:
                    continue
            if resp:
                self.meas_v_var.set(common.extract_number(resp))
                self.log(f"[PSU] MEAS:VOLT? -> {resp}")
            common.drain_error_queue(inst, self.log, "[PSU/MEAS]")
        except Exception as e:
            messagebox.showerror("Measure Voltage failed", str(e))

    def measure_current(self):
        try:
            inst = self.get_inst(); idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)

            if model not in ("HM8143",):
                common.psu_select_channel(inst, model, common.trim(self.channel_var.get()))

            candidates = ["MEAS:CURR?", "MEAS:CURR:DC?"]
            resp = None
            for c in candidates:
                try:
                    r = (inst.query(c) or "").strip()
                    if r:
                        resp = r
                        break
                except Exception:
                    continue
            if resp:
                self.meas_i_var.set(common.extract_number(resp))
                self.log(f"[PSU] MEAS:CURR? -> {resp}")
            common.drain_error_queue(inst, self.log, "[PSU/MEAS]")
        except Exception as e:
            messagebox.showerror("Measure Current failed", str(e))

    def measure_both(self):
        self.measure_voltage()
        self.measure_current()

    # ---------- operations: system ----------
    def to_remote(self):
        try:
            inst = self.get_inst()
            if not inst: return
            sequences = [["SYST:REM"], ["SYSTem:REMote"]]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[PSU/SYS]")
            self.log("[PSU] System -> REMOTE")
        except Exception as e:
            messagebox.showerror("Set Remote failed", str(e))

    def to_local(self):
        try:
            inst = self.get_inst()
            if not inst: return
            sequences = [["SYST:LOC"], ["SYSTem:LOCal"]]
            common.try_sequences(inst, sequences)
            common.drain_error_queue(inst, self.log, "[PSU/SYS]")
            self.log("[PSU] System -> LOCAL")
        except Exception as e:
            messagebox.showerror("Set Local failed", str(e))
