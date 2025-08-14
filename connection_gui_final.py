# connection_core.py
# Purpose: Scan VISA resources and connect to each device without any GUI or simulation.
# Notes:
# - Comments are written in English only (as requested).
# - No HMP4040-specific references or logic.
# - No simulation mode.
# - Prints results to stdout.
# - Robust serial (ASRL) probing is included.

import sys
from typing import Dict, Tuple, List, Optional

import pyvisa
from pyvisa import constants as pv  # parity/stopbits enums


class VisaDevice:
    """Lightweight holder for a PyVISA instrument. Extend as needed."""
    def __init__(self, pyvisa_instr):
        self.inst = pyvisa_instr

    def idn(self) -> str:
        """Query *IDN?; return empty string on failure."""
        try:
            return self.inst.query("*IDN?").strip()
        except Exception:
            return ""

    def close(self):
        """Close the underlying VISA resource."""
        try:
            self.inst.close()
        except Exception:
            pass


class VisaConnector:
    """Core scanner/connector with no UI and no simulation."""
    def __init__(self):
        self.rm: Optional[pyvisa.ResourceManager] = None
        self.scanned_resources: List[str] = []
        self.sessions: Dict[str, Dict] = {}

    # -------- scanning --------
    def scan_resources(self) -> List[str]:
        """Scan VISA resources and store the result."""
        try:
            self.rm = self.rm or pyvisa.ResourceManager()
            self.scanned_resources = list(self.rm.list_resources())
            return self.scanned_resources
        except Exception as e:
            print(f"[SCAN][ERROR] {e}", file=sys.stderr)
            self.scanned_resources = []
            return self.scanned_resources

    # -------- connection helpers --------
    def _try_open_serial(self, resource_key: str) -> Tuple[Optional[VisaDevice], str]:
        """
        Attempt to open an ASRL resource by sweeping common baud rates and terminations.
        Returns (VisaDevice, idn) on success, (None, "") on failure.
        """
        self.rm = self.rm or pyvisa.ResourceManager()

        # Common serial settings to probe
        baud_candidates = [115200, 38400, 19200, 9600]
        term_candidates = [("\r\n", "\n"), ("\n", "\n"), ("\r", "\r"), ("\r\n", "\r\n")]

        # Try opening quickly; some adapters can block on initial open
        try:
            inst = self.rm.open_resource(resource_key)
        except Exception:
            return None, ""

        # Use short timeouts to accelerate probing
        try:
            inst.timeout = 500
            inst.write_timeout = 500
        except Exception:
            pass

        # Typical serial framing; ignore if backend does not expose attributes
        try:
            inst.data_bits = 8
            inst.parity = getattr(pv.Parity, "none", 0)
            inst.stop_bits = getattr(pv.StopBits, "one", 10)
            if hasattr(inst, "rtscts"):
                inst.rtscts = False
            if hasattr(inst, "xonxoff"):
                inst.xonxoff = False
        except Exception:
            pass

        # Try to clear buffers
        try:
            inst.clear()
        except Exception:
            pass

        for baud in baud_candidates:
            try:
                if hasattr(inst, "baud_rate"):
                    inst.baud_rate = baud
            except Exception:
                pass

            for wterm, rterm in term_candidates:
                try:
                    if hasattr(inst, "write_termination"):
                        inst.write_termination = wterm
                    if hasattr(inst, "read_termination"):
                        inst.read_termination = rterm

                    # Nudge device if needed
                    try:
                        inst.write("")
                    except Exception:
                        pass

                    # Probe *IDN?
                    try:
                        idn = inst.query("*IDN?").strip()
                    except Exception:
                        idn = ""

                    if idn:
                        return VisaDevice(inst), idn
                except Exception:
                    # Move to next combination
                    continue

        # Give up and close
        try:
            inst.close()
        except Exception:
            pass
        return None, ""

    # -------- connect-all --------
    def connect_all(self) -> int:
        """
        Connect to all scanned resources and query *IDN?.
        Stores live sessions in self.sessions.
        Returns the count of successful connections.
        """
        if not self.scanned_resources:
            print("[CONNECT] No resources to connect. Run scan_resources() first.", file=sys.stderr)
            return 0

        connected_count = 0

        for resource_key in self.scanned_resources:
            if resource_key in self.sessions:
                # Already connected
                continue

            try:
                if resource_key.upper().startswith("ASRL"):
                    # Serial-specific probing
                    dev, idn = self._try_open_serial(resource_key)
                    if dev is None:
                        print(f"[CONNECT][ERROR] {resource_key}: no response on serial (tried common settings)")
                        continue
                else:
                    # USB/GPIB/TCPIP etc. Typical defaults generally work
                    self.rm = self.rm or pyvisa.ResourceManager()
                    inst = self.rm.open_resource(resource_key)

                    try:
                        inst.timeout = 1000
                        inst.write_timeout = 1000
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

                    dev = VisaDevice(inst)
                    idn = dev.idn()

                self.sessions[resource_key] = {
                    "device": dev,
                    "idn": idn,
                }
                print(f"[CONNECT][OK] {resource_key} -> {idn if idn else '(no IDN response)'}")
                connected_count += 1

            except Exception as e:
                print(f"[CONNECT][ERROR] {resource_key}: {e}", file=sys.stderr)

        return connected_count

    # -------- teardown --------
    def close_all(self):
        """Close all live VISA sessions."""
        for key, sess in list(self.sessions.items()):
            try:
                dev: VisaDevice = sess.get("device")
                if dev:
                    dev.close()
            except Exception:
                pass
        self.sessions.clear()


def main():
    """CLI entry point: scan, list, connect, and print results."""
    vc = VisaConnector()

    print("[SCAN] Listing VISA resources...")
    resources = vc.scan_resources()
    if not resources:
        print("[SCAN] No VISA resources found.")
        return

    for r in resources:
        print(f"  - {r}")

    print("\n[CONNECT] Opening all resources and querying *IDN? ...")
    count = vc.connect_all()
    print(f"[CONNECT] Completed. Connected {count} device(s).")

    # Optional: keep the process alive if you need to interact further.
    # For now, we close immediately.
    vc.close_all()
    print("[CLOSE] All sessions closed.")


if __name__ == "__main__":
    main()
