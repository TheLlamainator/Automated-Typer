# clean_and_type.py
import os
import sys
import time
import unicodedata
import pyautogui

IS_MAC = sys.platform == "darwin"


INPUT_FILE = "text.txt"
DEFAULT_WPS = 40.0            # words per second
DEFAULT_DELAY = 5.0           # seconds
DEFAULT_RETURN_TOKEN = "[[KEY_RETURN]]"
DEFAULT_TAB_TOKEN = "[[KEY_TAB]]"

REPLACEMENTS = {
    # Dashes / hyphens
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
    # Quotes
    "\u2018": "'", "\u2019": "'", "\u201A": "'", "\u201B": "'", "\u2032": "'",
    "\u201C": '"', "\u201D": '"', "\u201E": '"', "\u201F": '"', "\u2033": '"', "\uFF02": '"',
    # Slashes
    "\u2215": "/", "\uFF0F": "/",
    # Dots
    "\u2024": ".", "\u2027": ".",
    # Spaces → normal space (keep counts; do NOT collapse)
    "\u00A0": " ", "\u1680": " ",  # NBSP, Ogham space mark
    "\u2000": " ", "\u2001": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ",
    "\u2005": " ", "\u2006": " ", "\u2007": " ", "\u2008": " ", "\u2009": " ", "\u200A": " ",
    "\u202F": " ", "\u205F": " ", "\u3000": " ",
    # Confusable letters → ASCII
    "\u0430": "a",  # Cyrillic a
    "\u0435": "e",  # Cyrillic e
    "\u043E": "o",  # Cyrillic o
    "\u0440": "p",  # Cyrillic p
    "\u03B5": "e",  # Greek epsilon
}

DROP_CODEPOINTS = {
    # Zero-width / invisibles
    0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF,
    # Soft & invisible separators
    0x00AD, 0x2061, 0x2062, 0x2063, 0x2064,
    # Bidi controls
    0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069,
    # Other invisible / special
    0x180E,
    # Specials explicitly listed
    0xFFF9, 0xFFFA, 0xFFFB, 0xFFFC, 0xFFFD,
}

DROP_RANGES = [
    (0x0080, 0x009F),  # C1 controls
    (0xFE00, 0xFE0F),  # Variation selectors
    (0xE0100, 0xE01EF),  # Variation selectors extended
    (0x1F3FB, 0x1F3FF),  # Emoji skin tone modifiers
    (0x206A, 0x206F),  # more invisible formatting controls
]

# C0/DEL handled specially so we can convert LF/CR/TAB to tokens instead of dropping blindly
C0_START, C0_END = 0x0000, 0x001F
DEL = 0x007F

def _is_in_ranges(cp, ranges):
    for lo, hi in ranges:
        if lo <= cp <= hi:
            return True
    return False

def sanitize_text(original: str):
    """
    - NFKC normalize
    - Replace confusables/spaces (REPLACEMENTS)
    - Drop all disallowed controls/invisibles/formatting (per your list)
    - Keep raw \n, \r, \t for tokenizing later (not typed directly)
    Returns sanitized string + stats.
    """
    stats = {"replaced": {}, "dropped": {}}
    text = unicodedata.normalize("NFKC", original)

    out = []
    for ch in text:
        cp = ord(ch)

        # Handle C0 controls & DEL:
        if C0_START <= cp <= C0_END or cp == DEL:
            # Allow \n, \r, \t to pass through for token encoding; everything else is dropped
            if ch in ("\n", "\r", "\t"):
                out.append(ch)
            else:
                key = f"U+{cp:04X}"
                stats["dropped"][key] = stats["dropped"].get(key, 0) + 1
            continue

        # Drop by explicit sets/ranges
        if cp in DROP_CODEPOINTS or _is_in_ranges(cp, DROP_RANGES):
            key = f"U+{cp:04X}"
            stats["dropped"][key] = stats["dropped"].get(key, 0) + 1
            continue

        # Replace odd-but-visible characters
        if ch in REPLACEMENTS:
            repl = REPLACEMENTS[ch]
            stats["replaced"][ch] = stats["replaced"].get(ch, 0) + 1
            out.append(repl)
            continue

        # Keep as-is
        out.append(ch)

    # Normalize newline styles to '\n' (logical breaks) and keep '\t'
    s = "".join(out).replace("\r\n", "\n").replace("\r", "\n")
    return s, stats

