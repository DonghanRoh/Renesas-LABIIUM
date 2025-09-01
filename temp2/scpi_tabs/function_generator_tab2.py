# scpi_tabs/function_generator_tab.py
import tkinter as tk
from tkinter import ttk, messagebox
from . import common
import re

# ---------- helpers ----------
_SI = {
    "G": 1e9, "M": 1e6, "k": 1e3,
    "": 1.0,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9
}

def _parse_number_with_unit(label: str, kind: str):
    """
    Convert dropdown labels like '1 kHz', '100 mVpp', '10 ms', '90 °', '50 %', '1 MSa/s'
    into base units:
      kind in {'freq','srate','volt','offs','phase','time','percent','bitrate','band'}
    Returns float value in: Hz, Sa/s, V, V, deg, s, %, Hz, Hz respectively.
    """
    s = (label or "").strip()

    # Normalize special unit tokens
    s = s.replace("°", " deg")
    s = s.replace("Sa/s", "SPS")  # sample-per-second token
    s = s.replace("Vpp", " Vpp")

    # Extract number and unit parts
    m = re.match(r"^\s*([-+]?\d*\.?\d+)\s*([GMkmunµ]?)\s*([A-Za-z%]+)?\s*$", s)
    if not m:
        # fallback: just numeric
        try:
            return float(common.extract_number(s))
        except Exception:
            return 0.0

    val = float(m.group(1))
    pref = m.group(2) or ""
    unit = (m.group(3) or "").lower()

    mul = _SI.get(pref, 1.0)

    if kind in ("freq", "band", "bitrate"):
        # Hz-like
        if "hz" in unit:
            return val * mul
        return val
    if kind == "srate":
        # SPS from 'kSa/s' etc.
        if "sps" in unit:
            return val * mul
        return val
    if kind in ("volt", "offs"):
        # amplitude/offset in V or Vpp (we set VOLT as Vpp)
        # our labels are in Vpp for amplitude and V for offset
        return val * mul
    if kind == "phase":
        # degrees
        return val
    if kind == "time":
        # default seconds if unit absent
        # handle ms/us/ns in 'pref'
        if unit in ("s", "sec", "secs", "second", "seconds", ""):
            return val * mul
        return val
    if kind == "percent":
        return val
    return val

def _si_label(values, unit):
    """Helper to build labels like ['10 kHz', '1 MHz'] from numeric base-unit values."""
    out = []
    for v in values:
        abs_v = abs(v)
        if unit == "Hz" or unit == "SPS":
            if abs_v >= 1e6:
                out.append(f"{v/1e6:g} MHz" if unit=="Hz" else f"{v/1e6:g} MSa/s")
            elif abs_v >= 1e3:
                out.append(f"{v/1e3:g} kHz" if unit=="Hz" else f"{v/1e3:g} kSa/s")
            else:
                out.append(f"{v:g} Hz" if unit=="Hz" else f"{v:g} Sa/s")
        elif unit == "Vpp":
            if abs_v >= 1:
                out.append(f"{v:g} Vpp")
            else:
                out.append(f"{v*1e3:g} mVpp")
        elif unit == "V":
            if abs_v >= 1:
                out.append(f"{v:g} V")
            else:
                out.append(f"{v*1e3:g} mV")
        elif unit == "deg":
            out.append(f"{v:g} °")
        elif unit == "%":
            out.append(f"{v:g} %")
        elif unit == "s":
            if abs_v >= 1:
                out.append(f"{v:g} s")
            elif abs_v >= 1e-3:
                out.append(f"{v*1e3:g} ms")
            elif abs_v >= 1e-6:
                out.append(f"{v*1e6:g} µs")
            else:
                out.append(f"{v*1e9:g} ns")
        else:
            out.append(f"{v:g}")
    return out

class FunctionGeneratorTab:
    """
    Minimal 33612A UI:
      - Channel (1/2), Output (Off/On) — dropdowns
      - Waveform — dropdown
      - Parameters — per-waveform dropdowns (no free text)
    Removed: load/impedance, range, duty, units switching, read-back, 33250A support.
    """

    # Display names -> SCPI tokens
    WF_MAP = {
        "Sine": "SIN",
        "Square": "SQU",
        "Ramp": "RAMP",
        "Pulse": "PULS",
        "Arb": "ARB",
        "Triangle": "TRI",
        "Noise": "NOIS",
        "PRBS": "PRBS",
        "DC": "DC",
    }

    # Predefined parameter sets (base-unit values)
    PARAM_CHOICES = {
        "Sine": {
            "Frequency": _si_label([10, 100, 1e3, 10e3, 100e3, 1e6], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0, 2.0, 5.0, 10.0], "Vpp"),
            "Offset":    _si_label([-2.0, -1.0, 0.0, 1.0, 2.0], "V"),
            "Phase":     _si_label([0, 45, 90, 180], "deg"),
        },
        "Square": {
            "Frequency": _si_label([10, 100, 1e3, 10e3, 100e3, 1e6], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0, 2.0, 5.0, 10.0], "Vpp"),
            "Offset":    _si_label([-2.0, -1.0, 0.0, 1.0, 2.0], "V"),
            "Phase":     _si_label([0, 90, 180], "deg"),
        },
        "Ramp": {
            "Frequency": _si_label([10, 100, 1e3, 10e3, 100e3], "Hz"),
            "Amplitude": _si_label([0.1, 0.5, 1.0, 2.0, 5.0], "Vpp"),
            "Offset":    _si_label([-1.0, 0.0, 1.0], "V"),
            "Phase":     _si_label([0, 90, 180], "deg"),
            "Symmetry":  _si_label([10, 25, 50, 75, 90], "%"),
        },
        "Pulse": {
            "Frequency":   _si_label([10, 100, 1e3, 10e3, 100e3], "Hz"),
            "Amplitude":   _si_label([0.1, 0.5, 1.0, 2.0, 5.0], "Vpp"),
            "Offset":      _si_label([-1.0, 0.0, 1.0], "V"),
            "Phase":       _si_label([0, 90, 180], "deg"),
            "Pulse Width": _si_label([1e-6, 10e-6, 100e-6, 1e-3, 10e-3], "s"),
            "Lead Edge":
