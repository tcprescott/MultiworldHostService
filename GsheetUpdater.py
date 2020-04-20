#!env/bin/python

import argparse
import json
import os
import gspread
from google.oauth2.service_account import Credentials

import requests
from dotenv import load_dotenv

load_dotenv()


def update_gsheet(gsheetid):
    gc = gspread.authorize(get_creds())
    wb = gc.open_by_key(gsheetid)
    worksheet_list = wb.worksheets()
    for worksheet in worksheet_list:
        data = []
        try:
            resp = requests.get(
                url=f'http://localhost:5000/game/{worksheet.title}'
            )
        except Exception as e:
            continue
        
        last_seen_list = worksheet.col_values(6)

        game = resp.json()
        for slot, player_name in enumerate(game['players'][0]):
            connection = next((item for item in game['server']['clients']['connected'] if item["slot"] == slot+1), None)
            try:
                last_seen = last_seen_list[slot+2]
            except IndexError:
                last_seen = ''
            data.append(
                [
                    slot+1,
                    player_name,
                    False if connection is None else True,
                    game['server']['received_items'][0].get(str(slot+1), 0),
                    game['server']['location_checks'][0].get(str(slot+1), 0),
                    game['server']['client_activity_timers'][0].get(str(slot+1), last_seen)
                ]
            )
        worksheet.batch_update(
            [
                {
                    'range': f'A2:F{len(data)+1}',
                    'values': data
                }
            ]
        )

def get_creds():
    return Credentials.from_service_account_info(
            json.loads(os.environ['GSHEET_API_OAUTH']),
            scopes=['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive',
                'https://www.googleapis.com/auth/spreadsheets']
        )

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("gsheet")

    args = parser.parse_args()

    update_gsheet(args.gsheet)