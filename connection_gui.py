# hmp4040_gui_all_connect_minimal.py
import tkinter as tk
from tkinter import ttk, messagebox

import pyvisa
from pyvisa import constants as pv  # parity/stopbits 등 상수 사용
from hmp4040 import hmp4040 as HMP4040Class


# -----------------------------
# Mock instrument for simulation (IDN만 지원)
# -----------------------------
class MockInstrument:
    def write(self, cmd: str):
        pass

    def query(self, cmd: str) -> str:
        cmd = cmd.strip().upper()
        if cmd == "*IDN?":
            return "Rohde&Schwarz,HMP4040,Mock,1.00"
        return ""

    def clear(self):
        pass

    def close(self):
        pass


# -----------------------------
# Minimal GUI: scan/connect/list/log
# -----------------------------
class GUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Control GUI")
        self.geometry("900x520")

        self.rm = None
        self.sessions = {}
        self.scanned_resources = []
        self.current_resource_key = None
        self.current_idn = None

        self.simulated = tk.BooleanVar(value=False)
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

        self.idn_label = ttk.Label(topbar, text="[IDN] - Not connected")
        self.idn_label.grid(row=0, column=3, padx=6, pady=6, sticky="w")

        # Devices table
        devf = ttk.LabelFrame(self, text="Devices (scanned & connected)")
        devf.pack(fill="both", expand=False, padx=10, pady=(10, 10))

        columns = ("resource", "idn", "label")
        self.dev_tree = ttk.Treeview(devf, columns=columns, show="headings", height=7)
        self.dev_tree.heading("resource", text="VISA Resource")
        self.dev_tree.heading("idn", text="IDN")
        self.dev_tree.heading("label", text="Label")
        self.dev_tree.column("resource", width=250, anchor="w")
        self.dev_tree.column("idn", width=350, anchor="w")
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

        # Log with Clear Log
        logf = ttk.LabelFrame(self, text="Log")
        logf.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        log_toolbar = ttk.Frame(logf)
        log_toolbar.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(log_toolbar, text="Clear Log", command=self.clear_log).pack(side="right")

        self.log = tk.Text(logf, height=12)
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

    def clear_log(self):
        self.log.delete("1.0", "end")
        self.status.set("Log cleared.")

    def _update_idn_banner(self):
        if self.current_resource_key and self.current_resource_key in self.sessions:
            info = self.sessions[self.current_resource_key]
            label = info.get("label") or ""
            idn = info.get("idn") or ""
            base = f"[IDN] {idn} ({self.current_resource_key})"
            self.idn_label.config(text=(f"{label} | {base}" if label else base))
        else:
            self.idn_label.config(text="[IDN] - Not connected")

    def _on_toggle_sim(self, *_):
        self.status.set("Simulated mode ON" if self.simulated.get() else "Simulated mode OFF")

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
        vals = list(self.dev_tree.item(key, "values"))
        if len(vals) == 3:
            vals[2] = new_label
            self.dev_tree.item(key, values=vals)
        if key == self.current_resource_key:
            self._update_idn_banner()

    # ---------- connection ----------
    def scan_resources(self):
        try:
            self._busy(True, "Scanning VISA resources...")
            if self.simulated.get():
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

    def _try_open_serial(self, resource_key):
        """
        ASRL 포트를 robust 하게 연결 시도.
        맞는 설정을 찾으면 (inst, idn) 반환, 실패 시 (None, None) 반환.
        """
        self.rm = self.rm or pyvisa.ResourceManager()

        # 공통: 짧은 타임아웃으로 빠르게 여러 조합을 시도
        baud_candidates = [115200, 38400, 19200, 9600]
        # (write_term, read_term)
        term_candidates = [("\r\n", "\n"), ("\n", "\n"), ("\r", "\r"), ("\r\n", "\r\n")]

        # 일부 어댑터는 첫 open에서 오래 걸릴 수 있음 -> open 실패 시 바로 예외 처리
        try:
            inst = self.rm.open_resource(resource_key)
        except Exception:
            return None, None

        # 기본 타임아웃을 짧게
        try:
            inst.timeout = 500
            inst.write_timeout = 500
        except Exception:
            pass

        # 흐름제어/포맷(장비에 맞춰 필요 시 수정)
        try:
            inst.data_bits = 8
            inst.parity = getattr(pv.Parity, "none", 0)
            inst.stop_bits = getattr(pv.StopBits, "one", 10)  # pyvisa가 내부적으로 enum 처리
            # 일부 백엔드에서는 rtscts/xonxoff 속성이 없을 수 있어 try/except
            if hasattr(inst, "rtscts"):
                inst.rtscts = False
            if hasattr(inst, "xonxoff"):
                inst.xonxoff = False
        except Exception:
            pass

        # 버퍼 클리어
        try:
            inst.clear()
        except Exception:
            pass

        for baud in baud_candidates:
            try:
                if hasattr(inst, "baud_rate"):
                    inst.baud_rate = baud
            except Exception:
                # 설정 불가한 백엔드면 다음 후보로 그대로 진행
                pass

            for wterm, rterm in term_candidates:
                try:
                    if hasattr(inst, "write_termination"):
                        inst.write_termination = wterm
                    if hasattr(inst, "read_termination"):
                        inst.read_termination = rterm

                    # 쓰레기 데이터 제거
                    try:
                        inst.clear()
                    except Exception:
                        pass

                    # 일부 장비는 깨어나는데 시간이 필요 -> 빈 쓰기 시도(무시 가능)
                    try:
                        inst.write("")
                    except Exception:
                        pass

                    # IDN 시도
                    idn = inst.query("*IDN?").strip()
                    if idn:
                        return inst, idn
                except Exception:
                    # 타임아웃/프레이밍 오류 등 -> 다음 설정으로
                    continue

        # 모든 시도 실패
        try:
            inst.close()
        except Exception:
            pass
        return None, None

    @staticmethod
    def _is_hmp4040(idn: str) -> bool:
        if not idn:
            return False
        s = idn.upper()
        return "HMP4040" in s or ("ROHDE" in s and "HMP4040" in s)

    def connect_all(self):
        if not self.scanned_resources:
            messagebox.showinfo("Nothing to connect", "Scan resources first.")
            return
        self._busy(True, "Connecting to all scanned instruments...")
        connected_count = 0

        for resource_key in self.scanned_resources:
            if resource_key in self.sessions:
                continue

            try:
                if resource_key.startswith("SIMULATED"):
                    inst = MockInstrument()
                    idn = inst.query("*IDN?").strip()

                elif resource_key.upper().startswith("ASRL"):
                    # 시리얼 전용 연결 루틴: 보드레이트/종단문자 자동 탐색
                    inst, idn = self._try_open_serial(resource_key)
                    if inst is None:
                        self.log_line(f"[ERROR] Failed to connect {resource_key}: no response on serial (tried common settings)")
                        continue

                else:
                    # USB/GPIB 등은 비교적 표준적인 설정
                    self.rm = self.rm or pyvisa.ResourceManager()
                    inst = self.rm.open_resource(resource_key)
                    try:
                        inst.timeout = 1000
                        inst.write_timeout = 1000
                        # 대부분의 TMC/GPIB는 \n로 충분하지만, 안전하게 설정
                        if hasattr(inst, "read_termination"):
                            inst.read_termination = "\n"
                        if hasattr(inst, "write_termination"):
                            inst.write_termination = "\n"
                        try:
                            inst.clear()
                        except Exception:
                            pass
                    except Exception:
                        pass
                    idn = inst.query("*IDN?").strip()

                # 필요시 모델 필터링 (HMP4040 전용일 경우 아래 주석 해제)
                # if not self._is_hmp4040(idn):
                #     self.log_line(f"[WARN] {resource_key} responded but not HMP4040: {idn}")
                #     try:
                #         inst.close()
                #     except Exception:
                #         pass
                #     continue

                # HMP4040 래퍼(연결 후 기능 확장을 위해 보관; 현재 UI에서는 사용 안 함)
                wrapper = HMP4040Class(pyvisa_instr=inst)

                self.sessions[resource_key] = {
                    "inst": inst,
                    "wrapper": wrapper,
                    "idn": idn,
                    "label": "",
                }
                # Treeview 추가
                self.dev_tree.insert("", "end", iid=resource_key, values=(resource_key, idn, ""))
                self.log_line(f"[INFO] Connected: {idn} ({resource_key})")
                connected_count += 1

            except Exception as e:
                self.log_line(f"[ERROR] Failed to connect {resource_key}: {e}")

        if connected_count and not self.current_resource_key:
            first = self.dev_tree.get_children()
            if first:
                self.dev_tree.selection_set(first[0])
                self.dev_tree.focus(first[0])
                self._on_tree_selection()

        self.status.set(f"Connected {connected_count} device(s).")
        self._busy(False, "Ready.")


if __name__ == "__main__":
    app = GUI()
    app.mainloop()
