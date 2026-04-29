import os

dll_path = r"wda_unblocker.dll"
header_path = r"wda_bytes.h"

if not os.path.exists(dll_path):
    print(f"Error: {dll_path} not found!")
    exit(1)

with open(dll_path, "rb") as f:
    data = f.read()

with open(header_path, "w") as f:
    f.write("// Auto-generated from wda_unblocker.dll\n")
    f.write("unsigned char wda_dll_bytes[] = {\n")
    for i in range(0, len(data), 12):
        chunk = data[i:i+12]
        hex_chunk = ", ".join([f"0x{b:02x}" for b in chunk])
        f.write(f"    {hex_chunk},\n")
    f.write("};\n")
    f.write(f"unsigned int wda_dll_len = {len(data)};\n")

print(f"Successfully converted {len(data)} bytes to {header_path}")
