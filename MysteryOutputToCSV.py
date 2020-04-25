import csv

import yaml

with open('mystery_result.yaml', 'r') as f:
    mystery = yaml.safe_load(f.read())

PLAYERS = 200

with open('mystery_result.csv', 'w') as mysterycsv:
    fieldnames = ['slot'] + [f for f, v in mystery.items() if isinstance(v, dict)]
    writer = csv.DictWriter(mysterycsv, fieldnames=fieldnames)

    writer.writeheader()
    for p in range(0, PLAYERS):
        row = {
            'slot': p+1
        }
        for key, value in [(f, v) for f, v in mystery.items() if isinstance(v, dict)]:
            row[key] = value[p+1]

        writer.writerow(row)
