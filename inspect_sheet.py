import sys
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, 'backend')
from auth import get_credentials
from googleapiclient.discovery import build
from config import GOOGLE_SHEET_NAME

creds = get_credentials()
sheet_svc = build('sheets', 'v4', credentials=creds)
drive_svc = build('drive', 'v3', credentials=creds)

results = drive_svc.files().list(
    q=f'name="{GOOGLE_SHEET_NAME}" and mimeType="application/vnd.google-apps.spreadsheet"',
    fields='files(id, name)'
).execute()
files = results.get('files', [])
print('Found sheets:', [(f['name'], f['id']) for f in files])

if files:
    sid = files[0]['id']
    meta = sheet_svc.spreadsheets().get(spreadsheetId=sid).execute()
    tabs = [s['properties']['title'] for s in meta['sheets']]
    print('Tabs in sheet:', tabs)

    for tab in tabs:
        vals = sheet_svc.spreadsheets().values().get(
            spreadsheetId=sid, range=f"'{tab}'!1:3"
        ).execute()
        rows = vals.get('values', [])
        if rows:
            headers = rows[0]
            print(f'\nTab [{tab}] - {len(headers)} columns:')
            for i, h in enumerate(headers):
                sample = rows[1][i] if len(rows) > 1 and i < len(rows[1]) else ''
                print(f'  [{i:2d}] "{h}" => "{sample}"')
