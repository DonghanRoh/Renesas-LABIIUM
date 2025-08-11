import time
import pyvisa
from hmp4040 import hmp4040

rm = pyvisa.ResourceManager()

try:
    # Attempt to connect to the instrument
    hmp4040_ps = rm.open_resource('ASRL6::INSTR')
    
    # Connection check: get instrument ID
    idn_response = hmp4040_ps.query('*IDN?').strip()
    print(f"[INFO] Connection successful: {idn_response}")

except Exception as e:
    print(f"[ERROR] Failed to connect to instrument: {e}")
    exit(1)

# Initialize hmp4040 class
hmp4040 = hmp4040(pyvisa_instr=hmp4040_ps)

# Read current unique settings
current_setting_list = hmp4040.get_unique_scpi_list()

# Reset the instrument
print("[INFO] Resetting instrument...")
hmp4040_ps.write('*RST')
time.sleep(2)

# Restore unique settings
print("[INFO] Restoring unique settings...")
for scpi_cmd in current_setting_list:
    hmp4040_ps.write(scpi_cmd)
time.sleep(2)

print("[INFO] Settings restoration complete.")
