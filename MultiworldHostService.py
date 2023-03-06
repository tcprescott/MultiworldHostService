import asyncio
import datetime
import functools
import json
import logging
import random
import re
import shlex
import socket
import string
import zlib
import urllib.parse

import aiofiles
import aiohttp
import MultiServer
import websockets
from quart import Quart, abort, jsonify, request
# from tortoise import Tortoise
# import models

# import settings

MULTIWORLDS = {}

APP = Quart(__name__)

@APP.route('/game', methods=['POST'])
async def create_game():
    data = await request.get_json()

    world = await init_multiserver(data)

    response = APP.response_class(
        response=json.dumps(world, default=simple_multiworld_converter),
        status=200,
        mimetype='application/json'
    )

    return response


@APP.route('/game', methods=['GET'])
async def get_all_games():
    response = APP.response_class(
        response=json.dumps(
            {
                'count': len(MULTIWORLDS),
                'games': MULTIWORLDS
            },
            default=simple_multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response


@APP.route('/game/<string:token>', methods=['GET'])
async def get_game(token):
    if not token in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    response = APP.response_class(
        response=json.dumps(MULTIWORLDS[token], default=simple_multiworld_converter),
        status=200,
        mimetype='application/json'
    )

    return response


@APP.route('/game/<string:token>/msg', methods=['PUT'])
async def update_game_message(token):
    data = await request.get_json()

    if not token in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    if not 'msg' in data:
        abort(400)

    if data['msg'] == '/exit':
        close_game(data['token'])
        return jsonify(resp='Game closed.', success=True)

    try:
        resp = await server_command_processor(MULTIWORLDS[token]['server'], data['msg'])
        return jsonify(resp=resp, success=True)
    except Exception as e:
        logging.exception("Exception in server_command_processor")
        return jsonify(resp=str(e), success=False)


@APP.route('/game/<string:token>/<string:param>', methods=['PUT'])
async def update_game_parameter(token, param):
    data = await request.get_json()

    if not token in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    if not 'value' in data:
        abort(400)

    if param in ['noexpiry', 'admin', 'meta', 'racemode']:
        MULTIWORLDS[token][param] = data['value']
        await save_worlds()
        return jsonify(success=True)
    else:
        abort(400)


@APP.route('/game/<string:token>', methods=['DELETE'])
async def delete_game(token):
    if not token in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    close_game(token)

    await save_worlds()

    return jsonify(success=True)


@APP.route('/game/<string:token>/<int:slot>/<int:team>', methods=['DELETE'])
async def kick_player(token, slot, team):
    if not token in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    for client in MULTIWORLDS[token]['server'].endpoints:
        if client.auth and client.team == team and client.slot == slot and not client.socket.closed:
            await client.socket.close()

    return jsonify(success=True)


@APP.route('/jobs/cleanup/<int:minutes>', methods=['POST'])
async def cleanup(minutes):
    tokens_to_clean = []
    for token in MULTIWORLDS:
        if MULTIWORLDS[token]['date'] < datetime.datetime.now()-datetime.timedelta(minutes=minutes) and not MULTIWORLDS[token].get('noexpiry', False):
            tokens_to_clean.append(token)
    for token in tokens_to_clean:
        close_game(token)

    await save_worlds()

    return jsonify(success=True, count=len(tokens_to_clean), cleaned_tokens=tokens_to_clean)


@APP.errorhandler(400)
def bad_request(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.code)


@APP.errorhandler(404)
def game_not_found(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.code)


@APP.errorhandler(500)
def something_bad_happened(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.code)


def close_game(token):
    server = MULTIWORLDS[token]['server']
    server.server.ws_server.close()
    del MULTIWORLDS[token]


def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('0.0.0.0', port)) == 0


def random_string(length=6):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for i in range(length))


def simple_multiworld_converter(o):
    if isinstance(o, MultiServer.Client):
        return None
    if isinstance(o, MultiServer.Context):
        return None
    if isinstance(o, datetime.datetime):
        return o.__str__()


async def save_worlds():
    async with aiofiles.open('data/saved_worlds.json', 'w') as save:
        await save.write(json.dumps(MULTIWORLDS, default=simple_multiworld_converter))
        await save.flush()


@APP.before_serving
async def load_worlds():
    try:
        async with aiofiles.open('data/saved_worlds.json', 'r') as save:
            saved_worlds = json.loads(await save.read())
    except FileNotFoundError:
        saved_worlds = []
        print('saved_worlds.json not found, continuing...')

    for token in saved_worlds:
        print(f"Restoring {token}")
        await init_multiserver(saved_worlds[token])

