import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class PowerSupplyTab:
    """Power Supply tab UI (multi-channel, per-channel panels; English-only).

    Models (detected via common.detect_psu_model):
      - E3631A (channels: P6V/P25V/N25V)
      - E3633A (channels: OUT)
      - HMP4040 (channels: 1..4)
      - HMP4030 (channels: 1..3)
      - HM8143  (channels: U1/U2)

    Design changes (per user request):
      - Remove per-channel selection UI and per-channel query buttons (Query V_meas, Query I_meas).
      - Show ALL channels at once, each in its own panel with:
          * Vset (editable), Ilimit (editable)
          * V_meas (read-only), I_meas (read-only)
          * Apply button (sets both V / I for that channel if provided)
      - Provide a single "Query Both (All Channels)" button to refresh V_meas / I_meas for every channel at once.
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

        # channels panel: constructed dynamically per model
        self.channels_container = None
        self.channel_rows = {}  # ch -> {"vset": StringVar, "iset": StringVar, "vmeas": StringVar, "imeas": StringVar}

        self._build_ui(self.frame)

    # ---------- UI ----------
    def _build_ui(self, parent):
        # Header
        header = ttk.LabelFrame(parent, text="Power Supply")
        header.pack(fill="x", padx=10, pady=(10, 6))

        ttk.Label(header, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(header, textvariable=self.model_var).grid(row=0, column=1, padx=(0, 12), pady=8, sticky="w")

        ttk.Button(header, text="Query Both (All Channels)", command=self.query_all_measured)\
            .grid(row=0, column=3, padx=6, pady=8, sticky="e")

        ttk.Button(header, text="Refresh Setpoints", command=self.query_all_setpoints)\
            .grid(row=0, column=4, padx=(0, 6), pady=8, sticky="e")

        for c, w in enumerate([0, 1, 0, 0, 0]):
            header.grid_columnconfigure(c, weight=(1 if c == 1 else 0))

        # Channels container (rebuilt on device change)
        self.channels_container = ttk.LabelFrame(parent, text="Channels")
        self.channels_container.pack(fill="x", padx=10, pady=(0, 10))

    def set_enabled(self, enabled: bool):
        try:
            self.notebook.tab(self.frame, state="normal" if enabled else "disabled")
        except Exception:
            pass

    def update_for_active_device(self):
        inst = self.get_inst()
        idn = self.get_idn()
        # Reset panel
        self._clear_children(self.channels_container)
        self.channel_rows.clear()

        if not inst or not idn:
            self.model_var.set("(No PSU)")
            self.set_enabled(False)
            return

        model = common.detect_psu_model(idn)
        chs = common.psu_channel_values(model)
        self.model_var.set(model or "(Unknown)")

        if not chs:
            self.set_enabled(False)
            return

        self.set_enabled(True)
        self._build_channel_panels(model, chs)

        # Populate with current setpoints and measured values
        self.query_all_setpoints()
        self.query_all_measured()

    # ---------- rebuilders / helpers ----------
    def _clear_children(self, widget):
        for w in list(widget.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass

    def _build_channel_panels(self, model: str, chs):
        """Create one compact panel per channel."""
        # Grid with 2 columns of panels for readability on larger screens
        cols = 2 if len(chs) > 1 else 1

        for idx, ch in enumerate(chs):
            row = idx // cols
            col = idx % cols

            lf = ttk.LabelFrame(self.channels_container, text=f"Channel {ch}")
            lf.grid(row=row, column=col, padx=6, pady=6, sticky="nsew")

            vset = tk.StringVar(value="")
            iset = tk.StringVar(value="")
            vmeas = tk.StringVar(value="")
            imeas = tk.StringVar(value="")
            self.channel_rows[ch] = {"vset": vset, "iset": iset, "vmeas": vmeas, "imeas": imeas}

            # Row 0: Vset / Ilimit / Apply
            ttk.Label(lf, text="Voltage (V):").grid(row=0, column=0, padx=6, pady=6, sticky="e")
            ttk.Entry(lf, textvariable=vset, width=10).grid(row=0, column=1, padx=(0, 12), pady=6, sticky="w")

            ttk.Label(lf, text="Current Limit (A):").grid(row=0, column=2, padx=6, pady=6, sticky="e")
            ttk.Entry(lf, textvariable=iset, width=10).grid(row=0, column=3, padx=(0, 12), pady=6, sticky="w")

            ttk.Button(lf, text="Apply", command=lambda _ch=ch: self.apply_channel(_ch))\
                .grid(row=0, column=4, padx=6, pady=6)

            # Row 1: V_meas / I_meas (read-only)
            ttk.Label(lf, text="V_meas (V):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
            ttk.Entry(lf, textvariable=vmeas, width=12, state="readonly").grid(row=1, column=1, padx=(0, 12), pady=6, sticky="w")

            ttk.Label(lf, text="I_meas (A):").grid(row=1, column=2, padx=6, pady=6, sticky="e")
            ttk.Entry(lf, textvariable=imeas, width=12, state="readonly").grid(row=1, column=3, padx=(0, 12), pady=6, sticky="w")

            for c, w in enumerate([0, 1, 0, 1, 0]):
                lf.grid_columnconfigure(c, weight=w)

        # make container stretch
        for c in range(cols):
            self.channels_container.grid_columnconfigure(c, weight=1)

    def _require_inst(self):
        inst = self.get_inst()
        if not inst:
            messagebox.showinfo("Not connected", "Activate a connected device first.")
            return None
        return inst

    # ---------- per-channel operations ----------
    def apply_channel(self, ch: str):
        """Apply Vset / Ilimit for a single channel (skip any empty fields)."""
        try:
            inst = self._require_inst()
            if not inst:
                return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)
            ch = common.trim(ch)

            row = self.channel_rows.get(ch, {})
            v_txt = (row.get("vset") or tk.StringVar()).get().strip()
            i_txt = (row.get("iset") or tk.StringVar()).get().strip()

            # We allow setting either or both; skip empty fields
            if not v_txt and not i_txt:
                messagebox.showinfo("No values", "Enter Voltage and/or Current Limit to apply.")
                return

            if model == "HM8143":
                idx = common.hm8143_ch_index(ch)
                if v_txt:
                    v = float(v_txt)
                    inst.write(f"SU{idx}:{v}")
                    self.log(f"[PSU] Set V -> {v} on {ch} ({model})")
                if i_txt:
                    i = float(i_txt)
                    inst.write(f"SI{idx}:{i}")
                    self.log(f"[PSU] Set I -> {i} on {ch} ({model})")
            else:
                # Select channel for models requiring it
                common.psu_select_channel(inst, model, ch)
                if model in ("HMP4040", "HMP4030"):
                    if v_txt:
                        v = float(v_txt)
                        inst.write(f"SOUR:VOLT {v}")
                        self.log(f"[PSU] Set V -> {v} on {ch} ({model})")
                    if i_txt:
                        i = float(i_txt)
                        inst.write(f"SOUR:CURR {i}")
                        self.log(f"[PSU] Set I -> {i} on {ch} ({model})")
                elif model in ("E3631A", "E3633A"):
                    if v_txt:
                        v = float(v_txt)
                        inst.write(f"VOLT {v}")
                        self.log(f"[PSU] Set V -> {v} on {ch} ({model})")
                    if i_txt:
                        i = float(i_txt)
                        inst.write(f"CURR {i}")
                        self.log(f"[PSU] Set I -> {i} on {ch} ({model})")

            common.drain_error_queue(inst, self.log, "[PSU]")
        except Exception as e:
            messagebox.showerror("Apply Channel failed", str(e))

    # ---------- batch queries ----------
    def query_all_setpoints(self):
        """Populate Vset / Ilimit entries for all channels."""
        try:
            inst = self._require_inst()
            if not inst:
                return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)

            for ch, row in self.channel_rows.items():
                ch_trim = common.trim(ch)
                v_resp, i_resp = None, None

                if model == "HM8143":
                    idx = common.hm8143_ch_index(ch_trim)
                    try:
                        v_resp = (inst.query(f"RU{idx}") or "").strip()
                    except Exception:
                        v_resp = ""
                    try:
                        i_resp = (inst.query(f"RI{idx}") or "").strip()
                    except Exception:
                        i_resp = ""
                else:
                    # Select channel first
                    try:
                        common.psu_select_channel(inst, model, ch_trim)
                    except Exception:
                        pass

                    if model in ("HMP4040", "HMP4030"):
                        try:
                            v_resp = (inst.query("SOUR:VOLT?") or "").strip()
                        except Exception:
                            v_resp = ""
                        try:
                            i_resp = (inst.query("SOUR:CURR?") or "").strip()
                        except Exception:
                            i_resp = ""
                    elif model in ("E3631A", "E3633A"):
                        try:
                            v_resp = (inst.query("VOLT?") or "").strip()
                        except Exception:
                            v_resp = ""
                        try:
                            i_resp = (inst.query("CURR?") or "").strip()
                        except Exception:
                            i_resp = ""

                if v_resp:
                    row["vset"].set(common.extract_number(v_resp))
                if i_resp:
                    row["iset"].set(common.extract_number(i_resp))

                self.log(f"[PSU] Query Setpoints on {ch_trim} ({model}) -> V:{v_resp} | I:{i_resp}")

            common.drain_error_queue(inst, self.log, "[PSU]")
        except Exception as e:
            messagebox.showerror("Refresh Setpoints failed", str(e))

    def query_all_measured(self):
        """Query V_meas / I_meas for all channels (replaces individual Query buttons)."""
        try:
            inst = self._require_inst()
            if not inst:
                return
            idn = self.get_idn()
            model = common.detect_psu_model(idn)

            for ch, row in self.channel_rows.items():
                ch_trim = common.trim(ch)
                v_resp, i_resp = None, None

                if model == "HM8143":
                    idx = common.hm8143_ch_index(ch_trim)
                    try:
                        v_resp = (inst.query(f"MU{idx}") or "").strip()
                    except Exception:
                        v_resp = ""
                    try:
                        i_resp = (inst.query(f"MI{idx}") or "").strip()
                    except Exception:
                        i_resp = ""
                else:
                    # Select channel first
                    try:
                        common.psu_select_channel(inst, model, ch_trim)
                    except Exception:
                        pass
                    # Try common sequences
                    v_candidates = ["MEAS:VOLT?", "MEAS:VOLT:DC?"]
                    i_candidates = ["MEAS:CURR?", "MEAS:CURR:DC?"]

                    v_resp = self._first_ok_query(inst, v_candidates)
                    i_resp = self._first_ok_query(inst, i_candidates)

                if v_resp:
                    row["vmeas"].set(common.extract_number(v_resp))
                if i_resp:
                    row["imeas"].set(common.extract_number(i_resp))

                self.log(f"[PSU] Measured on {ch_trim} ({model}) -> V:{v_resp} | I:{i_resp}")

            common.drain_error_queue(inst, self.log, "[PSU]")
        except Exception as e:
            messagebox.showerror("Query Both (All Channels) failed", str(e))

    # ---------- utilities ----------
    @staticmethod
    def _first_ok_query(inst, candidates):
        for cmd in candidates:
            try:
                r = (inst.query(cmd) or "").strip()
                if r:
                    return r
            except Exception:
                continue
        return ""
