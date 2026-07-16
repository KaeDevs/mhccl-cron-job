"""
Run causelist automation for a given date and upload generated JSONs to an FTP server.

Usage examples (Windows PowerShell):
    # Dry run: show files that would be uploaded
    python API\\run_and_ftp_upload.py 23-12-2025 --dry-run

    # Upload: set FTP credentials as env vars and run
    $env:FTP_HOST = "mhc.idealadvisories.com"
    $env:FTP_USER = "<username>"
    $env:FTP_PASS = "<password>"
    python API\\run_and_ftp_upload.py 23-12-2025 --remote-dir /apitest/jsons/

Environment variables:
    FTP_HOST   (default: mhc.idealadvisories.com)
    FTP_USER   (required unless --dry-run)
    FTP_PASS   (required unless --dry-run)

Notes:
    - Plain FTP only. FTPS/TLS support has been removed.
    - The script parses stdout from MainScript.py for lines like "JSON saved to: <path>".
    - If none are found, it falls back to scanning API/jsons for files containing the date.
    - Each file upload reconnects/retries automatically if the connection is aborted
      mid-transfer (common with local firewall/AV interference on Windows).
"""

import argparse
from dotenv import load_dotenv
import os
import re
import sys
import subprocess
import time
from datetime import datetime
from ftplib import FTP

load_dotenv()

MAX_UPLOAD_RETRIES = 3
RETRY_DELAY_SECONDS = 3


def validate_date(date_str: str) -> bool:
    try:
        datetime.strptime(date_str, "%d-%m-%Y")
        return True
    except ValueError:
        return False


def parse_json_paths_from_output(stdout: str, base_dir: str) -> list:
    """Extract JSON file paths from lines like: 'JSON saved to: <path>'"""
    paths = []
    pattern = re.compile(r"JSON saved to:\s*(.+)")
    for line in stdout.splitlines():
        m = pattern.search(line)
        if m:
            raw_path = m.group(1).strip().strip('"').strip("'")
            if not os.path.isabs(raw_path):
                raw_path = os.path.normpath(os.path.join(base_dir, raw_path))
            if raw_path.lower().endswith('.json'):
                paths.append(raw_path)
    return paths


def find_jsons_for_date(date_str: str, api_dir: str) -> list:
    """Fallback: scan API/jsons for files containing the date string."""
    json_dir = os.path.join(api_dir, 'jsons')
    if not os.path.isdir(json_dir):
        return []
    matches = []
    for name in os.listdir(json_dir):
        if name.lower().endswith('.json') and date_str in name:
            matches.append(os.path.join(json_dir, name))
    return sorted(matches)


def ensure_remote_dir(ftp: FTP, remote_dir: str) -> None:
    """Ensure the remote directory exists by creating missing segments."""
    if not remote_dir:
        return
    parts = [p for p in remote_dir.replace('\\', '/').split('/') if p]
    path_built = ''
    for part in parts:
        path_built += '/' + part
        try:
            ftp.cwd(path_built)
        except Exception:
            ftp.mkd(path_built)
            ftp.cwd(path_built)


def connect_ftp(ftp_host: str, ftp_user: str, ftp_pass: str, ftp_debug: bool) -> FTP:
    """Create a fresh plain-FTP connection and log in."""
    ftp = FTP(ftp_host, timeout=120)
    if ftp_debug:
        ftp.set_debuglevel(2)
    # Passive mode is the default in ftplib, but set explicitly for clarity.
    ftp.set_pasv(True)

    try:
        ftp.login(user=ftp_user, passwd=ftp_pass)
    except Exception as e1:
        host_parts = ftp_host.split('.')
        domain = '.'.join(host_parts[-2:]) if len(host_parts) >= 2 else ftp_host
        retry_user = f"{ftp_user}@{domain}" if ftp_user and '@' not in ftp_user else None
        if retry_user:
            print(f"Login failed with provided username; retrying as '{retry_user}'...")
            ftp.login(user=retry_user, passwd=ftp_pass)
        else:
            raise e1
    return ftp


