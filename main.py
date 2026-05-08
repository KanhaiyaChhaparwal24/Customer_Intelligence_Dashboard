import os
import re
import io
import pickle
import pandas as pd

import gspread

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


# ==========================================
# GOOGLE AUTH CONFIG
# ==========================================

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets"
]

CREDS_FILE = "credentials.json"
TOKEN_FILE = "token.pkl"

DOWNLOAD_FOLDER = "downloads"

os.makedirs(DOWNLOAD_FOLDER, exist_ok=True)


# ==========================================
# GOOGLE LOGIN
# ==========================================

creds = None

if os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, "rb") as token:
        creds = pickle.load(token)

if not creds or not creds.valid:

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())

    else:
        flow = InstalledAppFlow.from_client_secrets_file(
            CREDS_FILE,
            SCOPES
        )

        creds = flow.run_local_server(port=0)

    with open(TOKEN_FILE, "wb") as token:
        pickle.dump(creds, token)

print("\n✅ Google Authentication Successful")


# ==========================================
# CONNECT GOOGLE SHEETS
# ==========================================

gc = gspread.authorize(creds)

# CHANGE THIS TO YOUR SHEET NAME
SHEET_NAME = "Customer Data Sources Sample Structure"

sheet = gc.open(SHEET_NAME)

print(f"✅ Connected to Sheet: {SHEET_NAME}")


# ==========================================
# READ BOTH SHEETS
# ==========================================

warranty_sheet = sheet.get_worksheet(0)
shopify_sheet = sheet.get_worksheet(1)

warranty_data = warranty_sheet.get_all_records()
shopify_data = shopify_sheet.get_all_records()

print(f"✅ Warranty Rows Found: {len(warranty_data)}")
print(f"✅ Shopify Rows Found: {len(shopify_data)}")


# ==========================================
# CONNECT GOOGLE DRIVE
# ==========================================

drive_service = build("drive", "v3", credentials=creds)

print("✅ Google Drive Connected")


# ==========================================
# EXTRACT FILE/FOLDER ID
# ==========================================

def extract_drive_id(url):

    file_patterns = [
        r"/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)"
    ]

    folder_pattern = r"/folders/([a-zA-Z0-9_-]+)"

    # FILE LINKS
    for pattern in file_patterns:

        match = re.search(pattern, url)

        if match:
            return {
                "type": "file",
                "id": match.group(1)
            }

    # FOLDER LINK
    folder_match = re.search(folder_pattern, url)

    if folder_match:
        return {
            "type": "folder",
            "id": folder_match.group(1)
        }

    return None


# ==========================================
# DOWNLOAD DRIVE FILE
# ==========================================

def download_drive_file(file_id, output_path):

    request = drive_service.files().get_media(fileId=file_id)

    fh = io.BytesIO()

    downloader = MediaIoBaseDownload(fh, request)

    done = False

    while not done:
        status, done = downloader.next_chunk()

    with open(output_path, "wb") as f:
        f.write(fh.getvalue())


# ==========================================
# PROCESS WARRANTY SHEET
# ==========================================

print("\n==============================")
print("STARTING INVOICE PROCESSING")
print("==============================")

for idx, row in enumerate(warranty_data):

    print(f"\n📌 Processing Row {idx + 1}")

    # CHANGE COLUMN NAME IF NEEDED
    drive_link = row.get("Invoice Upload")

    if not drive_link:
        print("⚠ No Drive Link Found")
        continue

    print(f"🔗 Drive Link: {drive_link}")

    drive_info = extract_drive_id(drive_link)

    if not drive_info:
        print("❌ Invalid Drive Link")
        continue

    try:

        # ==========================================
        # SINGLE FILE
        # ==========================================

        if drive_info["type"] == "file":

            file_id = drive_info["id"]

            file_metadata = drive_service.files().get(
                fileId=file_id,
                fields="name"
            ).execute()

            filename = file_metadata["name"]

            output_path = os.path.join(
                DOWNLOAD_FOLDER,
                filename
            )

            download_drive_file(file_id, output_path)

            print(f"✅ Downloaded File: {filename}")

        # ==========================================
        # FOLDER
        # ==========================================

        elif drive_info["type"] == "folder":

            folder_id = drive_info["id"]

            print("📂 Folder Detected")

            results = drive_service.files().list(
                q=f"'{folder_id}' in parents",
                fields="files(id, name)"
            ).execute()

            files = results.get("files", [])

            print(f"📁 Found {len(files)} files in folder")

            if len(files) == 0:
                print("⚠ Folder is empty")

            for file in files:

                file_id = file["id"]
                filename = file["name"]

                output_path = os.path.join(
                    DOWNLOAD_FOLDER,
                    filename
                )

                download_drive_file(file_id, output_path)

                print(f"✅ Downloaded: {filename}")

    except Exception as e:

        print(f"❌ Error: {e}")


# ==========================================
# OPTIONAL: CONVERT TO DATAFRAMES
# ==========================================

warranty_df = pd.DataFrame(warranty_data)
shopify_df = pd.DataFrame(shopify_data)

print("\n==============================")
print("DATA SUMMARY")
print("==============================")

print("\nWarranty Columns:")
print(warranty_df.columns.tolist())

print("\nShopify Columns:")
print(shopify_df.columns.tolist())

print("\n==============================")
print("✅ ALL DONE")
print("==============================")