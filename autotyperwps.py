import os
import sys
import time
import unicodedata
import pyautogui
import random
import math
from typing import Optional

IS_MAC = sys.platform == "darwin"

INPUT_FILE = "text.txt"
DEFAULT_WPS = 40.0            # words per second (used to compute baseline CPS; human drift added on top)
DEFAULT_DELAY = 5.0           # seconds
DEFAULT_RETURN_TOKEN = "[[KEY_RETURN]]"  # kept for UI, but NOT used to encode text
DEFAULT_TAB_TOKEN = "[[KEY_TAB]]"        # kept for UI, but NOT used to encode text
DEFAULT_TYPO_RATE = 0.07      # target average error rate (geometric spacing)

# --- Human-like timing knobs ---
AR_DRIFT = 0.35
LOGN_MU_SHIFT = -0.03
LOGN_SIGMA = 0.20
BACKSPACE_FACTOR = 0.65

# Pauses
PUNCT_PAUSE_PROB = 0.25
PUNCT_PAUSE_MS = (140, 360)
SENTENCE_PAUSE_MS = (600, 1100)
PARAGRAPH_PAUSE_MS = (800, 1500)
THINK_PAUSE_PROB = 0.06
THINK_PAUSE_MS = (280, 900)
SPACE_EXTRA_DELAY_MS = (0, 220)

# Burst/pause state
BURST_WORDS_RANGE = (4, 9)
BURST_PAUSE_MS = (380, 760)

# Word-level behaviours
MIDWORD_HESITATION_PROB = 0.05
MIDWORD_MINLEN = 6
MIDWORD_HESITATION_MS = (200, 450)

# Corrections
HESITATION_PROB = 0.25
HESITATION_MS = (80, 220)
MULTI_CORR_PROB = 0.012
MULTI_CORR_MIN = 2
MULTI_CORR_MAX = 3
SHIFT_SLIP_PROB = 0.006

def _geom_p_from_target_rate(rate: float) -> float:
    rate = max(1e-4, min(0.9, rate))
    return rate

REPLACEMENTS = {
    "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-", "\u2212": "-",
    "\u2018": "'", "\u2019": "'", "\u201A": "'", "\u201B": "'", "\u2032": "'",
    "\u201C": '"', "\u201D": '"', "\u201E": '"', "\u201F": '"', "\u2033": '"', "\uFF02": '"',
    "\u2215": "/", "\uFF0F": "/",
    "\u2024": ".", "\u2027": ".",
    "\u00A0": " ", "\u1680": " ",
    "\u2000": " ", "\u2001": " ", "\u2002": " ", "\u2003": " ", "\u2004": " ",
    "\u2005": " ", "\u2006": " ", "\u2007": " ", "\u2008": " ", "\u2009": " ", "\u200A": " ",
    "\u202F": " ", "\u205F": " ", "\u3000": " ",
    "\u0430": "a", "\u0435": "e", "\u043E": "o", "\u0440": "p", "\u03B5": "e",
}

DROP_CODEPOINTS = {
    0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF,
    0x00AD, 0x2061, 0x2062, 0x2063, 0x2064,
    0x200E, 0x200F, 0x202A, 0x202B, 0x202C, 0x202D, 0x202E, 0x2066, 0x2067, 0x2068, 0x2069,
    0x180E, 0xFFF9, 0xFFFA, 0xFFFB, 0xFFFC, 0xFFFD,
}
DROP_RANGES = [
    (0x0080, 0x009F),
    (0xFE00, 0xFE0F),
    (0xE0100, 0xE01EF),
    (0x1F3FB, 0x1F3FF),
    (0x206A, 0x206F),
]

C0_START, C0_END = 0x0000, 0x001F
DEL = 0x007F

def _is_in_ranges(cp, ranges):
    for lo, hi in ranges:
        if lo <= cp <= hi:
            return True
    return False

