import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class PowerSupplyTab:
    """Power Supply tab UI (per-model, single-channel control, per-channel readback).

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
      - Added a "Per-Channel Readback" panel:
          For every channel, show "Query V" / "Query I" buttons and read-only fields.
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

        # Per-channel readback store: {chan: (v_var, i_var)}
        self._per_ch_vars = {}

        # Panels that are rebuilt on model change
        self._model_info_panel = None
        self._per_ch_panel = None

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

        # Output controls
        out = ttk.LabelFrame(parent, text="Output")
        out.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Button(out, text="Output ON", command=lambda: self.output(True)).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(out, text="Output OFF", command=lambda: self.output(False)).grid(row=0, column=3, padx=6, pady=6)

        ttk.Label(out, text="State:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(out, textvariable=self.output_state_var, state="readonly", width=30).grid(
            row=0, column=1, padx=(0, 12), pady=6, sticky="w"
        )
        ttk.Button(out, text="Query State", command=self.query_output_state).grid(row=0, column=4, padx=6, pady=6)

        for c, w in enumerate([0, 1, 0, 0, 0]):
            out.grid_columnconfigure(c, weight=w)

        # Readback for selected channel
        meas = ttk.LabelFrame(parent, text="Readback (Selected Channel)")
        meas.pack(fill="x", padx=10, pady=(0, 6))
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

        # Per-Channel Readback (rebuilt per model)
        self._per_ch_panel = ttk.LabelFrame(parent, text="Per-Channel Readback")
        self._per_ch_panel.pack(fill="x", padx=10, pady=(0, 10))

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
            self._rebuild_per_channel([])
            return

        model = common.detect_psu_model(idn)
        self.model_var.set(model or "(Unknown)")
        chs = common.psu_channel_values(model)

        if not chs:
            self.channel_combo["values"] = []
            self.set_enabled(False)
            self._rebuild_model_info("(Unknown)", [])
            self._rebuild_per_channel([])
            return

        self.set_enabled(True)
        self.channel_combo["values"] = chs
        if not self.channel_var.get() or self.channel_var.get() not in chs:
            self.channel_var.set(chs[0])

        self._rebuild_model_info(model, chs)
        self._rebuild_per_channel(chs)

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
            text = "HAMEG HM8143 — channels: U1 / U2 (SU/SI, RU/RI used)."
        else:
            text = "Unknown PSU model. Generic SCPI will be used."

        ttk.Label(self._model_info_panel, text=text).pack(anchor="w")

    def _rebuild_per_channel(self, chs):
        self._clear_children(self._per_ch_panel)
        self._per_ch_vars = {}

        if not chs:
            ttk.Label(self._per_ch_panel, text="No channels.").pack(anchor="w", padx=6, pady=6)
            return

        # Table header
        hdr = ttk.Frame(self._per_ch_panel)
        hdr.pack(fill="x", padx=6, pady=(6, 2))
        ttk.Label(hdr, text="Channel", width=12).grid(row=0, column=0, sticky="w")
        ttk.Label(hdr, text="V_meas (V)", width=16).grid(row=0, column=1, sticky="w")
        ttk.Label(hdr, text="I_meas (A)", width=16).grid(row=0, column=2, sticky="w")
        ttk.Label(hdr, text="Actions").grid(row=0, column=3, sticky="w")

        # Rows
        for r, ch in enumerate(chs, start=1):
            row = ttk.Frame(self._per_ch_panel)
            row.pack(fill="x", padx=6, pady=2)

            ttk.Label(row, text=str(ch), width=12).grid(row=0, column=0, sticky="w")
            v_var = tk.StringVar(value="")
            i_var = tk.StringVar(value="")
            self._per_ch_vars[ch] = (v_var, i_var)

            ttk.Entry(row, textvariable=v_var, width=16, state="readonly").grid(row=0, column=1, sticky="w", padx=(0, 8))
            ttk.Entry(row, textvariable=i_var, width=16, state="readonly").grid(row=0, column=2, sticky="w", padx=(0, 8))

            ttk.Button(row, text="Query V", command=lambda c=ch: self._per_ch_query_v(c)).grid(row=0, column=3, padx=2)
            ttk.Button(row, text="Query I", command=lambda c=ch: self._per_ch_query_i(c)).grid(row=0, column=4, padx=2)
            ttk.Button(row, text="Query Both", command=lambda c=ch: self._per_ch_query_both(c)).grid(row=0, column=5, padx=2)

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
            inst = self._require_inst(); 
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
            inst = self._require_inst(); 
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
        try:
            inst = self._require_inst(); 
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
        try:
            inst = self._require_inst(); 
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

    # ---------- output (selected channel) ----------
    def output(self, on: bool):
        try:
            inst = self._require_inst(); 
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())
            val = "ON" if on else "OFF"

            if model == "HM8143":
                # No explicit per-channel OUTP in this generic template; try global
                sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
                common.try_sequences(inst, sequences)
            else:
                self._select_channel_if_needed(model, ch)
                sequences = [[f"OUTP {val}"], [f"OUTPut:STATe {val}"]]
                common.try_sequences(inst, sequences)

            self.log(f"[PSU] Output -> {val} on {ch} ({model})")
        except Exception as e:
            messagebox.showerror("PSU Output failed", str(e))

    def query_output_state(self):
        try:
            inst = self._require_inst(); 
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())

            if model != "HM8143":
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

    # ---------- readback (selected channel) ----------
    def measure_voltage(self):
        try:
            inst = self._require_inst(); 
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())

            if model != "HM8143":
                self._select_channel_if_needed(model, ch)

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                resp = inst.query(f"RU{idx}").strip()
            else:
                # Try typical MEAS commands
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
                self.log(f"[PSU] V_meas on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Measure Voltage failed", str(e))

    def measure_current(self):
        try:
            inst = self._require_inst(); 
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(self.channel_var.get())

            if model != "HM8143":
                self._select_channel_if_needed(model, ch)

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                resp = inst.query(f"RI{idx}").strip()
            else:
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
                self.log(f"[PSU] I_meas on {ch} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Measure Current failed", str(e))

    def measure_both(self):
        self.measure_voltage()
        self.measure_current()

    # ---------- per-channel readback (buttons for each channel) ----------
    def _per_ch_query_v(self, ch: str):
        try:
            inst = self._require_inst(); 
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                resp = inst.query(f"RU{idx}").strip()
            else:
                common.psu_select_channel(inst, model, ch)
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

            if ch in self._per_ch_vars and resp:
                v_var, _ = self._per_ch_vars[ch]
                v_var.set(common.extract_number(resp))
            self.log(f"[PSU] [Per-Channel] V_meas on {ch} -> {resp}")
        except Exception as e:
            messagebox.showerror("Per-Channel V query failed", str(e))

    def _per_ch_query_i(self, ch: str):
        try:
            inst = self._require_inst(); 
            if not inst: return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                resp = inst.query(f"RI{idx}").strip()
            else:
                common.psu_select_channel(inst, model, ch)
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

            if ch in self._per_ch_vars and resp:
                _, i_var = self._per_ch_vars[ch]
                i_var.set(common.extract_number(resp))
            self.log(f"[PSU] [Per-Channel] I_meas on {ch} -> {resp}")
        except Exception as e:
            messagebox.showerror("Per-Channel I query failed", str(e))

    def _per_ch_query_both(self, ch: str):
        self._per_ch_query_v(ch)
        self._per_ch_query_i(ch)