def encode_tokens(s: str, return_token: str, tab_token: str):
    out = []
    count_return = 0
    count_tab = 0
    for ch in s:
        if ch == "\n":
            out.append(return_token)
            count_return += 1
        elif ch == "\t":
            out.append(tab_token)
            count_tab += 1
        else:
            out.append(ch)
    return "".join(out), count_return, count_tab

def mac_quartz_press(key_code, shift=False):
    if not IS_MAC:
        return False
    try:
        from Quartz import CGEventCreateKeyboardEvent, CGEventPost, kCGHIDEventTap
        from Quartz import kCGEventFlagMaskShift, CGEventSetFlags
        ev_down = CGEventCreateKeyboardEvent(None, key_code, True)
        if shift:
            CGEventSetFlags(ev_down, kCGEventFlagMaskShift)
        CGEventPost(kCGHIDEventTap, ev_down)
        ev_up = CGEventCreateKeyboardEvent(None, key_code, False)
        if shift:
            CGEventSetFlags(ev_up, kCGEventFlagMaskShift)
        CGEventPost(kCGHIDEventTap, ev_up)
        return True
    except Exception as e:
        print(f"[Quartz not available] {e}")
        return False

def press_return():
    # Prefer hardware-like Return on macOS, then fallback
    if IS_MAC and mac_quartz_press(36):  # 36 = Return
        return
    pyautogui.press("return")

def press_keypad_enter():
    if IS_MAC and mac_quartz_press(76):  # 76 = Keypad Enter
        return
    pyautogui.press("enter")

def exec_token(token: str):
    """
    Supported tokens:
      [[KEY_RETURN]], [[KEY_ENTER]], [[KEY_SHIFT_RETURN]],
      [[KEY_CTRL_RETURN]], [[KEY_ALT_RETURN]], [[KEY_TAB]]
      [[SLEEP:ms]]           e.g., [[SLEEP:250]]
      [[TYPE:literal text]]  force literal text
    Unknown tokens are typed literally.
    """
    t = token.strip()
    up = t.upper()

    # Timing token
    if up.startswith("SLEEP:"):
        try:
            ms = float(t.split(":", 1)[1])
            time.sleep(ms / 1000.0)
        except Exception:
            pyautogui.write(f"[[{token}]]", interval=0.0)
        return

    # Literal text
    if up.startswith("TYPE:"):
        literal = t.split(":", 1)[1]
        pyautogui.write(literal, interval=0.0)
        return

    # Keys
    if up == "KEY_RETURN":
        press_return(); return
    if up == "KEY_ENTER":
        press_keypad_enter(); return
    if up == "KEY_SHIFT_RETURN":
        pyautogui.keyDown("shift"); press_return(); pyautogui.keyUp("shift"); return
    if up == "KEY_CTRL_RETURN":
        pyautogui.keyDown("ctrl"); press_return(); pyautogui.keyUp("ctrl"); return
    if up == "KEY_ALT_RETURN":
        pyautogui.keyDown("alt"); press_return(); pyautogui.keyUp("alt"); return
    if up == "KEY_TAB":
        pyautogui.press("tab"); return

    # Unknown token → type literally
    pyautogui.write(f"[[{token}]]", interval=0.0)

def type_with_tokens(s: str, cps: float):
    i = 0
    delay = 1.0 / max(cps, 1e-6)
    while i < len(s):
        if s[i:i+2] == "[[":
            j = s.find("]]", i+2)
            if j != -1:
                token = s[i+2:j]
                exec_token(token)
                i = j + 2
                time.sleep(delay)
                continue
        pyautogui.write(s[i], interval=0.0)
        time.sleep(delay)
        i += 1