def upload_one_file(ftp_host: str, ftp_user: str, ftp_pass: str, ftp_debug: bool,
                     fp: str, remote_dir: str) -> None:
    """
    Upload a single file using its OWN fresh FTP connection (connect, login,
    cwd, STOR, quit). Some FTP servers behave badly when multiple STORs are
    issued on one reused control connection, so we never reuse a session
    across files. Retries with a brand-new connection on failure.
    """
    fname = os.path.basename(fp)
    attempt = 0
    last_err = None
    while attempt < MAX_UPLOAD_RETRIES:
        attempt += 1
        ftp = None
        try:
            print(f"Uploading {fname} -> {remote_dir} (attempt {attempt})")
            ftp = connect_ftp(ftp_host, ftp_user, ftp_pass, ftp_debug)
            ensure_remote_dir(ftp, remote_dir)
            with open(fp, 'rb') as f:
                ftp.storbinary(f'STOR {fname}', f)
            print(f"[OK] Uploaded {fname}")
            try:
                ftp.quit()
            except Exception:
                ftp.close()
            return
        except (ConnectionAbortedError, ConnectionResetError, EOFError, OSError) as e:
            last_err = e
            print(f"[WARN] Upload of {fname} failed: {e}")
            if ftp is not None:
                try:
                    ftp.close()
                except Exception:
                    pass
            if attempt >= MAX_UPLOAD_RETRIES:
                break
            print(f"Reconnecting fresh and retrying in {RETRY_DELAY_SECONDS}s...")
            time.sleep(RETRY_DELAY_SECONDS)

    print(f"[FAIL] Giving up on {fname} after {attempt} attempts")
    if last_err is not None:
        raise last_err
    raise RuntimeError(f"Upload failed for {fname}")


def upload_files(ftp_host: str, ftp_user: str, ftp_pass: str, ftp_debug: bool,
                  files: list, remote_dir: str) -> None:
    """Upload each file with its own dedicated FTP connection."""
    for fp in files:
        if not os.path.isfile(fp):
            print(f"Skipping missing file: {fp}")
            continue
        upload_one_file(ftp_host, ftp_user, ftp_pass, ftp_debug, fp, remote_dir)
        # Small pause between sessions - some hosts rate-limit rapid reconnects
        time.sleep(1)


def run_causelist(date_str: str, api_dir: str) -> subprocess.CompletedProcess:
    """Run run_causelist.py with the given date and return the process."""
    cmd = [sys.executable, 'run_causelist.py', date_str]
    print(f"Running: {' '.join(cmd)} (cwd={api_dir})")
    proc = subprocess.run(
        cmd,
        cwd=api_dir,
        capture_output=True,
        text=True,
        encoding='utf-8',
        errors='replace',
        check=False,
    )
    print(proc.stdout)
    if proc.stderr:
        print(f"Warnings/Errors:\n{proc.stderr}")
    return proc


def main():
    parser = argparse.ArgumentParser(description="Run causelist and upload JSONs via FTP")
    parser.add_argument('date', help="Date in DD-MM-YYYY")
    parser.add_argument(
        '--remote-dir',
        default=os.getenv("FTP_REMOTE_DIR", "/mhc.idealadvisories.com/apitest/jsons/"),
        help="Remote directory on FTP server (path only)"
    )
    parser.add_argument('--dry-run', action='store_true', help="Do not upload; just show actions")
    parser.add_argument('--ftp-host', help="FTP host (overrides FTP_HOST env; default mhc.idealadvisories.com)")
    parser.add_argument('--ftp-user', help="FTP username (overrides FTP_USER env)")
    parser.add_argument('--ftp-pass', help="FTP password (overrides FTP_PASS env)")
    parser.add_argument('--ftp-debug', action='store_true', help="Enable verbose FTP debug output")
    args = parser.parse_args()

    date_str = args.date
    if not validate_date(date_str):
        print("❌ Invalid date format. Use DD-MM-YYYY (e.g., 23-12-2025)")
        sys.exit(1)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    proc = run_causelist(date_str, script_dir)

    if proc.returncode != 0:
        print("❌ run_causelist.py failed; aborting upload")
        sys.exit(proc.returncode)

    json_paths = parse_json_paths_from_output(proc.stdout, script_dir)
    if not json_paths:
        json_paths = find_jsons_for_date(date_str, script_dir)

    if not json_paths:
        print(f"❌ No JSON files found for date {date_str}")
        sys.exit(2)

    print("Files to upload:")
    for p in json_paths:
        print(f" - {p}")

    if args.dry_run:
        print(f"Dry run: would upload to '{args.remote_dir}' on FTP host")
        sys.exit(0)

    ftp_host = args.ftp_host or os.getenv("FTP_HOST", "mhc.idealadvisories.com")
    ftp_user = args.ftp_user or os.getenv("FTP_USER")
    ftp_pass = args.ftp_pass or os.getenv("FTP_PASS")

    if not ftp_user or not ftp_pass:
        print("❌ Missing FTP credentials. Set FTP_USER and FTP_PASS env vars.")
        print(f"FTP_HOST defaults to: {ftp_host}")
        sys.exit(3)

    print(f"Connecting to FTP host: {ftp_host} (plain FTP, one connection per file)")

    try:
        upload_files(ftp_host, ftp_user, ftp_pass, args.ftp_debug, json_paths, args.remote_dir)
    except Exception as e:
        print(f"❌ Upload failed: {e}")
        sys.exit(4)

    print("\n✓ Upload complete")


if __name__ == '__main__':
    main()