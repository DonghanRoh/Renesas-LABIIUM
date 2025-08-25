import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class PowerSupplyTab:
    """Power Supply tab UI (single-channel control; English-only).

    Models (detected via common.detect_psu_model):
      - E3631A (channels: P6V/P25V/N25V)
      - E3633A (channels: OUT)
      - HMP4040 (channels: 1..4)
      - HMP4030 (channels: 1..3)
      - HM8143  (channels: U1/U2)

    Design:
      - All controls act on exactly ONE active channel (selected in the Channel combobox).
      - Protection features removed (no OVP/OCP).
      - No "All ON / All OFF".
      - English-only UI text.
      - Readback panel shows V/I for the selected channel only.
      - HM8143 specifics:
          * Output ON/OFF uses OP1 / OP0 (global for the supply).
          * Query State uses STA (text status).
          * Actual (measured) values use MUx / MIx; RUx / RIx are used only for setpoints.
    """

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Power Supply")

        # State
        self.model_var = tk.StringVar(value="")
        self.channel_var = tk.StringVar(value="")

        self.voltage_var = tk.StringVar(value="")
        self.current_var = tk.StringVar(value="")

        self.output_state_var = tk.StringVar(value="(unknown)")

        self.meas_v_var = tk.StringVar(value="")
        self.meas_i_var = tk.StringVar(value="")

        # Panel rebuilt on model change
        self._model_info_panel = None

        self._build_ui(self.frame)

    # ---------- UI ----------
    def _build_ui(self, parent):
        # Header
        header = ttk.LabelFrame(parent, text="Power Supply")
        header.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(header, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(header, textvariable=self.model_var).grid(row=0, column=1, padx=(0, 12), pady=8, sticky="w")

        ttk.Label(header, text="Channel:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.channel_combo = ttk.Combobox(header, textvariable=self.channel_var, state="readonly", width=12)
        self.channel_combo.grid(row=0, column=3, padx=(0, 12), pady=8, sticky="w")

        # Model info (rebuilt on update_for_active_device)
        self._model_info_panel = ttk.Frame(header)
        self._model_info_panel.grid(row=1, column=0, columnspan=4, sticky="we", padx=6, pady=(0, 6))

        for c, w in enumerate([0, 1, 0, 1]):
            header.grid_columnconfigure(c, weight=w)

        # Setpoint controls
        sp = ttk.LabelFrame(parent, text="Setpoints")
        sp.pack(fill="x", padx=10, pady=(6, 6))

        ttk.Label(sp, text="Voltage (V):").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(sp, textvariable=self.voltage_var, width=10).grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(sp, text="Set V", command=self.set_voltage).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(sp, text="Query V (Set)", command=self.query_voltage).grid(row=0, column=3, padx=6, pady=6)

        ttk.Label(sp, text="Current Limit (A):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(sp, textvariable=self.current_var, width=10).grid(row=1, column=1, padx=(0, 12), pady=6, sticky="w")
        ttk.Button(sp, text="Set I", command=self.set_current).grid(row=1, column=2, padx=6, pady=6)
        ttk.Button(sp, text="Query I (Set)", command=self.query_current).grid(row=1, column=3, padx=6, pady=6)

        for c, w in enumerate([0, 1, 0, 1]):
            sp.grid_columnconfigure(c, weight=w)

        # Output controls (single channel UI; HM8143 uses global OP1/OP0 internally)
        out = ttk.LabelFrame(parent, text="Output")
        out.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Button(out, text="Output ON", command=lambda: self.output(True)).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(out, text="Output OFF", command=lambda: self.output(False)).grid(row=0, column=3, padx=6, pady=6)

        ttk.Label(out, text="State:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(out, textvariable=self.output_state_var, state="readonly", width=40).grid(
            row=0, column=1, padx=(0, 12), pady=6, sticky="w"
        )
        ttk.Button(out, text="Query State", command=self.query_output_state).grid(row=0, column=4, padx=6, pady=6)

        for c, w in enumerate([0, 1, 0, 0, 0]):
            out.grid_columnconfigure(c, weight=w)

        # Readback for selected channel
        meas = ttk.LabelFrame(parent, text="Readback (Selected Channel)")
        meas.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(meas, text="V_meas (V):").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(meas, textvariable=self.meas_v_var, width=12, state="readonly").grid(
            row=0, column=1, padx=(0, 12), pady=6, sticky="w"
        )
        ttk.Button(meas, text="Query V_meas", command=self.measure_voltage).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(meas, text="I_meas (A):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(meas, textvariable=self.meas_i_var, width=12, state="readonly").grid(
            row=1, column=1, padx=(0, 12), pady=6, sticky="w"
        )
        ttk.Button(meas, text="Query I_meas", command=self.measure_current).grid(row=1, column=2, padx=6, pady=6)

        ttk.Button(meas, text="Query Both", command=self.measure_both).grid(row=0, column=3, rowspan=2, padx=6, pady=6, sticky="ns")

        for c, w in enumerate([0, 1, 0, 0]):
            meas.grid_columnconfigure(c, weight=w)

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
            self._rebuild_model_info("(Unknown)", [])
            # reset readbacks
            self.output_state_var.set("(unknown)")
            self.meas_v_var.set("")
            self.meas_i_var.set("")
            return

        model = common.detect_psu_model(idn)
        self.model_var.set(model or "(Unknown)")
        chs = common.psu_channel_values(model)

        if not chs:
            self.channel_combo["values"] = []
            self.set_enabled(False)
            self._rebuild_model_info("(Unknown)", [])
            self.output_state_var.set("(unknown)")
            self.meas_v_var.set("")
            self.meas_i_var.set("")
            return

        self.set_enabled(True)
        self.channel_combo["values"] = chs
        if not self.channel_var.get() or self.channel_var.get() not in chs:
            self.channel_var.set(chs[0])

        self._rebuild_model_info(model, chs)

        # reset readbacks
        self.output_state_var.set("(unknown)")
        self.meas_v_var.set("")
        self.meas_i_var.set("")

    # ---------- rebuilders ----------
    def _clear_children(self, widget):
        for w in list(widget.winfo_children()):
            try: w.destroy()
            except Exception: pass

    def _rebuild_model_info(self, model: str, chs):
        if self._model_info_panel is None:
            return
        self._clear_children(self._model_info_panel)

        text = ""
        if model in ("HMP4040", "HMP4030"):
            text = f"R&S {model} — select a single channel above to control."
        elif model == "E3631A":
            text = "Keysight E3631A — channels: P6V / P25V / N25V."
        elif model == "E3633A":
            text = "Keysight E3633A — single output: OUT."
        elif model == "HM8143":
            text = "HAMEG HM8143 — channels: U1 / U2. Output ON/OFF is global (OP1/OP0)."
        else:
            text = "Unknown PSU model. Generic SCPI will be used."

        ttk.Label(self._model_info_panel, text=text).pack(anchor="w")

    # ---------- helpers ----------
    def _require_inst(self):
        inst = self.get_inst()
        if not inst:
            messagebox.showinfo("Not connected", "Activate a connected device first.")
            return None
        return inst

    def _select_channel_if_needed(self, model: str, ch: str):
        """Select channel for models that need explicit selection (not HM8143)."""
        if model != "HM8143":
            common.psu_select_channel(self.get_inst(), model, ch)

    def _parse_onoff(self, s: str) -> str:
        s = (s or "").strip().upper()
        if s in ("1", "ON", "ON,ON", "ON,1"):
            return "ON"
        if s in ("0", "OFF", "OFF,OFF", "OFF,0"):
            return "OFF"
        return s or "(unknown)"

    # ---------- set/query setpoints (selected channel) ----------
    def set_voltage(self):
        try:
            inst = self._require_inst()
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())
            v = float(self.voltage_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                inst.write(f"SU{idx}:{v}")
            else:
                self._select_channel_if_needed(model, ch)
                if model in ("HMP4040", "HMP4030"):
                    inst.write(f"SOUR:VOLT {v}")
                elif model in ("E3631A", "E3633A"):
                    inst.write(f"VOLT {v}")
            self.log(f"[PSU] Set V -> {v} on {ch} ({model})")
        except Exception as e:
            messagebox.showerror("Set Voltage failed", str(e))

    def set_current(self):
        try:
            inst = self._require_inst()
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())
            i = float(self.current_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                inst.write(f"SI{idx}:{i}")
            else:
                self._select_channel_if_needed(model, ch)
                if model in ("HMP4040", "HMP4030"):
                    inst.write(f"SOUR:CURR {i}")
                elif model in ("E3631A", "E3633A"):
                    inst.write(f"CURR {i}")
            self.log(f"[PSU] Set I -> {i} on {ch} ({model})")
        except Exception as e:
            messagebox.showerror("Set Current failed", str(e))

    def query_voltage(self):
        """Query set VOLT (not measured value)."""
        try:
            inst = self._require_inst()
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                resp = inst.query(f"RU{idx}").strip()
            else:
                self._select_channel_if_needed(model, ch)
                if model in ("HMP4040", "HMP4030"):
                    resp = inst.query("SOUR:VOLT?").strip()
                elif model in ("E3631A", "E3633A"):
                    resp = inst.query("VOLT?").strip()

            self.voltage_var.set(common.extract_number(resp))
            self.log(f"[PSU] Query V(set) on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Voltage failed", str(e))

    def query_current(self):
        """Query set CURR limit (not measured value)."""
        try:
            inst = self._require_inst()
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                resp = inst.query(f"RI{idx}").strip()
            else:
                self._select_channel_if_needed(model, ch)
                if model in ("HMP4040", "HMP4030"):
                    resp = inst.query("SOUR:CURR?").strip()
                elif model in ("E3631A", "E3633A"):
                    resp = inst.query("CURR?").strip()

            self.current_var.set(common.extract_number(resp))
            self.log(f"[PSU] Query I(set) on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Current failed", str(e))

    # ---------- output ----------
    def output(self, on: bool):
        try:
            inst = self._require_inst()
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())
            val = "ON" if on else "OFF"

            if model == "HM8143":
                # HM8143 uses OP1 / OP0 (global) rather than OUTP per-channel.
                cmd = "OP1" if on else "OP0"
                inst.write(cmd)
            else:
                self._select_channel_if_needed(model, ch)
                # Generic OUTP sequence
                sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
                common.try_sequences(inst, sequences)

            self.log(f"[PSU] Output -> {val} on {ch} ({model})")
        except Exception as e:
            messagebox.showerror("PSU Output failed", str(e))

    def query_output_state(self):
        try:
            inst = self._require_inst()
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())

            if model == "HM8143":
                # 'STA' returns a text like: OP1 CV1 CC2 RM1 (or OP0 --- --- RM1)  ➜ show raw.
                resp = (inst.query("STA") or "").strip()
                self.output_state_var.set(resp or "(unknown)")
                self.log(f"[PSU] State ({model}) -> {resp}")
                return

            # Others: query ON/OFF
            self._select_channel_if_needed(model, ch)
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
            self.output_state_var.set(self._parse_onoff(resp))
            self.log(f"[PSU] Output State on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Output State failed", str(e))

    # ---------- readback (selected channel; actual values) ----------
    def measure_voltage(self):
        try:
            inst = self._require_inst()
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())
            resp = None

            if model == "HM8143":
                # MUx = measured (actual) voltage
                idx = common.hm8143_ch_index(ch)
                resp = (inst.query(f"MU{idx}") or "").strip()
            else:
                self._select_channel_if_needed(model, ch)
                for c in ["MEAS:VOLT?", "MEAS:VOLT:DC?"]:
                    try:
                        r = (inst.query(c) or "").strip()
                        if r:
                            resp = r
                            break
                    except Exception:
                        continue

            if resp:
                self.meas_v_var.set(common.extract_number(resp))
            self.log(f"[PSU] V_meas on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Measure Voltage failed", str(e))

    def measure_current(self):
        try:
            inst = self._require_inst()
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())
            resp = None

            if model == "HM8143":
                # MIx = measured (actual) current
                idx = common.hm8143_ch_index(ch)
                resp = (inst.query(f"MI{idx}") or "").strip()
            else:
                self._select_channel_if_needed(model, ch)
                for c in ["MEAS:CURR?", "MEAS:CURR:DC?"]:
                    try:
                        r = (inst.query(c) or "").strip()
                        if r:
                            resp = r
                            break
                    except Exception:
                        continue

            if resp:
                self.meas_i_var.set(common.extract_number(resp))
            self.log(f"[PSU] I_meas on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Measure Current failed", str(e))

    def measure_both(self):
        self.measure_voltage()
        self.measure_current()