def main():
    # CLI: python clean_and_type.py [file] [wps] [delay] [return_token] [tab_token]
    infile = sys.argv[1] if len(sys.argv) > 1 else INPUT_FILE
    wps_cli = float(sys.argv[2]) if len(sys.argv) > 2 else None
    delay_cli = float(sys.argv[3]) if len(sys.argv) > 3 else None
    return_token_cli = sys.argv[4] if len(sys.argv) > 4 else None
    tab_token_cli = sys.argv[5] if len(sys.argv) > 5 else None

    if not os.path.exists(infile):
        print(f"Error: {infile} not found.")
        sys.exit(1)

    with open(infile, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    # 1) Sanitize
    safe_text, stats = sanitize_text(raw)

    # 2) Interactive config (WPS & delay & tokens) unless CLI overrides
    print("=== Auto Typer — Strong Cleaner + Token Typer ===")
    print(f"Loaded file: {infile}")

    # WPS
    if wps_cli is None:
        while True:
            try:
                wps_in = input(f"Typing speed (WPS, default {DEFAULT_WPS}, min 0.1): ").strip() or str(DEFAULT_WPS)
                wps = float(wps_in)
                if wps < 0.1:
                    print("Please enter a WPS of at least 0.1"); continue
                if wps > 200:
                    if input("WPS > 200 can be unstable. Proceed? (y/n): ").strip().lower() != "y":
                        continue
                break
            except ValueError:
                print("Please enter a valid number.")
    else:
        wps = wps_cli

    # Delay
    if delay_cli is None:
        while True:
            try:
                delay_in = input(f"Start delay in seconds (default {DEFAULT_DELAY}): ").strip() or str(DEFAULT_DELAY)
                start_delay = float(delay_in)
                if start_delay < 0:
                    print("Please enter a non-negative number."); continue
                break
            except ValueError:
                print("Please enter a valid number.")
    else:
        start_delay = delay_cli

    # Tokens
    default_return_token = return_token_cli or DEFAULT_RETURN_TOKEN
    default_tab_token = tab_token_cli or DEFAULT_TAB_TOKEN

    print("\nChoose newline token (what your app expects):")
    print("  [[KEY_RETURN]]       (default; mac Return)")
    print("  [[KEY_SHIFT_RETURN]] (chat apps often need this)")
    print("  [[KEY_ENTER]]        (numeric keypad Enter)")
    return_token = (input(f"Return token (press Enter for {default_return_token}): ").strip()
                    or default_return_token)

    tab_token = (input(f"Tab token (press Enter for {default_tab_token}): ").strip()
                 or default_tab_token)

    # 3) Encode logical keys as tokens
    encoded, encoded_returns, encoded_tabs = encode_tokens(safe_text, return_token, tab_token)

    # Report (what was replaced/dropped, and how many keys encoded)
    print("\n=== Cleaner Report ===")
    print(f"Replaced chars: {sum(stats['replaced'].values())}")
    if stats["replaced"]:
        for ch, cnt in sorted(stats["replaced"].items(), key=lambda x: -x[1]):
            cp = f"U+{ord(ch):04X}"
            name = ch if ch.strip() else "SPACE"
            print(f"  {cp} '{name}': {cnt} → replaced")
    print(f"Dropped chars: {sum(stats['dropped'].values())}")
    if stats["dropped"]:
        for cp, cnt in sorted(stats["dropped"].items(), key=lambda x: -x[1]):
            print(f"  {cp}: {cnt} → removed")
    print(f"Encoded returns: {encoded_returns}")
    print(f"Encoded tabs: {encoded_tabs}")

    # Confirm & start
    cps = max(0.5, wps * 5.0)  # ~5 chars per word
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.02

    print("\n=== Run Settings ===")
    print(f"File: {infile}")
    print(f"WPS: {wps}  (≈ CPS {cps:.1f})")
    print(f"Start delay: {start_delay} s")
    print(f"Return token: {return_token}")
    print(f"Tab token: {tab_token}")
    input("Press Enter to start... (click your target window after)")

    print(f"\nStarting in {start_delay} seconds...")
    time.sleep(start_delay)

    try:
        type_with_tokens(encoded, cps=cps)
        print("\nDone.")
    except KeyboardInterrupt:
        print("\nStopped by user.")

# Entry
if __name__ == "__main__":
    # macOS: ensure Accessibility for Terminal/IDE & Python in System Settings → Privacy & Security → Accessibility.
    main()