def sanitize_text(original: str):
    stats = {"replaced": {}, "dropped": {}}
    text = unicodedata.normalize("NFKC", original)
    out = []
    for ch in text:
        cp = ord(ch)
        if C0_START <= cp <= C0_END or cp == DEL:
            if ch in ("\n", "\r", "\t"):
                out.append(ch)
            else:
                key = f"U+{cp:04X}"
                stats["dropped"][key] = stats["dropped"].get(key, 0) + 1
            continue
        if cp in DROP_CODEPOINTS or _is_in_ranges(cp, DROP_RANGES):
            key = f"U+{cp:04X}"
            stats["dropped"][key] = stats["dropped"].get(key, 0) + 1
            continue
        if ch in REPLACEMENTS:
            repl = REPLACEMENTS[ch]
            stats["replaced"][ch] = stats["replaced"].get(ch, 0) + 1
            out.append(repl)
            continue
        out.append(ch)
    s = "".join(out).replace("\r\n", "\n").replace("\r", "\n")
    return s, stats

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
    if IS_MAC and mac_quartz_press(36):  # Return
        return
    pyautogui.press("return")

def press_keypad_enter():
    if IS_MAC and mac_quartz_press(76):  # Keypad Enter
        return
    pyautogui.press("enter")

def exec_token(token: str):
    # still support external [[...]] tokens if they exist in your source
    t = token.strip(); up = t.upper()
    if up.startswith("SLEEP:"):
        try:
            ms = float(t.split(":", 1)[1]); time.sleep(ms/1000.0)
        except Exception:
            pyautogui.write(f"[[{token}]]", interval=0.0)
        return
    if up.startswith("TYPE:"):
        literal = t.split(":", 1)[1]; pyautogui.write(literal, interval=0.0); return
    if up == "KEY_RETURN": press_return(); return
    if up == "KEY_ENTER":  press_keypad_enter(); return
    if up == "KEY_SHIFT_RETURN":
        pyautogui.keyDown("shift"); press_return(); pyautogui.keyUp("shift"); return
    if up == "KEY_CTRL_RETURN":
        pyautogui.keyDown("ctrl"); press_return(); pyautogui.keyUp("ctrl"); return
    if up == "KEY_ALT_RETURN":
        pyautogui.keyDown("alt"); press_return(); pyautogui.keyUp("alt"); return
    if up == "KEY_TAB": pyautogui.press("tab"); return
    pyautogui.write(f"[[{token}]]", interval=0.0)

# ---- Humanisation helpers ----
KEY_NEIGHBORS = {
    "1": ["2", "q"], "2": ["1", "3", "q", "w"], "3": ["2", "4", "w", "e"], "4": ["3", "5", "e", "r"],
    "5": ["4", "6", "r", "t"], "6": ["5", "7", "t", "y"], "7": ["6", "8", "y", "u"], "8": ["7", "9", "u", "i"],
    "9": ["8", "0", "i", "o"], "0": ["9", "-", "o", "p"], "-": ["0", "=", "p"], "=": ["-", "["],
    "q": ["1", "2", "w", "a"], "w": ["2", "3", "q", "e", "a", "s"], "e": ["3", "4", "w", "r", "s", "d"],
    "r": ["4", "5", "e", "t", "d", "f"], "t": ["5", "6", "r", "y", "f", "g"],
    "y": ["6", "7", "t", "u", "g", "h"], "u": ["7", "8", "y", "i", "h", "j"],
    "i": ["8", "9", "u", "o", "j", "k"], "o": ["9", "0", "i", "p", "k", "l"],
    "p": ["0", "-", "o", "[", "l", ";"], "[": ["p", "]", ";"], "]": ["[", "\\"],
    "a": ["q", "w", "s", "z"], "s": ["w", "e", "a", "d", "z", "x"], "d": ["e", "r", "s", "f", "x", "c"],
    "f": ["r", "t", "d", "g", "c", "v"], "g": ["t", "y", "f", "h", "v", "b"],
    "h": ["y", "u", "g", "j", "b", "n"], "j": ["u", "i", "h", "k", "n", "m"],
    "k": ["i", "o", "j", "l", "m", ","], "l": ["o", "p", "k", ";", ",", "."],
    ";": ["p", "[", "l", "'", ".", "/"], "'": [";", "]", "/"],
    "z": ["a", "s", "x"], "x": ["s", "d", "z", "c"], "c": ["d", "f", "x", "v"],
    "v": ["f", "g", "c", "b"], "b": ["g", "h", "v", "n"], "n": ["h", "j", "b", "m"],
    "m": ["j", "k", "n", ","], ",": ["m", "k", ".", "l"], ".": [",", "l", "/",";"], "/": [".", ";", "'","\\"],
    "\\": ["]", "/"]
}
PUNCT_SET = set(",.;:!?")