async def server_command_processor(ctx: MultiServer.Context, raw_input: str):
    command = shlex.split(raw_input)
    if not command:
        return

    if command[0] == '/players':
        logging.info(MultiServer.get_connected_players_string(ctx))
        return "Players: " + MultiServer.get_connected_players_string(ctx)
    if command[0] == '/password':
        MultiServer.set_password(ctx, command[1] if len(command) > 1 else None)
        return "Password set."
    if command[0] == '/kick' and len(command) > 1:
        team = int(command[2]) - 1 if len(command) > 2 and command[2].isdigit() else None
        for client in ctx.clients:
            if client.auth and client.name.lower() == command[1].lower() and (team is None or team == client.team):
                if client.socket and not client.socket.closed:
                    await client.socket.close()
                    return f"Kicked player '{command[1]}'."

        return f"Player '{command[1]}' not found."

    if command[0] == '/forfeitslot' and len(command) > 1 and command[1].isdigit():
        if len(command) > 2 and command[2].isdigit():
            team = int(command[1]) - 1
            slot = int(command[2])
        else:
            team = 0
            slot = int(command[1])
        MultiServer.forfeit_player(ctx, team, slot)
        return f"Forfeited player in slot {slot} on team {team + 1}."
    if command[0] == '/forfeitplayer' and len(command) > 1:
        team = int(command[2]) - 1 if len(command) > 2 and command[2].isdigit() else None
        for client in ctx.clients:
            if client.auth and client.name.lower() == command[1].lower() and (team is None or team == client.team):
                if client.socket and not client.socket.closed:
                    MultiServer.forfeit_player(ctx, client.team, client.slot)
                    return f"Forfeited player {command[1]} from team {team + 1}."
    if command[0] == '/senditem' and len(command) > 2:
        [(player, item)] = re.findall(r'\S* (\S*) (.*)', raw_input)
        if item in MultiServer.Items.item_table:
            for client in ctx.clients:
                if client.auth and client.name.lower() == player.lower():
                    new_item = MultiServer.ReceivedItem(MultiServer.Items.item_table[item][3], "cheat console", client.slot)
                    MultiServer.get_received_items(ctx, client.team, client.slot).append(new_item)
                    MultiServer.notify_all(ctx, 'Cheat console: sending "' + item + '" to ' + client.name)
            MultiServer.send_new_items(ctx)
            return f"Sent {item} to {player}."
        else:
            logging.warning("Unknown item: " + item)
            return f"Unknown item: {item}"

    if command[0][0] != '/':
        MultiServer.notify_all(ctx, '[Server]: ' + raw_input)

async def init_multiserver(data):
    if not 'multidata_url' in data and not 'token' in data:
        raise Exception('Missing multidata_url or token in data')

    port = int(data.get('port', random.randint(30000, 35000)))

    if port < 30000 or port > 35000:
        raise Exception(f'Port {port} is out of bounds.')
    if is_port_in_use(port):
        raise Exception(f'Port {port} is in use!')

    if 'token' in data:
        token = data['token']
        if token in MULTIWORLDS:
            raise Exception(f'Game with token {token} already exists.')

        async with aiofiles.open(f"data/{token}_multidata", "rb") as multidata_file:
            binary = await multidata_file.read()
    else:
        token = random_string(6)

        async with aiohttp.request(method='get', url=data['multidata_url'], headers={'User-Agent': 'SahasrahBot Multiworld Service'}) as resp:
            binary = await resp.read()

        async with aiofiles.open(f"data/{token}_multidata", "wb") as multidata_file:
            await multidata_file.write(binary)

    if 'date' in data:
        server_date = datetime.datetime.fromisoformat(data['date'])
    else:
        server_date = datetime.datetime.now()

    multidata = json.loads(zlib.decompress(binary).decode("utf-8"))

    ctx = await create_multiserver(
        port,
        f"data/{token}_multidata",
        racemode=data.get('racemode', False)
    )

    MULTIWORLDS[token] = {
        'token': token,
        'server': ctx,
        'port': port,
        'noexpiry': data.get('noexpiry', False),
        'admin': data.get('admin', None),
        'date': server_date,
        'meta': data.get('meta', None),
        'players': multidata['names'],
        'server_options': multidata.get('server_options', None),
    }

    await save_worlds()

    return MULTIWORLDS[token]


async def create_multiserver(port, multidatafile, racemode=False):
    logging.basicConfig(format='[%(asctime)s] %(message)s', level=getattr(logging, "INFO", logging.INFO))

    ctx = MultiServer.Context('0.0.0.0', port, None)
    ctx.data_filename = multidatafile
    ctx.disable_client_forfeit = racemode


    try:
        with open(ctx.data_filename, 'rb') as f:
            jsonobj = json.loads(zlib.decompress(f.read()).decode("utf-8"))
            for team, names in enumerate(jsonobj['names']):
                for player, name in enumerate(names, 1):
                    ctx.player_names[(team, player)] = name
            ctx.rom_names = {tuple(rom): (team, slot) for slot, team, rom in jsonobj['roms']}
            ctx.remote_items = set(jsonobj['remote_items'])
            ctx.locations = {tuple(k): tuple(v) for k, v in jsonobj['locations']}
    except Exception as e:
        logging.error('Failed to read multiworld data (%s)' % e)
        return

    if not ctx.disable_save:
        if not ctx.save_filename:
            ctx.save_filename = (ctx.data_filename[:-9] if ctx.data_filename[-9:] == 'multidata' else (
                ctx.data_filename + '_')) + 'multisave'
        try:
            with open(ctx.save_filename, 'rb') as f:
                jsonobj = json.loads(zlib.decompress(f.read()).decode("utf-8"))
                rom_names = jsonobj[0]
                received_items = {tuple(k): [MultiServer.ReceivedItem(**i) for i in v] for k, v in jsonobj[1]}
                if not all([ctx.rom_names[tuple(rom)] == (team, slot) for rom, (team, slot) in rom_names]):
                    raise Exception('Save file mismatch, will start a new game')
                ctx.received_items = received_items
                logging.info('Loaded save file with %d received items for %d players' % (sum([len(p) for p in received_items.values()]), len(received_items)))
        except FileNotFoundError:
            logging.error('No save data found, starting a new game')
        except Exception as e:
            logging.exception(e)

    ctx.server = websockets.serve(functools.partial(MultiServer.server,ctx=ctx), ctx.host, ctx.port, ping_timeout=None, ping_interval=None)
    await ctx.server
    return ctx

# async def database():
#     await Tortoise.init(
#         db_url=f'mysql://{settings.DB_USER}:{urllib.parse.quote_plus(settings.DB_PASS)}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}',
#         modules={'models': ['models']}
#     )

if __name__ == '__main__':
    # loop = asyncio.get_event_loop()

    # dbtask = loop.create_task(database())
    # loop.run_until_complete(dbtask)
    APP.run(host='127.0.0.1', port=5002, use_reloader=False)
