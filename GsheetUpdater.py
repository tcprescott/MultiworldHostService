#!env/bin/python

import argparse
import datetime
import json
import os

import gspread
import requests
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials

load_dotenv()


def update_gsheet(gsheetid):
    gc = gspread.authorize(get_creds())
    wb = gc.open_by_key(gsheetid)
    worksheet_list = wb.worksheets()
    for worksheet in worksheet_list:
        data = []
        try:
            resp = requests.get(
                url=f'http://localhost:5000/game/{worksheet.title}?simple=false'
            )
        except Exception as e:
            continue
        
        last_seen_list = worksheet.col_values(6)

        game = resp.json()
        for slot, player_name in enumerate(game['players'][0]):
            connection = next((item for item in game['server']['clients']['connected'] if item["slot"] == slot+1), None)
            try:
                last_datetime = game['server']['client_activity_timers'][0].get(str(slot+1), last_seen_list[slot+1])
                last_seen = datetime.datetime.fromisoformat(last_datetime).strftime('%Y/%m/%d %H:%M:%S')
            except ValueError:
                last_seen = last_seen_list[slot+1]
            except IndexError:
                last_seen = ''
            data.append(
                [
                    slot+1,
                    player_name,
                    "" if connection is None else "✔️",
                    len(game['server']['inventory'][0].get(str(slot+1), [])),
                    game['server']['location_checks'][0].get(str(slot+1), 0),
                    last_seen,
                    count_inv_items('Bombos', slot, game),
                    count_inv_items('Book of Mudora', slot, game),
                    count_inv_items('Bottle', slot, game) + count_inv_items('Bottle (Red Potion)', slot, game) + count_inv_items('Bottle (Green Potion)', slot, game) + count_inv_items('Bottle (Blue Potion)',  slot, game) + count_inv_items('Bottle (Fairy)',  slot,game) + count_inv_items('Bottle (Bee)',  slot,game) + count_inv_items('Bottle (Good Bee)',  slot,game),
                    count_inv_items('Cane of Somaria', slot, game),
                    count_inv_items('Cape', slot, game),
                    count_inv_items('Ether', slot, game),
                    count_inv_items('Fire Rod', slot, game),
                    count_inv_items('Flippers', slot, game),
                    count_inv_items('Flute', slot, game),
                    count_inv_items('Hammer', slot, game),
                    count_inv_items('Hookshot', slot, game),
                    count_inv_items('Ice Rod', slot, game),
                    count_inv_items('Lamp', slot, game),
                    count_inv_items('Magic Mirror', slot, game),
                    count_inv_items('Magic Powder', slot, game),
                    count_inv_items('Moon Pearl', slot, game),
                    count_inv_items('Mushroom', slot, game),
                    count_inv_items('Pegasus Boots', slot, game),
                    count_inv_items('Progressive Bow', slot, game) + count_inv_items('Progressive Bow (Alt)', slot, game),
                    count_inv_items('Progressive Glove', slot, game),
                    count_inv_items('Progressive Sword', slot, game),
                    count_inv_items('Quake', slot, game),
                    count_inv_items('Shovel', slot, game),
                ]
            )
        worksheet.batch_update(
            [
                {
                    'range': f'A2:AC{len(data)+1}',
                    'values': data
                },
            ],
            value_input_option='USER_ENTERED'
        )

def count_inv_items(item, slot, game):
    return game['server']['inventory'][0].get(str(slot+1), 'None').count(item)

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
