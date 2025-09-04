"""
Experiment (TIME DOMAIN):
- Power supply: Rohde & Schwarz HMP4040 (VISA: ASRL3::INSTR), CH1 at 2.8 / 3.8 / 4.8 V, current limit 1 A
- Counter: Keysight 53230A (VISA: USB0::0x0957::0x1907::MY50002864::INSTR)
- Measure *period* statistics with Statistics Count = 3000
- Print Mean, Stdev, Min, Max, Peak-to-Peak for each supply voltage
"""

import time
import pyvisa
from pyvisa.constants import StopBits, Parity

# ========= User-configurable =========
HMP_VISA = "ASRL3::INSTR"  # R&S HMP4040 (RS-232)
COUNTER_VISA = "USB0::0x0957::0x1907::MY50002864::INSTR"  # Keysight 53230A
VOLTAGES = [2.8, 3.8, 4.8]  # V
CURRENT_LIMIT_A = 1.0       # A
SAMPLES = 3000              # Statistics sample count
GATE_TIME_S = 0.010         # Gate time (still used for period mode on 53230A)
POLL_INTERVAL_S = 0.2       # Progress polling interval
SETTLING_S = 0.5            # Supply settling time after voltage change
# ====================================

def open_hmp(rm):
    h = rm.open_resource(HMP_VISA)
    # Recommended serial settings for R&S supplies (adjust if your setup differs)
    h.baud_rate = 9600
    h.data_bits = 8
    h.stop_bits = StopBits.one
    h.parity = Parity.none
    h.read_termination = '\n'
    h.write_termination = '\n'
    h.timeout = 10000
    return h

def setup_hmp_channel1(h, voltage, current_limit):
    # Select channel 1 and apply V/I in one shot; then turn output ON
    h.write("*CLS")
    # h.write("*RST")  # optional global reset

    h.write("INST:NSEL 1")              # Select CH1
    h.write(f"APPL {voltage},{current_limit}")  # Set V and I (A)
    h.write("OUTP ON")                  # Enable CH1 output

def power_off_hmp_channel1(h):
    try:
        h.write("INST:NSEL 1")
        h.write("OUTP OFF")
    except Exception:
        pass

def open_counter(rm):
    c = rm.open_resource(COUNTER_VISA)
    c.timeout = 120000   # up to 120 s for 3000 samples depending on signal conditions
    c.read_termination = '\n'
    c.write_termination = '\n'
    return c

def setup_counter_for_period_stats(counter):
    # Always start from a known state
    counter.write("*RST")
    counter.write("*CLS")
    idn = counter.query("*IDN?").strip()
    print("Counter IDN:", idn)

    # Configure *period* measurement on Channel 1
    # Per Keysight 53230A SCPI: CONFigure:PERiod [,...][,<channel>]
    counter.write("CONF:PER (@1)")

    # (Optional) explicit gate time; valid in this stats setup
    counter.write(f"SENS:FREQ:GATE:TIME {GATE_TIME_S}")

    # Enable statistics in the CALCulate subsystem
    counter.write("CALC:STAT ON")         # Enable CALCulate1
    counter.write("CALC:AVER:STAT ON")    # Enable statistics
    counter.write("CALC:AVER:CLE")        # Clear previous stats

    # Define number of readings
    counter.write(f"SAMP:COUN {SAMPLES}")

def run_measurement_with_progress(counter):
    # Initiate and poll reading memory count to show progress until we reach SAMPLES
    print("Starting measurement...")
    counter.write("INIT")

    last_print_len = 0
    while True:
        # DATA:POINts? returns number of readings currently in reading memory
        try:
            pts = int(float(counter.query("DATA:POIN?")))
        except Exception:
            # Some firmware uses DATA:POINts? (long form). Try that if short form fails.
            pts = int(float(counter.query("DATA:POINts?")))
        if pts > SAMPLES:
            pts = SAMPLES

        pct = 100.0 * pts / SAMPLES
        bar_len = 40
        filled = int(bar_len * pts / SAMPLES)
        bar = "[" + "#" * filled + "-" * (bar_len - filled) + f"] {pts}/{SAMPLES} ({pct:5.1f}%)"
        # overwrite one line
        print("Progress " + bar + " ", end="\r")
        last_print_len = max(last_print_len, len(bar))

        if pts >= SAMPLES:
            print()  # newline after finishing
            break

        time.sleep(POLL_INTERVAL_S)

    # Query statistics: mean, stdev, min, max
    stats = counter.query("CALC:AVER:ALL?").strip()
    mean, stdev, vmin, vmax = map(float, stats.split(",")[:4])

    # Query peak-to-peak (range)
    ptp = float(counter.query("CALC:AVER:PTP?"))

    return mean, stdev, vmin, vmax, ptp

def main():
    rm = pyvisa.ResourceManager()
    print("VISA resources:", rm.list_resources())

    hmp = None
    counter = None
    try:
        # Open instruments
        print("Opening HMP4040...")
        hmp = open_hmp(rm)
        print("HMP IDN:", hmp.query("*IDN?").strip())

        print("Opening 53230A counter...")
        counter = open_counter(rm)
        print("53230A opened.")

        results = []

        for v in VOLTAGES:
            print(f"\n=== Supply {v:.1f} V, ILIM {CURRENT_LIMIT_A:.3f} A ===")
            # Set PSU
            setup_hmp_channel1(hmp, v, CURRENT_LIMIT_A)
            print("Waiting for supply to settle...")
            time.sleep(SETTLING_S)

            # Configure counter & run (PERIOD mode)
            setup_counter_for_period_stats(counter)
            mean, stdev, vmin, vmax, ptp = run_measurement_with_progress(counter)

            print("Results (Time Domain - Period):")
            print(f"  Mean   : {mean} s")
            print(f"  Stdev  : {stdev} s")
            print(f"  Min    : {vmin} s")
            print(f"  Max    : {vmax} s")
            print(f"  Pk-Pk  : {ptp} s")

            results.append((v, mean, stdev, vmin, vmax, ptp))

        # Summary
        print("\n=== Summary (Period) ===")
        for v, mean, stdev, vmin, vmax, ptp in results:
            print(f"{v:.1f} V -> Mean={mean} s, Stdev={stdev} s, Min={vmin} s, Max={vmax} s, Pk-Pk={ptp} s")

    finally:
        # Safe power-down
        if hmp is not None:
            print("Turning off HMP CH1 output...")
            power_off_hmp_channel1(hmp)
            try:
                hmp.close()
            except Exception:
                pass
        if counter is not None:
            try:
                counter.close()
            except Exception:
                pass
        try:
            rm.close()
        except Exception:
            pass

if __name__ == "__main__":
    main()
