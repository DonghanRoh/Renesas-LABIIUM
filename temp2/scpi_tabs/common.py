# scpi_tabs/common.py
import re

def trim(s: str) -> str:
    return (s or "").strip()

def extract_number(s: str) -> str:
    m = re.search(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", s or "")
    return m.group(0) if m else (s or "")

def try_sequences(inst, sequences):
    """Write-only sequence attempts. Each element is a list of write commands."""
    last_err = None
    for seq in sequences:
        try:
            for cmd in seq:
                inst.write(cmd)
            return True
        except Exception as e:
            last_err = e
    if last_err:
        raise last_err
    return False

def drain_error_queue(inst, log_fn, prefix="[SCPI]"):
    """Best-effort SYST:ERR? drain (up to 10)."""
    try:
        for _ in range(10):
            err = trim(inst.query("SYST:ERR?"))
            log_fn(f"{prefix} SYST:ERR? -> {err}")
            if err.startswith("0") or err.upper().startswith("+0") or "NO ERROR" in err.upper():
                break
    except Exception:
        pass

# ---- Model detection helpers ----
def detect_psu_model(idn: str) -> str:
    s = (idn or "").upper()
    if "HMP4040" in s: return "HMP4040"
    if "HMP4030" in s: return "HMP4030"
    if "E3631A"  in s: return "E3631A"
    if "E3633A"  in s: return "E3633A"
    if "HM8143"  in s: return "HM8143"
    return ""

def psu_channel_values(model: str):
    if model == "HMP4040": return ["1", "2", "3", "4"]
    if model == "HMP4030": return ["1", "2", "3"]
    if model == "E3631A":  return ["P6V", "P25V", "N25V"]
    if model == "E3633A":  return ["OUT"]
    if model == "HM8143":  return ["U1", "U2"]
    return []

def psu_select_channel(inst, model: str, channel: str):
    if model in ("HMP4040", "HMP4030"):
        inst.write(f"INST:NSEL {channel}")
    elif model == "E3631A":
        inst.write(f"INST:SEL {channel}")
    elif model in ("E3633A", "HM8143"):
        return
    else:
        raise RuntimeError("Unsupported PSU model for channel selection.")

def hm8143_ch_index(ch: str) -> str:
    c = (ch or "").strip().upper()
    if c == "U1": return "1"
    if c == "U2": return "2"
    raise RuntimeError("HM8143 supports only U1/U2 for set/query.")

def is_supported_dmm(idn: str) -> bool:
    s = (idn or "").upper()
    if "HMP4040" in s:  # avoid false-positive with '4040'
        s = s.replace("HMP4040", "")
    targets = ["34410A", "34461A", "4040", "34465A", "34470A", "2000", "3458A"]
    return any(t in s for t in targets)

def is_supported_smu(idn: str) -> bool:
    s = (idn or "").upper()
    targets = ["MODEL 2420", "MODEL 2440", "MODEL 2450", "MODEL 2460", "MODEL 2461"]
    return any(t in s for t in targets)

def is_supported_fgen(idn: str) -> bool:
    s = (idn or "").upper()
    return ("33250A" in s) or ("33612A" in s)
