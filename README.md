# Auto Typer (WPS)

A small Python utility that types text into the active window at a configurable **words-per-second (WPS)** rate.  
Useful for **UI testing**, **accessibility workflows**, and **automation demos** where simulated human typing is needed.

> **Important**  
> This tool is **not** intended to evade copy/paste detection, academic integrity systems, or any monitoring/anti-abuse controls.  
> Do **not** use it to mislead platforms or people. Use responsibly and in compliance with applicable policies and laws.

macOS note: you may need to grant Accessibility permissions to your terminal or Python in
System Settings → Privacy & Security → Accessibility.

---

## Features
- Types from a local `text.txt` file line by line
- Speed set in **WPS** (e.g., 40 WPS ≈ 2400 WPM)
- Start delay so you can focus the target window
- Fail-safe: slam mouse to a screen corner to abort (`pyautogui.FAILSAFE`)

---

## Requirements
- Python 3.8+
- [`pyautogui`](https://pypi.org/project/PyAutoGUI/)
- macOS, Windows, or Linux with a GUI session

Install dependencies:
```bash
pip install pyautogui
