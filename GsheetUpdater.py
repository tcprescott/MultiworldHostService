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

ITEMS_TO_LIST = [
    "Bow",
    "Silver Arrows",
    "Hookshot",
    "Mushroom",
    "Magic Powder",
    "Fire Rod",
    "Ice Rod",
    "Bombos",
    "Ether",
    "Quake",
    "Lamp",
    "Hammer",
    "Flute",
    "Shovel",
    "Bug Catching Net",
    "Book of Mudora",
    "Bottle",
    "Cane of Somaria",
    "Cape",
    "Magic Mirror",
    "Pegasus Boots",
    "Power Gloves",
    "Titans Mitts",
    "Flippers",
    "Moon Pearl",
    "Fighter Sword",
    "Master Sword",
    "Big Key (Eastern Palace)",
    "Big Key (Desert Palace)",
    "Big Key (Tower of Hera)",
    "Big Key (Palace of Darkness)",
    "Big Key (Swamp Palace)",
    "Big Key (Skull Woods)",
    "Big Key (Thieves Town)",
    "Big Key (Ice Palace)",
    "Big Key (Misery Mire)",
    "Big Key (Turtle Rock)",
    "Big Key (Ganons Tower)",
    "Small Key (Escape)",
    "Small Key (Desert Palace)",
    "Small Key (Tower of Hera)",
    "Small Key (Agahnims Tower)",
    "Small Key (Palace of Darkness)",
    "Small Key (Swamp Palace)",
    "Small Key (Skull Woods)",
    "Small Key (Thieves Town)",
    "Small Key (Ice Palace)",
    "Small Key (Misery Mire)",
    "Small Key (Turtle Rock)",
    "Small Key (Ganons Tower)",
]

def update_gsheet(gsheetid):
    gc = gspread.authorize(get_creds())
    wb = gc.open_by_key(gsheetid)
    worksheet_list = wb.worksheets()
    for worksheet in worksheet_list:
        data = []
        data.append([
            "slot",
            "player name",
            "connected",
            "inventory",
            "checks",
            "last_seen",
        ] + ITEMS_TO_LIST)
        try:
            if worksheet.title == 'test':
                with open('test_data/fake_world.json', 'r') as f:
                    game = json.loads(f.read())
            else:
                resp = requests.get(
                    url=f'http://localhost:5000/game/{worksheet.title}?simple=false'
                )
                game = resp.json()
        except Exception as e:
            continue
        
        last_seen_list = worksheet.col_values(6)


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
                    last_seen
                ] + inventory_list(slot, game)
            )
        worksheet.batch_update(
            [
                {
                    'range': f'A1:f{colnum_string(len(data[0]))}{len(data)+1}',
                    'values': data
                },
            ],
            value_input_option='USER_ENTERED'
        )

PROGRESSIVE_ITEM_MAP = {
    'Titans Mitts': {
        'count': 2,
        'search_for': ['Progressive Glove']
    },
    'Power Gloves': {
        'count': 1,
        'search_for': ['Progressive Glove'],
        'or_has': [
            'Power Gloves',
            'Titans Mitts'
        ]
    },
    'Bow': {
        'count': 1,
        'search_for': ['Progressive Bow', 'Progressive Bow (Alt)'],
    },
    'Silver Arrows': {
        'count': 2,
        'search_for': ['Progressive Bow', 'Progressive Bow (Alt)']
    },
    'Fighter Sword': {
        'count': 1,
        'search_for': ['Progressive Sword'],
        'or_has': [
            'Fighter Sword',
            'Master Sword',
            'Tempered Sword',
            'Golden Sword'
        ]
    },
    'Master Sword': {
        'count': 2,
        'search_for': ['Progressive Sword'],
        'or_has': [
            'Master Sword',
            'Tempered Sword',
            'Golden Sword'
        ]
    },
    'Bottle': {
        'count': 1,
        'search_for': [
            'Bottle',
            'Bottle (Red Potion)',
            'Bottle (Green Potion)',
            'Bottle (Blue Potion)',
            'Bottle (Fairy)',
            'Bottle (Bee)',
            'Bottle (Good Bee)'
        ],
    },
}

def inventory_list(slot, game, team=0):
    inv_list = []
    for item in ITEMS_TO_LIST:
        requested_count = 1
        search_for = [item]
        if item in PROGRESSIVE_ITEM_MAP:
            requested_count = PROGRESSIVE_ITEM_MAP[item]['count']
            search_for = PROGRESSIVE_ITEM_MAP[item]['search_for']
        count = 0
        for i in search_for:
            count += game['server']['inventory'][team].get(str(slot+1), 'None').count(i)
        if item.startswith("Small Key"):
            inv_list.append(count)
        else:
            inv_list.append("✔️" if count >= requested_count or has_item_or_higher(item, slot, game, team) else "❌")
    return inv_list

def has_item_or_higher(item, slot, game, team=0):
    inv = game['server']['inventory'][team].get(str(slot+1), 'None')
    if item in PROGRESSIVE_ITEM_MAP:
        for i in PROGRESSIVE_ITEM_MAP[item].get('or_has', [item]):
            if i in inv:
                return True
    
    return False

def colnum_string(n):
    string = ""
    while n > 0:
        n, remainder = divmod(n - 1, 26)
        string = chr(65 + remainder) + string
    return string

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
