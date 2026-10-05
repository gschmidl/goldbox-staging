"""fix_gamedat.py GBC_DIR - makes GBC's game IDs independent of the load address.

GBC finds each game in memory by its "1st ID", a byte pattern stored as hex
text in Games\\<game>\\Game.dat. For five games that pattern runs into far
calls (9A oooo ssss) whose segment words DOS relocates at load time, so it
only matched where DOSBox 0.74 happened to load the game. The pattern is cut
right after the first far call's offset, before the first relocated word.
The "2nd ID" (plain text at a fixed distance) is still checked by GBC.
Keeps Game.dat.orig.
"""
import os
import sys

ID1_OFF = 0x6D0  # Pascal string of hex digits

# game folder -> the relocation-free 1st ID it gets
FIXES = {
    "01. Pool of Radiance":
        b"\x05STING\x9a\x00\x00",
    "02. Curse of the Azure Bonds":
        b"\x05STING\x1eCurse of the Azure Bonds v1.3 \x09Play Demo\x9a\x00\x00",
    "05. Champions of Krynn":
        b"of Krynn v1.2\x09Play Demo\x17Champions Of Krynn v1.2\x9a\x00\x00",
    "11. Countdown to Doomsday":
        b"\x12Buck Rogers v1.00 \x09Play Demo\x9a\x00\x00",
    "12. Matrix Cubed":
        b"\x12Matrix Cubed v1.0 \x09Play Demo\x11Matrix Cubed v1.0\x9a\x00\x00",
}


def main(gbc_dir):
    for game, new in FIXES.items():
        path = os.path.join(gbc_dir, "Games", game, "Game.dat")
        data = bytearray(open(path, "rb").read())
        n = data[ID1_OFF]
        cur = bytes.fromhex(data[ID1_OFF + 1:ID1_OFF + 1 + n].decode("ascii"))
        if cur == new:
            print(f"{game}: already fixed")
            continue
        # the original continues with the relocated segment word
        assert cur.startswith(new) and len(cur) >= len(new) + 2, \
            f"{game}: unexpected 1st ID {cur!r}"
        if not os.path.exists(path + ".orig"):
            open(path + ".orig", "wb").write(data)
        text = new.hex().upper().encode("ascii")
        field = bytes([len(text)]) + text
        data[ID1_OFF:ID1_OFF + len(field)] = field
        data[ID1_OFF + len(field):ID1_OFF + 1 + n] = bytes(1 + n - len(field))
        open(path, "wb").write(data)
        print(f"{game}: 1st ID {len(cur)} -> {len(new)} bytes")


if __name__ == "__main__":
    main(sys.argv[1])
