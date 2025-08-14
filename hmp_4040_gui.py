# hmp4040_gui_all_connect.py
import tkinter as tk
from tkinter import ttk, messagebox

import pyvisa  # hard import (no try/except)
from hmp4040 import hmp4040 as HMP4040Class


# -----------------------------
# Mock instrument for simulation
# -----------------------------
class MockInstrument:
    def __init__(self):
        self.selected_ch = 1
        self.channels = {
            ch: {
                "VOLT": 0.0,
                "CURR": 0.1,
                "OUT": 0,
                "MEAS_V": 0.0,
                "MEAS_I": 0.0,
                "OVP_MODE": "measured",
            }
            for ch in [1, 2, 3, 4]
        }

    def write(self, cmd: str):
        cmd = cmd.strip()
        if cmd.upper().startswith("*RST"):
            for ch in self.channels:
                self.channels[ch]["VOLT"] = 0.0
                self.channels[ch]["CURR"] = 0.1
                self.channels[ch]["OUT"] = 0
                self.channels[ch]["MEAS_V"] = 0.0
                self.channels[ch]["MEAS_I"] = 0.0
                self.channels[ch]["OVP_MODE"] = "measured"
            self.selected_ch = 1
            return

        if cmd.upper().startswith("INST"):
            try:
                self.selected_ch = int(cmd.split()[-1])
            except Exception:
                pass
            return

        ch = self.selected_ch
        if cmd.upper().startswith("SOURCE:VOLTAGE"):
            val = float(cmd.split()[-1])
            self.channels[ch]["VOLT"] = val
            self.channels[ch]["MEAS_V"] = val
        elif cmd.upper().startswith("SOURCE:CURRENT"):
            val = float(cmd.split()[-1])
            self.channels[ch]["CURR"] = val
        elif cmd.upper().startswith("OUTPUT:STATE"):
            val = int(cmd.split()[-1])
            self.channels[ch]["OUT"] = val
            self.channels[ch]["MEAS_I"] = 0.01 * val
        elif cmd.upper().startswith("VOLTAGE:PROTECTION:MODE"):
            val = cmd.split()[-1].lower()
            if val in ("measured", "protected"):
                self.channels[ch]["OVP_MODE"] = val

    def query(self, cmd: str) -> str:
        cmd = cmd.strip()
        if cmd.upper().startswith("*IDN?"):
            return "Rohde&Schwarz,HMP4040,Mock,1.00"
        if cmd.upper().startswith("SOURCE:VOLTAGE?"):
            return f"{self.channels[self.selected_ch]['VOLT']:.3f}"
        if cmd.upper().startswith("SOURCE:CURRENT?"):
            return f"{self.channels[self.selected_ch]['CURR']:.4f}"
        if cmd.upper().startswith("OUTPUT:STATE?"):
            return f"{self.channels[self.selected_ch]['OUT']}"
        if cmd.upper().startswith("MEASURE:VOLTAGE?"):
            return f"{self.channels[self.selected_ch]['MEAS_V']:.3f}"
        if cmd.upper().startswith("MEASURE:CURRENT?"):
            return f"{self.channels[self.selected_ch]['MEAS_I']:.3f}"
        if cmd.upper().startswith("VOLTAGE:PROTECTION:MODE?"):
            return self.channels[self.selected_ch]["OVP_MODE"]
        return ""

    def close(self):
        pass