def _eligible_for_typo(ch: str) -> bool:
    if ch in ("\n", "\r", "\t", " "): return False
    base = ch.lower()
    return base in KEY_NEIGHBORS or ch.isalpha()

def _neighbor_for(ch: str) -> Optional[str]:
    base = ch.lower()
    opts = KEY_NEIGHBORS.get(base)
    if not opts: return None
    wrong = random.choice(opts)
    return wrong.upper() if ch.isupper() else wrong

def _lognormal_delay(base_delay: float, state):
    last = state["ln_last"]
    ln = LOGN_MU_SHIFT + AR_DRIFT * last + random.gauss(0, LOGN_SIGMA)
    state["ln_last"] = ln
    mult = math.exp(ln)
    return max(0.0, base_delay * mult)

def _maybe_pause_after(ch: Optional[str]):
    if ch and ch in PUNCT_SET and random.random() < PUNCT_PAUSE_PROB:
        time.sleep(random.uniform(*PUNCT_PAUSE_MS)/1000.0)

def _maybe_sentence_pause(prev: Optional[str], ch: str, nxt: Optional[str]):
    if ch in ".?!" and (nxt == " " or nxt == "\n" or nxt is None):
        time.sleep(random.uniform(*SENTENCE_PAUSE_MS)/1000.0)

def _maybe_paragraph_pause(prev2: Optional[str], prev1: Optional[str], ch: str):
    if prev2 == "\n" and prev1 == "\n":
        time.sleep(random.uniform(*PARAGRAPH_PAUSE_MS)/1000.0)

def _space_extra_delay():
    extra = random.uniform(*SPACE_EXTRA_DELAY_MS)/1000.0
    if extra > 0: time.sleep(extra)

def _is_sentence_start(history_tail: str) -> bool:
    if not history_tail: return True
    return history_tail.endswith(". ") or history_tail.endswith("? ") or history_tail.endswith("! ") or history_tail.endswith("\n")

