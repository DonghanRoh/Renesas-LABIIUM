# hmp4040_gui_no_threads.py
import tkinter as tk
from tkinter import ttk, messagebox
import time

import pyvisa  # hard import as requested
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
# GUI (no threading)
# -----------------------------
class HMP4040GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("HMP4040 Control GUI (no threading)")
        self.geometry("1040x680")

        self.rm = None
        self.inst = None
        self.wrapper = None
        self.connected = False
        self.simulated = tk.BooleanVar(value=False)
        self._unique_cache = []

        # current connection state
        self.current_idn = None              # IDN string for display
        self.current_resource_key = None     # VISA Resource (or SIMULATED#n) -> the ONLY key for labeling

        # session devices: resource_key -> {"idn": str, "label": str}
        self.devices = {}

        # simulated resource unique counter
        self.sim_counter = 0

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        # top bar: left(connection), right(device list)
        topbar = ttk.Frame(self)
        topbar.pack(fill="x", padx=10, pady=(10, 0))

        # left: connection group
        conn = ttk.LabelFrame(topbar, text="Connection")
        conn.pack(side="left", fill="x", expand=True, padx=(0, 10))

        ttk.Checkbutton(conn, text="Simulated", variable=self.simulated,
                        command=self._on_toggle_sim).grid(row=0, column=0, padx=6, pady=6, sticky="w")

        ttk.Label(conn, text="VISA Resource:").grid(row=0, column=1, padx=6, pady=6, sticky="e")
        self.resource_cb = ttk.Combobox(conn, width=42, values=[])
        self.resource_cb.grid(row=0, column=2, padx=6, pady=6, sticky="w")

        ttk.Button(conn, text="Scan", command=self.scan_resources).grid(row=0, column=3, padx=6, pady=6)
        ttk.Button(conn, text="Connect", command=self.connect).grid(row=0, column=4, padx=6, pady=6)

        # user device label entry (between Connect and IDN)
        self.device_name_var = tk.StringVar(value="PSU")
        self.device_name_entry = ttk.Entry(conn, textvariable=self.device_name_var, width=16)
        self.device_name_entry.grid(row=0, column=5, padx=6, pady=6, sticky="w")

        # IDN label
        self.idn_label = ttk.Label(conn, text="[IDN] - Not connected")
        self.idn_label.grid(row=0, column=6, padx=6, pady=6, sticky="w")

        # when label text changes, only update the CURRENT resource's label
        try:
            self.device_name_var.trace_add("write", lambda *args: self._on_label_changed())
        except Exception:
            self.device_name_var.trace("w", lambda *args: self._on_label_changed())

        # right: devices list (one column)
        devf = ttk.LabelFrame(topbar, text="Devices (this session)")
        devf.pack(side="right", fill="y")

        ttk.Label(devf, text="Shown by VISA Resource").pack(anchor="w", padx=6, pady=(6, 0))

        self.device_listbox = tk.Listbox(devf, height=10, width=56, exportselection=False)
        self.device_listbox.pack(fill="both", expand=True, padx=6, pady=6)

        # body
        mid = ttk.LabelFrame(self, text="Channel & Settings")
        mid.pack(fill="x", padx=10, pady=10)

        ttk.Label(mid, text="Channel:").grid(row=0, column=0, padx=6, pady=6, sticky="e")
        self.channel_var = tk.IntVar(value=1)
        self.channel_cb = ttk.Combobox(mid, width=6, values=[1, 2, 3, 4],
                                       textvariable=self.channel_var, state="readonly")
        self.channel_cb.grid(row=0, column=1, padx=6, pady=6, sticky="w")
        ttk.Button(mid, text="Select Channel", command=self.select_channel).grid(row=0, column=2, padx=6, pady=6)

        ttk.Label(mid, text="Voltage (V):").grid(row=1, column=0, padx=6, pady=6, sticky="e")
        self.volt_var = tk.StringVar(value="0.000")
        ttk.Entry(mid, textvariable=self.volt_var, width=10).grid(row=1, column=1, padx=6, pady=6, sticky="w")

        ttk.Label(mid, text="Current Limit (A):").grid(row=1, column=2, padx=6, pady=6, sticky="e")
        self.curr_var = tk.StringVar(value="0.1000")
        ttk.Entry(mid, textvariable=self.curr_var, width=10).grid(row=1, column=3, padx=6, pady=6, sticky="w")

        ttk.Label(mid, text="OVP Mode:").grid(row=1, column=4, padx=6, pady=6, sticky="e")
        self.ovp_mode = tk.StringVar(value="measured")
        ttk.Combobox(mid, width=12, values=["measured", "protected"], textvariable=self.ovp_mode,
                     state="readonly").grid(row=1, column=5, padx=6, pady=6, sticky="w")

        self.out_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(mid, text="Output ON", variable=self.out_var, command=self.toggle_output)\
            .grid(row=2, column=0, padx=6, pady=6, sticky="w")

        ttk.Button(mid, text="Apply Settings", command=self.apply_settings).grid(row=2, column=2, padx=6, pady=6)
        ttk.Button(mid, text="Read Channel", command=self.read_channel).grid(row=2, column=3, padx=6, pady=6)
        ttk.Button(mid, text="Measure Now", command=self.measure_now).grid(row=2, column=4, padx=6, pady=6)

        act = ttk.LabelFrame(self, text="Actions")
        act.pack(fill="x", padx=10, pady=10)
        ttk.Button(act, text="*RST (Reset)", command=self.reset_inst).grid(row=0, column=0, padx=6, pady=6)
        ttk.Button(act, text="Save Unique Settings", command=self.save_unique).grid(row=0, column=1, padx=6, pady=6)
        ttk.Button(act, text="Restore Unique Settings", command=self.restore_unique).grid(row=0, column=2, padx=6, pady=6)
        ttk.Button(act, text="Print State (Console)", command=self.print_state).grid(row=0, column=3, padx=6, pady=6)

        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, padx=10, pady=10)
        self.log = tk.Text(logf, height=16)
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        self.status = tk.StringVar(value="Ready.")
        ttk.Label(self, textvariable=self.status, relief="sunken", anchor="w").pack(fill="x")

        self._on_toggle_sim()
        self._refresh_device_list()

    # ---------- helpers ----------
    def _require_connection(self):
        if not self.connected or self.inst is None:
            messagebox.showwarning("Not connected", "Please connect to the instrument first.")
            return False
        return True

    def log_line(self, msg: str):
        self.log.insert("end", msg + "\n")
        self.log.see("end")

    def _busy(self, on=True, msg=None):
        self.config(cursor="watch" if on else "")
        if msg:
            self.status.set(msg)
        self.update_idletasks()

    def _compose_display_line(self, idn: str, label: str, resource_key: str) -> str:
        """Return a single-line string for the device list."""
        clean_idn = (idn or "").replace("\n", " ").strip()
        label = (label or "").strip()
        if label:
            return f"{label} | [IDN] {clean_idn} ({resource_key})"
        else:
            return f"[IDN] {clean_idn} ({resource_key})"

    def _refresh_device_list(self):
        """Refresh the right-top device list (one column)."""
        self.device_listbox.delete(0, "end")
        if not self.devices:
            self.device_listbox.insert("end", "(No devices yet)")
            return

        labeled = []
        unlabeled = []
        for key, info in self.devices.items():
            (labeled if (info.get("label") or "").strip() else unlabeled).append((key, info))

        # sort for readability
        labeled.sort(key=lambda kv: ((kv[1].get("label") or "").lower(), kv[0].lower()))
        unlabeled.sort(key=lambda kv: kv[0].lower())

        for key, info in labeled + unlabeled:
            line = self._compose_display_line(info.get("idn", ""), info.get("label", ""), key)
            self.device_listbox.insert("end", line)

    def _update_idn_label(self):
        """Update the IDN display label at the top (uses VISA Resource as the key)."""
        label = (self.device_name_var.get() or "").strip()
        if self.current_idn and self.current_resource_key:
            self.idn_label.config(
                text=self._compose_display_line(self.current_idn, label, self.current_resource_key)
            )
        else:
            if label:
                self.idn_label.config(text=f"{label} | [IDN] - Not connected")
            else:
                self.idn_label.config(text="[IDN] - Not connected")

    def _record_connected_device(self):
        """Store/update the current device by VISA Resource key."""
        if not self.current_resource_key or not self.current_idn:
            return
        current_label = (self.device_name_var.get() or "").strip()
        self.devices[self.current_resource_key] = {"idn": self.current_idn, "label": current_label}
        self._refresh_device_list()

    def _on_label_changed(self):
        """Only update the CURRENT device's label when the Entry changes."""
        self._update_idn_label()
        if self.current_resource_key in self.devices:
            self.devices[self.current_resource_key]["label"] = (self.device_name_var.get() or "").strip()
            self._refresh_device_list()

    # ---------- connection ----------
    def _on_toggle_sim(self):
        sim = self.simulated.get()
        self.resource_cb.configure(state=("disabled" if sim else "normal"))
        self.status.set("Simulated mode ON" if sim else "Simulated mode OFF")

    def scan_resources(self):
        if self.simulated.get():
            self.resource_cb["values"] = ["SIMULATED"]
            self.resource_cb.set("SIMULATED")
            self.status.set("Simulated resource ready.")
            return

        try:
            self._busy(True, "Scanning VISA resources...")
            self.rm = pyvisa.ResourceManager()
            res = list(self.rm.list_resources())
            if not res:
                self.status.set("No VISA resources found.")
                self.resource_cb["values"] = []
            else:
                self.status.set(f"Found {len(res)} resource(s).")
                self.resource_cb["values"] = res
                self.resource_cb.set(res[0])
        except Exception as e:
            messagebox.showerror("Scan failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def connect(self):
        self._busy(True, "Connecting...")
        self.after(50, self._do_connect)

    def _do_connect(self):
        try:
            if self.simulated.get():
                self.inst = MockInstrument()
                # unique resource key for simulated each time
                self.sim_counter += 1
                self.current_resource_key = f"SIMULATED#{self.sim_counter}"
            else:
                if self.rm is None:
                    self.rm = pyvisa.ResourceManager()
                resource = self.resource_cb.get().strip()
                if not resource:
                    raise RuntimeError("Please select a VISA resource.")
                self.inst = self.rm.open_resource(resource)
                # use raw resource string as the unique key
                self.current_resource_key = resource

                # moderate timeouts
                try:
                    self.inst.timeout = 1000  # ms
                    self.inst.write_timeout = 1000
                    self.inst.read_termination = "\n"
                    self.inst.write_termination = "\n"
                except Exception:
                    pass

            idn = self.inst.query("*IDN?").strip()
            self.current_idn = idn
            self._update_idn_label()

            self.connected = True
            self.wrapper = HMP4040Class(pyvisa_instr=self.inst)
            self.select_channel()
            self.log_line(f"[INFO] Connected: {idn} ({self.current_resource_key})")
            self.status.set("Connected.")

            # add/update device by VISA Resource key
            self._record_connected_device()

        except Exception as e:
            self.connected = False
            self.wrapper = None
            self.inst = None
            self.current_idn = None
            self.current_resource_key = None
            self.idn_label.config(text="[IDN] - Not connected")
            self.status.set("Connection failed.")
            messagebox.showerror("Connection failed", str(e))
        finally:
            self._busy(False, "Ready.")

    # ---------- instrument ops ----------
    def select_channel(self):
        if not self._require_connection():
            return
        ch = int(self.channel_var.get())
        self._busy(True, f"Selecting channel {ch}...")
        self.after(10, self._do_select_channel, ch)

    def _do_select_channel(self, ch):
        try:
            self.inst.write(f"INSTrument:NSELect {ch}")
            self.log_line(f"[SCPI] INSTrument:NSELect {ch}")
            self.status.set(f"Channel {ch} selected.")
        except Exception as e:
            messagebox.showerror("Select channel failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def apply_settings(self):
        if not self._require_connection():
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
        self._busy(True, f"Applying settings to CH{ch}...")
        self.after(10, self._do_apply_settings, ch, v, i, ovp)

    def _do_apply_settings(self, ch, v, i, ovp):
        try:
            self.inst.write(f"INSTrument:NSELect {ch}")
            self.inst.write(f"SOURce:VOLTage {v}")
            self.inst.write(f"SOURce:CURRent {i}")
            self.inst.write(f"VOLTage:PROTection:MODE {ovp}")
            self.log_line(f"[APPLY] CH{ch} -> V={v} V, I={i} A, OVP={ovp}")
            self.status.set(f"Settings applied to CH{ch}.")
        except Exception as e:
            messagebox.showerror("Apply settings failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def read_channel(self):
        if not self._require_connection():
            return
        ch = int(self.channel_var.get())
        self._busy(True, f"Reading CH{ch}...")
        self.after(10, self._do_read_channel, ch)

    def _do_read_channel(self, ch):
        try:
            self.inst.write(f"INSTrument:NSELect {ch}")
            vset = float(self.inst.query("SOURce:VOLTage?"))
            iset = float(self.inst.query("SOURce:CURRent?"))
            out = int(self.inst.query("OUTPut:STATe?"))
            ovp = self.inst.query("VOLTage:PROTection:MODE?").strip()
            self.volt_var.set(f"{vset:.3f}")
            self.curr_var.set(f"{iset:.4f}")
            self.ovp_mode.set(ovp)
            self.out_var.set(bool(out))
            self.log_line(f"[READ] CH{ch} -> V={vset:.3f} V, I={iset:.4f} A, OUT={out}, OVP={ovp}")
            self.status.set(f"Read CH{ch} settings.")
        except Exception as e:
            messagebox.showerror("Read channel failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def toggle_output(self):
        if not self._require_connection():
            self.out_var.set(False)
            return
        ch = int(self.channel_var.get())
        state = 1 if self.out_var.get() else 0
        self._busy(True, f"Setting CH{ch} output {'ON' if state else 'OFF'}...")
        self.after(10, self._do_toggle_output, ch, state)

    def _do_toggle_output(self, ch, state):
        try:
            self.inst.write(f"INSTrument:NSELect {ch}")
            self.inst.write(f"OUTPut:STATe {state}")
            self.log_line(f"[SCPI] CH{ch} OUTPut:STATe {state}")
            self.status.set(f"CH{ch} Output {'ON' if state else 'OFF'}.")
        except Exception as e:
            # revert checkbox on failure
            self.out_var.set(not bool(state))
            messagebox.showerror("Output toggle failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def measure_now(self):
        if not self._require_connection():
            return
        ch = int(self.channel_var.get())
        self._busy(True, f"Measuring CH{ch}...")
        self.after(10, self._do_measure_now, ch)

    def _do_measure_now(self, ch):
        try:
            self.inst.write(f"INSTrument:NSELect {ch}")
            vmeas = float(self.inst.query("MEASure:VOLTage?"))
            imeas = float(self.inst.query("MEASure:CURRent?"))
            self.log_line(f"[MEAS] CH{ch} -> V={vmeas:.3f} V, I={imeas:.3f} A")
            self.status.set(f"Measured CH{ch}: {vmeas:.3f} V, {imeas:.3f} A")
        except Exception as e:
            messagebox.showerror("Measure failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def reset_inst(self):
        if not self._require_connection():
            return
        self._busy(True, "Resetting instrument...")
        self.after(10, self._do_reset_inst)

    def _do_reset_inst(self):
        try:
            self.inst.write("*RST")
            # quick status tick
            self.after(300, lambda: self.status.set("Instrument reset done."))
            self.log_line("[SCPI] *RST")
        except Exception as e:
            messagebox.showerror("Reset failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def save_unique(self):
        if not self._require_connection():
            return
        self._busy(True, "Capturing unique settings...")
        self.after(10, self._do_save_unique)

    def _do_save_unique(self):
        try:
            unique = self.wrapper.get_unique_scpi_list()
            self._unique_cache = unique
            self.log_line("[UNIQUE] Captured unique settings:")
            for line in unique:
                self.log_line("  " + line)
            self.status.set("Unique settings captured.")
        except Exception as e:
            messagebox.showerror("Save unique failed", str(e))
        finally:
            self._busy(False, "Ready.")

    def restore_unique(self):
        if not self._require_connection():
            return
        if not self._unique_cache:
            messagebox.showwarning("No saved settings", "Run 'Save Unique Settings' first.")
            return
        self._busy(True, "Restoring unique settings...")
        self.after(10, self._do_restore_stage, 0)

    def _do_restore_stage(self, idx):
        try:
            if idx == 0:
                self.inst.write("*RST")
                self.log_line("[SCPI] *RST")
                self.after(300, self._do_restore_stage, 1)
                return
            i = idx - 1
            if i < len(self._unique_cache):
                self.inst.write(self._unique_cache[i])
                self.after(30, self._do_restore_stage, idx + 1)
            else:
                self.status.set("Unique settings restored.")
                self._busy(False, "Ready.")
                self.log_line("[UNIQUE] Restored saved unique settings.")
        except Exception as e:
            self._busy(False, "Ready.")
            messagebox.showerror("Restore unique failed", str(e))

    def print_state(self):
        if not self._require_connection():
            return
        self._busy(True, "Printing state to console...")
        self.after(10, self._do_print_state)

    def _do_print_state(self):
        try:
            self.wrapper.get_inst_state()  # prints to console
            self.log_line("[STATE] Printed to console.")
            self.status.set("State printed to console.")
        except Exception as e:
            messagebox.showerror("Print state failed", str(e))
        finally:
            self._busy(False, "Ready.")


if __name__ == "__main__":
    # Make sure exactly one Tk root is created here.
    app = HMP4040GUI()
    app.mainloop()
