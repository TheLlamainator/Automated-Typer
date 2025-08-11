import pyautogui
import time
import os

def type_text(text, wps, delay):
    print(f"Starting in {delay} seconds... Switch to your target window!")
    time.sleep(delay)

    # Words-per-second → delay between words
    delay_between_words = 1.0 / wps

    print("Starting to type...")
    lines = text.split('\n')
    for line in lines:
        words = line.split()
        for word in words:
            pyautogui.write(word + " ", interval=0.01)  # small intra-word delay
            time.sleep(delay_between_words)
        pyautogui.press('enter')
        time.sleep(delay_between_words)
    print("Typing complete!")

def main():
    pyautogui.FAILSAFE = True

    print("=== Auto Typer (WPS) ===")

    script_dir = os.path.dirname(os.path.abspath(__file__))
    text_file_path = os.path.join(script_dir, "text.txt")

    if not os.path.exists(text_file_path):
        print(f"Error: text.txt not found in {script_dir}")
        print("Please create a text.txt file with the text you want to type.")
        return

    try:
        with open(text_file_path, 'r', encoding='utf-8') as file:
            text = file.read().strip()
    except Exception as e:
        print(f"Error reading text.txt: {str(e)}")
        return

    if not text:
        print("text.txt is empty. Please add some text to type.")
        return

    while True:
        try:
            # 2400 WPM ~= 40 WPS
            wps_input = input("Enter typing speed (WPS, default 40, min 0.1): ") or "40"
            wps = float(wps_input)
            if wps < 0.1:
                print("Please enter a WPS of at least 0.1")
                continue
            if wps > 200:
                print("Warning: Very high WPS values may cause issues. Are you sure? (y/n)")
                if input().lower() != 'y':
                    continue
            break
        except ValueError:
            print("Please enter a valid number")

    while True:
        try:
            delay = int(input("Enter start delay in seconds (default 5): ") or "5")
            if delay < 0:
                print("Please enter a non-negative number")
                continue
            break
        except ValueError:
            print("Please enter a valid number")

    print("\nSettings:")
    print(f"WPS: {wps}")
    print(f"Start Delay: {delay} seconds")
    print("\nReady to start typing!")
    input("Press Enter when ready...")

    try:
        type_text(text, wps, delay)
    except KeyboardInterrupt:
        print("\nTyping stopped by user")
    except Exception as e:
        print(f"\nAn error occurred: {str(e)}")

if __name__ == "__main__":
    main()