def type_with_tokens(s: str, cps: float, newline_mode: str, typo_rate: float = 0.0):
    """
    newline_mode: 'RETURN' | 'SHIFT_RETURN' | 'ENTER'
    """
    i = 0
    base_delay = 1.0 / max(cps, 1e-6)
    ln_state = {"ln_last": 0.0}

    words_since_burst = 0
    next_burst_after = random.randint(*BURST_WORDS_RANGE)
    in_word = False
    current_word_len = 0

    p_err = _geom_p_from_target_rate(max(0.0001, min(0.5, typo_rate)))
    def draw_gap(p):
        u = random.random()
        return max(1, int(math.ceil(math.log(1 - u) / math.log(1 - p))))
    next_error_in = draw_gap(p_err)

    hist_chars = []
    def push_hist(ch):
        hist_chars.append(ch)
        if len(hist_chars) > 200:
            del hist_chars[:len(hist_chars)-200]

    def hist_tail(n):
        return "".join(hist_chars[-n:]) if hist_chars else ""

    def _type_char(ch: str, backspace_speed=False):
        delay = _lognormal_delay(base_delay, ln_state)
        time.sleep(delay * (BACKSPACE_FACTOR if backspace_speed else 1.0))
        pyautogui.write(ch, interval=0.0)

    def _press_backspace(n=1):
        for _ in range(n):
            delay = _lognormal_delay(base_delay, ln_state)
            time.sleep(delay * BACKSPACE_FACTOR)
            pyautogui.press("backspace")

    def _press_newline():
        if newline_mode == "SHIFT_RETURN":
            pyautogui.keyDown("shift"); press_return(); pyautogui.keyUp("shift")
        elif newline_mode == "ENTER":
            press_keypad_enter()
        else:
            press_return()

    def _hesitate():
        if random.random() < HESITATION_PROB:
            time.sleep(random.uniform(*HESITATION_MS)/1000.0)

    def _end_word_boundary(just_typed: Optional[str]):
        nonlocal words_since_burst, next_burst_after, in_word, current_word_len
        if just_typed and (just_typed in (" ", "\n") or just_typed in PUNCT_SET):
            if in_word:
                words_since_burst += 1
                in_word = False
                current_word_len = 0
                if words_since_burst >= next_burst_after:
                    time.sleep(random.uniform(*BURST_PAUSE_MS)/1000.0)
                    words_since_burst = 0
                    next_burst_after = random.randint(*BURST_WORDS_RANGE)

    while i < len(s):
        # Handle embedded control tokens (if your file already contains [[...]])
        if s[i:i+2] == "[[":
            j = s.find("]]", i+2)
            if j != -1:
                token = s[i+2:j]
                exec_token(token)
                i = j + 2
                continue

        ch = s[i]
        nxt = s[i+1] if (i+1) < len(s) else None
        prev1 = hist_chars[-1] if hist_chars else None
        prev2 = hist_chars[-2] if len(hist_chars) >= 2 else None

        # Directly handle newlines and tabs (CRITICAL FIX)
        if ch == "\n":
            _press_newline()
            push_hist("\n")
            i += 1
            _maybe_paragraph_pause(prev2, prev1, "\n")
            continue
        if ch == "\t":
            pyautogui.press("tab")
            push_hist("\t")
            i += 1
            continue

        # word state
        if ch.isalnum():
            if not in_word:
                in_word = True
                current_word_len = 0
            current_word_len += 1
        else:
            in_word = False
            current_word_len = 0

        _maybe_paragraph_pause(prev2, prev1, ch)
        _maybe_sentence_pause(prev1, ch, nxt)

        if ch.isalpha() and ch.isupper() and _is_sentence_start(hist_tail(2)) and random.random() < SHIFT_SLIP_PROB:
            low = ch.lower()
            _type_char(low); push_hist(low)
            _hesitate()
            _press_backspace(1)
            _type_char(ch); push_hist(ch)
            i += 1
            _end_word_boundary(ch)
            _maybe_pause_after(ch)
            if ch == " ": _space_extra_delay()
            continue

        # error decision
        do_error = False
        err_kind = None
        if _eligible_for_typo(ch) and next_error_in <= 1:
            long_word_boost = 1.4 if current_word_len >= MIDWORD_MINLEN else 1.0
            if random.random() < min(1.0, long_word_boost * 0.85):
                do_error = True
                r = random.random()
                if r < 0.20 and nxt and _eligible_for_typo(nxt) and nxt not in " \n\t" and s[i+1:i+3] != "]]":
                    err_kind = "transpose"
                elif r < 0.35:
                    err_kind = "sticky"
                else:
                    err_kind = "neighbor"

        if do_error:
            next_error_in = draw_gap(p_err)
            if err_kind == "transpose":
                a, b = ch, nxt
                _type_char(b); push_hist(b)
                _type_char(a); push_hist(a)
                _hesitate()
                _press_backspace(2)
                _type_char(a); push_hist(a)
                _type_char(b); push_hist(b)
                i += 2
                _end_word_boundary(b)
                _maybe_pause_after(b)
                if b == " ": _space_extra_delay()
                continue
            elif err_kind == "sticky":
                _type_char(ch); push_hist(ch)
                _type_char(ch); push_hist(ch)
                _hesitate()
                _press_backspace(1)
                i += 1
                _end_word_boundary(ch)
                _maybe_pause_after(ch)
                if ch == " ": _space_extra_delay()
                continue
            else:
                wrong = _neighbor_for(ch)
                if wrong:
                    _type_char(wrong); push_hist(wrong)
                    _hesitate()
                    _press_backspace(1)
                    _type_char(ch); push_hist(ch)
                    i += 1
                    _end_word_boundary(ch)
                    _maybe_pause_after(ch)
                    if ch == " ": _space_extra_delay()
                    continue

        if _eligible_for_typo(ch):
            next_error_in -= 1

        if in_word and current_word_len >= MULTI_CORR_MIN and random.random() < MULTI_CORR_PROB:
            _type_char(ch); push_hist(ch); i += 1
            n = random.randint(MULTI_CORR_MIN, min(MULTI_CORR_MAX, current_word_len))
            _hesitate()
            _press_backspace(n)
            start = max(0, i - n)
            for k in range(start, i):
                c2 = s[k]
                if c2 == "[" and s[k:k+2] == "[[": break
                _type_char(c2); push_hist(c2)
            _end_word_boundary(c2 if n > 0 else None)
            _maybe_pause_after(c2 if n > 0 else None)
            if c2 == " ": _space_extra_delay()
            continue

        if in_word and current_word_len >= MIDWORD_MINLEN and random.random() < MIDWORD_HESITATION_PROB:
            time.sleep(random.uniform(*MIDWORD_HESITATION_MS)/1000.0)

        _type_char(ch); push_hist(ch)
        i += 1

        _maybe_pause_after(ch)
        if ch == " ": _space_extra_delay()
        _end_word_boundary(ch)