# -----------------------------
# GUI (batch connect; no threading)
# -----------------------------
class HMP4040GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HMP4040 Control GUI (batch connect)")
        self.geometry("1100x680")

        self.rm = None
        # 세션: resource_key -> {"inst": ..., "wrapper": ..., "idn": str, "label": str}
        self.sessions = {}
        # 스캔된 리소스 목록
        self.scanned_resources = []
        # 현재 선택된 리소스 키
        self.current_resource_key = None
        self.current_idn = None

        self.simulated = tk.BooleanVar(value=False)

        # 고정 파라미터(채널/설정)
        self.channel_var = tk.IntVar(value=1)
        self.volt_var = tk.StringVar(value="0.000")
        self.curr_var = tk.StringVar(value="0.1000")
        self.ovp_mode = tk.StringVar(value="measured")
        self.out_var = tk.BooleanVar(value=False)

        # Label 편집용
        self.sel_label_var = tk.StringVar(value="")

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        # Top: Connection
        topbar = ttk.LabelFrame(self, text="Connection")
        topbar.pack(fill="x", padx=10, pady=(10, 0))

        ttk.Checkbutton(topbar, text="Simulated", variable=self.simulated,
                        command=self._on_toggle_sim).grid(row=0, column=0, padx=6, pady=6, sticky="w")

        ttk.Button(topbar, text="Scan", command=self.scan_resources).grid(row=0, column=1, padx=6, pady=6, sticky="w")
        ttk.Button(topbar, text="Connect All", command=self.connect_all).grid(row=0, column=2, padx=6, pady=6, sticky="w")

        # IDN banner (현재 선택/연결된 장비 표시)
        self.idn_label = ttk.Label(topbar, text="[IDN] - Not connected")
        self.idn_label.grid(row=0, column=3, padx=6, pady=6, sticky="w")

        # Channel & Settings
        mid = ttk.LabelFrame(self, text="Channel & Settings")
        mid.pack(fill="x", padx=10, pady=10)

        ttk.Label(mid, text="Channel:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.channel_cb = ttk.Combobox(mid, width=6, values=[1, 2, 3, 4],
                                       textvariable=self.channel_var, state="readonly")
        self.channel_cb.grid(row=0, column=1, padx=6, pady=6, sticky="w")
        ttk.Button(mid, text="Select Channel", command=self.select_channel).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(mid, text="Voltage (V):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        ttk.Entry(mid, textvariable=self.volt_var, width=10).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(mid, text="Current Limit (A):").grid(row=1, column=2, padx=6, pady=6, sticky="e")
        ttk.Entry(mid, textvariable=self.curr_var, width=10).grid(row=1, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(mid, text="OVP Mode:").grid(row=1, column=4, padx=6, pady=6, sticky="e")
        ttk.Combobox(mid, width=12, values=["measured", "protected"], textvariable=self.ovp_mode,
                     state="readonly").grid(row=1, column=5, padx=6, pady=6, sticky="w")

        ttk.Checkbutton(mid, text="Output ON", variable=self.out_var, command=self.toggle_output)\
            .grid(row=2, column=0, padx=6, pady=6, sticky="w")

        ttk.Button(mid, text="Apply Settings", command=self.apply_settings).grid(row=2, column=2, padx=6, pady=6)
        ttk.Button(mid, text="Read Channel", command=self.read_channel).grid(row=2, column=3, padx=6, pady=6)
        ttk.Button(mid, text="Measure Now", command=self.measure_now).grid(row=2, column=4, padx=6, pady=6)

        # Actions
        act = ttk.LabelFrame(self, text="Actions")
        act.pack(fill="x", padx=10, pady=10)
        ttk.Button(act, text="*RST (Reset)", command=self.reset_inst).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(act, text="Save Unique Settings", command=self.save_unique).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(act, text="Restore Unique Settings", command=self.restore_unique).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(act, text="Print State (Console)", command=self.print_state).grid(row=0, column=3, padx=6, pady=6)

        # ---- NEW: Devices table (between Actions and Log) ----
        devf = ttk.LabelFrame(self, text="Devices (scanned & connected)")
        devf.pack(fill="both", expand=False, padx=10, pady=(0, 10))

        columns = ("resource", "idn", "label")
        self.dev_tree = ttk.Treeview(devf, columns=columns, show="headings", height=6)
        self.dev_tree.heading("resource", text="VISA Resource")
        self.dev_tree.heading("idn", text="IDN")
        self.dev_tree.heading("label", text="Label")
        self.dev_tree.column("resource", width=260, anchor="w")
        self.dev_tree.column("idn", width=380, anchor="w")
        self.dev_tree.column("label", width=200, anchor="w")
        self.dev_tree.pack(fill="both", expand=True, padx=6, pady=(6, 0))
        self.dev_tree.bind("<<TreeviewSelect>>", self._on_tree_selection)

        editor = ttk.Frame(devf)
        editor.pack(fill="x", padx=6, pady=(6, 6))
        ttk.Label(editor, text="Label for selected:").grid(row=0, column=0, padx=(0, 6), pady=4, sticky="e")
        self.sel_label_entry = ttk.Entry(editor, textvariable=self.sel_label_var, width=40)
        self.sel_label_entry.grid(row=0, column=1, padx=(0, 6), pady=4, sticky="we")
        ttk.Button(editor, text="Save Label", command=self._save_selected_label).grid(row=0, column=2, padx=6, pady=4)
        editor.grid_columnconfigure(1, weight=1)

        # Log (reduced height)
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log = tk.Text(logf, height=10)  # ↓ reduced from 16 to 10
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

        self._on_toggle_sim()

    # ---------- helpers ----------
    def _busy(self, on=True, msg=None):
        self.config(cursor="watch" if on else "")
        if msg:
            self.status.set(msg)
        self.update_idletasks()

    def log_line(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _require_selection_connected(self):
        key = self.current_resource_key
        if not key or key not in self.sessions:
            messagebox.showwarning("No device", "Select a connected device in the table first.")
            return None
        return key

    def _update_idn_banner(self):
        if self.current_resource_key and self.current_resource_key in self.sessions:
            info = self.sessions[self.current_resource_key]
            label = info.get("label") or ""
            idn = info.get("idn") or ""
            base = f"[IDN] {idn} ({self.current_resource_key})"
            self.idn_label.config(text=(f"{label} | {base}" if label else base))
        else:
            self.idn_label.config(text="[IDN] - Not connected")

    def _on_tree_selection(self, event=None):
        sel = self.dev_tree.selection()
        if not sel:
            return
        key = sel[0]
        if key in self.sessions:
            self.current_resource_key = key
            self.current_idn = self.sessions[key].get("idn", "")
            self.sel_label_var.set(self.sessions[key].get("label", ""))
            self._update_idn_banner()

    def _save_selected_label(self):
        sel = self.dev_tree.selection()
        if not sel:
            messagebox.showinfo("No selection", "Please select a device in the table first.")
            return
        key = sel[0]
        if key not in self.sessions:
            return
        new_label = (self.sel_label_var.get() or "").strip()
        self.sessions[key]["label"] = new_label
        # Treeview 값 업데이트
        vals = list(self.dev_tree.item(key, "values"))
        if len(vals) == 3:
            vals[2] = new_label
            self.dev_tree.item(key, values=vals)
        # 배너 갱신
        if key == self.current_resource_key:
            self._update_idn_banner()

    # ---------- connection workflow ----------
    def _on_toggle_sim(self):
        self.status.set("Simulated mode ON" if self.simulated.get() else "Simulated mode OFF")

    def scan_resources(self):
        try:
            self._busy(True, "Scanning VISA resources...")
            if self.simulated.get():
                # 가상으로 여러 개 제공
                self.scanned_resources = [f"SIMULATED{i}" for i in range(1, 4)]
            else:
                self.rm = self.rm or pyvisa.ResourceManager()
                self.scanned_resources = list(self.rm.list_resources())
            if not self.scanned_resources:
                self.status.set("No VISA resources found.")
                self.log_line("[SCAN] No VISA resources found.")
            else:
                self.status.set(f"Found {len(self.scanned_resources)} resource(s).")
                self.log_line(f"[SCAN] {len(self.scanned_resources)} resource(s) found:")
                for r in self.scanned_resources:
                    self.log_line(f"  - {r}")
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def connect_all(self):
        if not self.scanned_resources:
            messagebox.showinfo("Nothing to connect", "Scan resources first.")
            return
        self._busy(True, "Connecting to all scanned instruments...")
        connected_count = 0
        for resource_key in self.scanned_resources:
            if resource_key in self.sessions:
                # 이미 연결됨: skip
                continue
            try:
                if resource_key.startswith("SIMULATED"):
                    inst = MockInstrument()
                else:
                    self.rm = self.rm or pyvisa.ResourceManager()
                    inst = self.rm.open_resource(resource_key)
                    try:
                        inst.timeout = 1000  # ms
                        inst.write_timeout = 1000
                        inst.read_termination = "\n"
                        inst.write_termination = "\n"
                    except Exception:
                        pass

                idn = inst.query("*IDN?").strip()
                wrapper = HMP4040Class(pyvisa_instr=inst)

                self.sessions[resource_key] = {
                    "inst": inst,
                    "wrapper": wrapper,
                    "idn": idn,
                    "label": "",
                }
                # Treeview에 추가
                self.dev_tree.insert("", "end", iid=resource_key, values=(resource_key, idn, ""))
                self.log_line(f"[INFO] Connected: {idn} ({resource_key})")
                connected_count += 1

            except Exception as e:
                self.log_line(f"[ERROR] Failed to connect {resource_key}: {e}")

        if connected_count:
            # 첫 연결된 장비로 선택 이동 (없다면 유지)
            if not self.current_resource_key:
                # 첫번째 항목 선택
                first = self.dev_tree.get_children()
                if first:
                    self.dev_tree.selection_set(first[0])
                    self.dev_tree.focus(first[0])
                    self._on_tree_selection()
        self.status.set(f"Connected {connected_count} device(s).")
        self._busy(False, "Ready.")

    # ---------- per-device ops (use selected) ----------
    def _get_selected_handles(self):
        key = self._require_selection_connected()
        if not key:
            return None, None, None
        info = self-sessions_get(key)
        if not info:
            messagebox.showwarning("Device not available", "Selected device is not connected.")
            return None, None, None
        return key, info["inst"], info["wrapper"]

    def self-sessions_get(self, key):
        # 작은 헬퍼: KeyError 방지
        return self.sessions.get(key)

    def select_channel(self):
        key, inst, _ = self._get_selected_handles()
        if not inst:
            return
        ch = int(self.channel_var.get())
        try:
            self._busy(True, f"[{key}] Selecting channel {ch}...")
            inst.write(f"INSTrument:NSELect {ch}")
            self.log_line(f"[{key}] [SCPI] INSTrument:NSELect {ch}")
            self.status.set(f"[{key}] Channel {ch} selected.")
        except Exception as e:
            messagebox.showerror("Select channel failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def apply_settings(self):
        key, inst, _ = self._get_selected_handles()
        if not inst:
            return
        try:
            v = float(self.volt_var.get())
            i = float(self.curr_var.get())
        except ValueError:
            messagebox.showerror("Invalid input", "Voltage/Current must be numeric.")
            return
        ovp = self.ovp_mode.get().lower()
        if ovp not in ("measured", "protected"):
            messagebox.showerror("Invalid OVP", "OVP mode must be 'measured' or 'protected'.")
            return
        ch = int(self.channel_var.get())
        try:
            self._busy(True, f"[{key}] Applying settings to CH{ch}...")
            inst.write(f"INSTrument:NSELect {ch}")
            inst.write(f"SOURce:VOLTage {v}")
            inst.write(f"SOURce:CURRent {i}")
            inst.write(f"VOLTage:PROTection:MODE {ovp}")
            self.log_line(f"[{key}] [APPLY] CH{ch} -> V={v} V, I={i} A, OVP={ovp}")
            self.status.set(f"[{key}] Settings applied to CH{ch}.")
        except Exception as e:
            messagebox.showerror("Apply settings failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def read_channel(self):
        key, inst, _ = self._get_selected_handles()
        if not inst:
            return
        ch = int(self.channel_var.get())
        try:
            self._busy(True, f"[{key}] Reading CH{ch}...")
            inst.write(f"INSTrument:NSELect {ch}")
            vset = float(inst.query("SOURce:VOLTage?"))
            iset = float(inst.query("SOURce:CURRent?"))
            out = int(inst.query("OUTPut:STATe?"))
            ovp = inst.query("VOLTage:PROTection:MODE?").strip()
            self.volt_var.set(f"{vset:.3f}")
            self.curr_var.set(f"{iset:.4f}")
            self.ovp_mode.set(ovp)
            self.out_var.set(bool(out))
            self.log_line(f"[{key}] [READ] CH{ch} -> V={vset:.3f} V, I={iset:.4f} A, OUT={out}, OVP={ovp}")
            self.status.set(f"[{key}] Read CH{ch} settings.")
        except Exception as e:
            messagebox.showerror("Read channel failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def toggle_output(self):
        key, inst, _ = self._get_selected_handles()
        if not inst:
            self.out_var.set(False)
            return
        ch = int(self.channel_var.get())
        state = 1 if self.out_var.get() else 0
        try:
            self._busy(True, f"[{key}] Setting CH{ch} output {'ON' if state else 'OFF'}...")
            inst.write(f"INSTrument:NSELect {ch}")
            inst.write(f"OUTPut:STATe {state}")
            self.log_line(f"[{key}] [SCPI] CH{ch} OUTPut:STATe {state}")
            self.status.set(f"[{key}] CH{ch} Output {'ON' if state else 'OFF'}.")
        except Exception as e:
            self.out_var.set(not bool(state))
            messagebox.showerror("Output toggle failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def measure_now(self):
        key, inst, _ = self._get_selected_handles()
        if not inst:
            return
        ch = int(self.channel_var.get())
        try:
            self._busy(True, f"[{key}] Measuring CH{ch}...")
            inst.write(f"INSTrument:NSELect {ch}")
            vmeas = float(inst.query("MEASure:VOLTage?"))
            imeas = float(inst.query("MEASure:CURRent?"))
            self.log_line(f"[{key}] [MEAS] CH{ch} -> V={vmeas:.3f} V, I={imeas:.3f} A")
            self.status.set(f"[{key}] Measured CH{ch}: {vmeas:.3f} V, {imeas:.3f} A")
        except Exception as e:
            messagebox.showerror("Measure failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def reset_inst(self):
        key, inst, _ = self._get_selected_handles()
        if not inst:
            return
        try:
            self._busy(True, f"[{key}] Resetting instrument...")
            inst.write("*RST")
            self.status.set(f"[{key}] Instrument reset done.")
            self.log_line(f"[{key}] [SCPI] *RST")
        except Exception as e:
            messagebox.showerror("Reset failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def save_unique(self):
        key, _, wrapper = self._get_selected_handles()
        if not wrapper:
            return
        try:
            self._busy(True, f"[{key}] Capturing unique settings...")
            unique = wrapper.get_unique_scpi_list()
            # 세션별 캐시
            self.sessions[key]["unique_cache"] = unique
            self.log_line(f"[{key}] [UNIQUE] Captured unique settings:")
            for line in unique:
                self.log_line("  " + line)
            self.status.set(f"[{key}] Unique settings captured.")
        except Exception as e:
            messagebox.showerror("Save unique failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def restore_unique(self):
        key, inst, _ = self._get_selected_handles()
        if not inst:
            return
        cache = self.sessions[key].get("unique_cache", [])
        if not cache:
            messagebox.showwarning("No saved settings", "Run 'Save Unique Settings' first.")
            return
        try:
            self._busy(True, f"[{key}] Restoring unique settings...")
            inst.write("*RST")
            self.log_line(f"[{key}] [SCPI] *RST")
            # 간단히 순차 수행 (타이머 대신 즉시)
            for line in cache:
                inst.write(line)
            self.status.set(f"[{key}] Unique settings restored.")
            self.log_line(f"[{key}] [UNIQUE] Restored saved unique settings.")
        except Exception as e:
            messagebox.showerror("Restore unique failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def print_state(self):
        key, _, wrapper = self._get_selected_handles()
        if not wrapper:
            return
        try:
            self._busy(True, f"[{key}] Printing state to console...")
            wrapper.get_inst_state()  # prints to console
            self.log_line(f"[{key}] [STATE] Printed to console.")
            self.status.set(f"[{key}] State printed to console.")
        except Exception as e:
            messagebox.showerror("Print state failed", str(e))
        finally:
            self._busy(False, "Ready.")


if __name__ == "__main__":
    app = HMP4040GUI()
    app.mainloop()
