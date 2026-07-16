"""
Causelist Automation Runner
This script automatically runs the causelist download and JSON generation process.

Usage:
    python run_causelist.py                    # Opens GUI to select date
    python run_causelist.py 23-12-2025        # Uses specified date (DD-MM-YYYY)
"""

import subprocess
import sys
import os
from datetime import datetime
import threading
import queue

def run_script(script_name, date_arg):
    """Run a Python script with date argument and handle errors."""
    print(f"\n{'='*50}")
    print(f"Running {script_name} for date: {date_arg}")
    print(f"{'='*50}\n")
    
    try:
        result = subprocess.run(
            [sys.executable, script_name, date_arg],
            cwd=os.path.dirname(os.path.abspath(__file__)),
            capture_output=True,
            text=True,
            check=True
        )
        
        print(result.stdout)
        if result.stderr:
            print(f"Warnings/Info: {result.stderr}")
        
        print(f"\n[OK] {script_name} completed successfully")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"\n[ERROR] Error running {script_name}")
        print(f"Error output: {e.stderr}")
        print(f"Standard output: {e.stdout}")
        return False
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        return False

def validate_date(date_str):
    """Validate date format (DD-MM-YYYY)."""
    try:
        datetime.strptime(date_str, "%d-%m-%Y")
        return True
    except ValueError:
        return False

def run_gui():
    """Launch the GUI (imports only when needed)."""
    # Import GUI libraries lazily so CLI runs without them
    import tkinter as tk
    from tkinter import ttk
    try:
        from tkcalendar import DateEntry
    except ModuleNotFoundError:
        print("❌ tkcalendar is not installed. Install it with: pip install tkcalendar")
        sys.exit(1)

    class CauselistGUI:
        def __init__(self, root):
            self.root = root
            self.root.title("Causelist Automation")
            self.root.geometry("700x500")

            # Date selection frame
            date_frame = ttk.Frame(root, padding="10")
            date_frame.pack(fill=tk.X)

            ttk.Label(date_frame, text="Select Date:", font=("Arial", 12)).pack(side=tk.LEFT, padx=5)

            self.date_entry = DateEntry(date_frame, width=20, background='darkblue',
                                        foreground='white', borderwidth=2,
                                        date_pattern='dd-mm-yyyy')
            self.date_entry.pack(side=tk.LEFT, padx=5)

            self.run_button = ttk.Button(date_frame, text="Run Automation", command=self.start_automation)
            self.run_button.pack(side=tk.LEFT, padx=10)

            # Progress bar
            self.progress = ttk.Progressbar(root, mode='indeterminate')
            self.progress.pack(fill=tk.X, padx=10, pady=5)

            # Log display
            log_frame = ttk.Frame(root, padding="10")
            log_frame.pack(fill=tk.BOTH, expand=True)

            ttk.Label(log_frame, text="Logs:", font=("Arial", 10, "bold")).pack(anchor=tk.W)

            # Text widget with scrollbar
            text_scroll = ttk.Scrollbar(log_frame)
            text_scroll.pack(side=tk.RIGHT, fill=tk.Y)

            self.log_text = tk.Text(log_frame, wrap=tk.WORD, yscrollcommand=text_scroll.set,
                                   font=("Consolas", 9), bg="#1e1e1e", fg="#d4d4d4")
            self.log_text.pack(fill=tk.BOTH, expand=True)
            text_scroll.config(command=self.log_text.yview)

            # Status label
            self.status_label = ttk.Label(root, text="Ready", font=("Arial", 10))
            self.status_label.pack(pady=5)

            self.is_running = False

        def log(self, message):
            """Add message to log display."""
            self.log_text.insert(tk.END, message + "\n")
            self.log_text.see(tk.END)
            self.root.update_idletasks()

        def start_automation(self):
            """Start automation in a separate thread."""
            if self.is_running:
                return

            date_str = self.date_entry.get_date().strftime("%d-%m-%Y")
            self.is_running = True
            self.run_button.config(state=tk.DISABLED)
            self.progress.start()
            self.log_text.delete(1.0, tk.END)
            self.status_label.config(text="Running automation...")

            # Run in thread to avoid freezing GUI
            thread = threading.Thread(target=self.run_automation, args=(date_str,))
            thread.daemon = True
            thread.start()

        def run_automation(self, date_str):
            """Run the automation process."""
            try:
                self.log("="*50)
                self.log("CAUSELIST AUTOMATION STARTED")
                self.log(f"Date: {date_str}")
                self.log("="*50)

                # Step 1: Download files
                self.log("="*50)
                self.log(f"Running DownloadFiles.py for date: {date_str}")
                self.log("="*50)

                result1 = subprocess.run(
                    [sys.executable, "DownloadFiles.py", date_str],
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )

                self.log(result1.stdout)
                if result1.stderr:
                    self.log(f"Warnings: {result1.stderr}")

                if result1.returncode != 0:
                    self.log(f"\n✗ Error running DownloadFiles.py")
                    self.status_label.config(text="❌ Failed to download files")
                    return

                self.log(f"\n✓ DownloadFiles.py completed successfully\n")

                # Step 2: Generate JSON
                self.log("="*50)
                self.log(f"Running MainScript.py for date: {date_str}")
                self.log("="*50)

                result2 = subprocess.run(
                    [sys.executable, "MainScript.py", date_str],
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    capture_output=True,
                    text=True,
                    encoding='utf-8',
                    errors='replace'
                )

                # Only show summary, not full JSON output
                lines = result2.stdout.split('\n')
                for line in lines:
                    if 'JSON saved to:' in line or 'Generating JSON' in line or 'Error' in line:
                        self.log(line)

                if result2.stderr:
                    self.log(f"Warnings: {result2.stderr}")

                if result2.returncode != 0:
                    self.log(f"\n✗ Error running MainScript.py")
                    self.status_label.config(text="❌ Failed to generate JSON")
                    return

                self.log(f"\n✓ MainScript.py completed successfully\n")

                self.log("="*50)
                self.log("✓ CAUSELIST AUTOMATION COMPLETED SUCCESSFULLY")
                self.log("="*50)

                self.status_label.config(text="✓ Completed successfully!")

            except Exception as e:
                self.log(f"\n✗ Unexpected error: {e}")
                self.status_label.config(text="❌ Error occurred")

            finally:
                self.is_running = False
                self.run_button.config(state=tk.NORMAL)
                self.progress.stop()

    root = tk.Tk()
    app = CauselistGUI(root)
    root.mainloop()

def main():
    """Main automation workflow."""
    # If no arguments, show GUI
    if len(sys.argv) == 1:
        run_gui()
        return
    
    # Get date from command line
    date_str = sys.argv[1]
    if not validate_date(date_str):
        print("❌ Error: Invalid date format. Use DD-MM-YYYY (e.g., 23-12-2025)")
        sys.exit(1)
    
    print("\n" + "="*50)
    print("CAUSELIST AUTOMATION STARTED")
    print(f"Date: {date_str}")
    print("="*50)
    
    # Step 1: Download files
    if not run_script("DownloadFiles.py", date_str):
        print("\n[ERROR] Failed to download files. Stopping automation.")
        sys.exit(1)
    
    # Step 2: Generate JSON
    if not run_script("MainScript.py", date_str):
        print("\n[ERROR] Failed to generate JSON. Stopping automation.")
        sys.exit(1)
    
    print("\n" + "="*50)
    print("[OK] CAUSELIST AUTOMATION COMPLETED SUCCESSFULLY")
    print("="*50 + "\n")

if __name__ == "__main__":
    main()