def main():
    # CLI: python human_autotyper.py [file] [wps] [delay] [return_token] [tab_token] [typo_rate]
    infile = sys.argv[1] if len(sys.argv) > 1 else INPUT_FILE
    wps_cli = float(sys.argv[2]) if len(sys.argv) > 2 else None
    delay_cli = float(sys.argv[3]) if len(sys.argv) > 3 else None
    return_token_cli = sys.argv[4] if len(sys.argv) > 4 else None
    tab_token_cli = sys.argv[5] if len(sys.argv) > 5 else None
    typo_rate_cli = float(sys.argv[6]) if len(sys.argv) > 6 else None

    if not os.path.exists(infile):
        print(f"Error: {infile} not found.")
        sys.exit(1)

    with open(infile, "r", encoding="utf-8", errors="replace") as f:
        raw = f.read()

    safe_text, stats = sanitize_text(raw)

    print("=== Auto Typer — Human Model v3 (newline fix) ===")
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

    # Newline/tab mode (kept UI, but now we act directly on \n/\t)
    default_return_token = return_token_cli or DEFAULT_RETURN_TOKEN
    default_tab_token = tab_token_cli or DEFAULT_TAB_TOKEN

    print("\nChoose newline key to send (what your app expects):")
    print("  1) [[KEY_RETURN]]       (mac Return / normal Enter)  [default]")
    print("  2) [[KEY_SHIFT_RETURN]] (Shift+Return, e.g., chat newlines)")
    print("  3) [[KEY_ENTER]]        (numeric keypad Enter)")
    choice = (input("Pick 1/2/3: ").strip() or "1")
    newline_mode = "RETURN" if choice == "1" else ("SHIFT_RETURN" if choice == "2" else "ENTER")

    # For reporting only (no encoding anymore)
    encoded_returns = safe_text.count("\n")
    encoded_tabs = safe_text.count("\t")

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
    print(f"Newlines to send: {encoded_returns}")
    print(f"Tabs to send: {encoded_tabs}")

    cps = max(0.5, wps * 5.0)  # ~5 chars per word
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.02

    typo_rate = typo_rate_cli if typo_rate_cli is not None else DEFAULT_TYPO_RATE

    print("\n=== Run Settings ===")
    print(f"File: {infile}")
    print(f"WPS: {wps}  (≈ CPS {cps:.1f})")
    print(f"Start delay: {start_delay} s")
    print(f"Newline mode: {newline_mode}")
    print(f"Tab token (for external tokens only): {default_tab_token}")
    print(f"Target typo rate: {typo_rate:.2%}")
    input("Press Enter to start... (click your target window after)")

    print(f"\nStarting in {start_delay} seconds...")
    time.sleep(start_delay)

    try:
        type_with_tokens(safe_text, cps=cps, newline_mode=newline_mode, typo_rate=typo_rate)
        print("\nDone.")
    except KeyboardInterrupt:
        print("\nStopped by user.")

if __name__ == "__main__":
    # macOS: ensure Accessibility for Terminal/IDE & Python in System Settings → Privacy & Security → Accessibility.
    main()
