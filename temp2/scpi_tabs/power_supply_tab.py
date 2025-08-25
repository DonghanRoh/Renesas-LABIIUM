# scpi_tabs/power_supply_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common

class PowerSupplyTab:
    """Power Supply tab UI + basic SCPI ops.
    IDNs: E3631A (P6V/P25V/N25V), E3633A (OUT), HMP4040 (1..4), HMP4030 (1..3), HM8143 (U1/U2)
    """

    def __init__(self, notebook: ttk.Notebook, get_inst, get_idn, log_fn, status_var: tk.StringVar):
        self.notebook = notebook
        self.get_inst = get_inst
        self.get_idn = get_idn
        self.log = log_fn
        self.status = status_var

        self.frame = ttk.Frame(self.notebook)
        self.notebook.add(self.frame, text="Power Supply")

        self.model_var = tk.StringVar(value="")
        self.channel_var = tk.StringVar(value="")
        self.voltage_var = tk.StringVar(value="")
        self.current_var = tk.StringVar(value="")
        self._build_ui(self.frame)

    def _build_ui(self, parent):
        f = ttk.LabelFrame(parent, text="Power Supply Controls")
        f.pack(fill="x", padx=10, pady=10)

        ttk.Label(f, text="Model:").grid(row=0, column=0, padx=6, pady=8, sticky="e")
        ttk.Label(f, textvariable=self.model_var).grid(row=0, column=1, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Channel:").grid(row=0, column=2, padx=6, pady=8, sticky="e")
        self.channel_combo = ttk.Combobox(f, textvariable=self.channel_var, state="readonly", width=12)
        self.channel_combo.grid(row=0, column=3, padx=(0,12), pady=8, sticky="w")

        ttk.Label(f, text="Voltage (V):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(f, textvariable=self.voltage_var, width=10).grid(row=1, column=1, padx=(0,12), pady=6, sticky="w")
        ttk.Button(f, text="Set V", command=self.set_voltage).grid(row=1, column=2, padx=6, pady=6)
        ttk.Button(f, text="Query V", command=self.query_voltage).grid(row=1, column=3, padx=6, pady=6)

        ttk.Label(f, text="Current Limit (A):").grid(row=2, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(f, textvariable=self.current_var, width=10).grid(row=2, column=1, padx=(0,12), pady=6, sticky="w")
        ttk.Button(f, text="Set I", command=self.set_current).grid(row=2, column=2, padx=6, pady=6)
        ttk.Button(f, text="Query I", command=self.query_current).grid(row=2, column=3, padx=6, pady=6)

        for c, w in enumerate([0,1,0,1]):
            f.grid_columnconfigure(c, weight=w)

    # -- lifecycle --
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
            return

        model = common.detect_psu_model(idn)
        self.model_var.set(model or "(Unknown)")
        chs = common.psu_channel_values(model)
        if not chs:
            self.channel_combo["values"] = []
            self.set_enabled(False)
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

    # -- ops --
    def set_voltage(self):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            channel = common.trim(self.channel_var.get())
            v = float(self.voltage_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(channel)
                inst.write(f"SU{idx}:{v}")
            else:
                common.psu_select_channel(inst, model, channel)
                if model in ("HMP4040", "HMP4030"):
                    inst.write(f"SOUR:VOLT {v}")
                elif model in ("E3631A", "E3633A"):
                    inst.write(f"VOLT {v}")
            self.log(f"[PSU] Set V -> {v} on {channel} ({model})")
        except Exception as e:
            messagebox.showerror("Set Voltage failed", str(e))

    def set_current(self):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            channel = common.trim(self.channel_var.get())
            i = float(self.current_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(channel)
                inst.write(f"SI{idx}:{i}")
            else:
                common.psu_select_channel(inst, model, channel)
                if model in ("HMP4040", "HMP4030"):
                    inst.write(f"SOUR:CURR {i}")
                elif model in ("E3631A", "E3633A"):
                    inst.write(f"CURR {i}")
            self.log(f"[PSU] Set I -> {i} on {channel} ({model})")
        except Exception as e:
            messagebox.showerror("Set Current failed", str(e))

    def query_voltage(self):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            channel = common.trim(self.channel_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(channel)
                resp = inst.query(f"RU{idx}").strip()
            else:
                common.psu_select_channel(inst, model, channel)
                if model in ("HMP4040", "HMP4030"):
                    resp = inst.query("SOUR:VOLT?").strip()
                elif model in ("E3631A", "E3633A"):
                    resp = inst.query("VOLT?").strip()

            self.voltage_var.set(common.extract_number(resp))
            self.log(f"[PSU] Query V on {channel} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Voltage failed", str(e))

    def query_current(self):
        try:
            inst = self.get_inst();  idn = self.get_idn()
            if not inst: return
            model = common.detect_psu_model(idn)
            channel = common.trim(self.channel_var.get())

            if model == "HM8143":
                idx = common.hm8143_ch_index(channel)
                resp = inst.query(f"RI{idx}").strip()
            else:
                common.psu_select_channel(inst, model, channel)
                if model in ("HMP4040", "HMP4030"):
                    resp = inst.query("SOUR:CURR?").strip()
                elif model in ("E3631A", "E3633A"):
                    resp = inst.query("CURR?").strip()

            self.current_var.set(common.extract_number(resp))
            self.log(f"[PSU] Query I on {channel} ({model}) -> {resp}")
        except Exception as e:
            messagebox.showerror("Query Current failed", str(e))
