import argparse
import asyncio
import datetime
import functools
import json
import logging
import random
import re
import requests
import shlex
import socket
import string
import urllib
import zlib

import aiofiles
import websockets
from quart import Quart, abort, jsonify, request

import Items
import MultiClient
import MultiServer

APP = Quart(__name__)
MULTIWORLD_HOST = requests.get('https://checkip.amazonaws.com').text.strip()

# TODO: Replace this with a SQLite database
MULTIWORLDS = {}


@APP.route('/game', methods=['POST'])
async def create_game():
    global MULTIWORLDS

    data = await request.get_json()

    if not data:
        abort(400, description=f'Missing json body')

    if 'multidata_url' not in data:
        abort(400, description=f'Missing multidata_url in data')

    port = int(data.get('port', random.randint(30000, 35000)))

    # Berserker's hint options
    check_value = data['checkValue'] if 'checkValue' in data else 1
    hint_cost = data['hintCost'] if 'hintCost' in data else 1000
    allow_cheats = 'allowCheats' in data and int(data['allowCheats']) == 1

    if port < 30000 or port > 35000:
        abort(400, description=f'Port {port} is out of bounds.')
    if is_port_in_use(port):
        abort(400, description=f'Port {port} is in use!')

    req = urllib.request.Request(
        url=data['multidata_url'],
        headers={'User-Agent': 'SahasrahBot Multiworld Service'}
    )
    token = random_string(6)
    binary = urllib.request.urlopen(req).read()

    async with aiofiles.open(f"data/{token}_multidata", "wb") as multidata_file:
        await multidata_file.write(binary)

    multidata = json.loads(zlib.decompress(binary).decode("utf-8"))

    ctx = await create_multiserver(port, f"data/{token}_multidata", check_value, hint_cost, allow_cheats)

    MULTIWORLDS[token] = {
        'token': token,
        'server': ctx,
        'host': MULTIWORLD_HOST,
        'port': port,
        'admin': data.get('admin', None),
        'date': datetime.datetime.now(),
        'meta': data.get('meta', None),
        'players': multidata['names'],
    }
    response = APP.response_class(
        response=json.dumps(MULTIWORLDS[token], default=multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response


@APP.route('/game/<string:token>', methods=['POST'])
# TODO: Break out some functionality so there isn't a bunch of duplicated code
async def resume_game(token):
    global MULTIWORLDS

    data = await request.get_json()

    port = int(data.get('port', random.randint(30000, 35000)))

    if port < 30000 or port > 35000:
        abort(400, description=f'Port {port} is out of bounds.')
    if is_port_in_use(port):
        abort(400, description=f'Port {port} is in use!')

    if token in MULTIWORLDS:
        abort(400, description=f'Game with token {token} already exists.')

    async with aiofiles.open(f"data/{token}_multidata", "rb") as multidata_file:
        binary = await multidata_file.read()

    multidata = json.loads(zlib.decompress(binary).decode("utf-8"))

    # Berserker's hint options
    check_value = int(data['checkValue']) if 'checkValue' in data else 1
    hint_cost = int(data['hintCost']) if 'hintCost' in data else 1000
    allow_cheats = 'allowCheats' in data and int(data['allowCheats']) == 1

    ctx = await create_multiserver(port, f"data/{token}_multidata", check_value, hint_cost, allow_cheats)
    ctx.host = MULTIWORLD_HOST

    MULTIWORLDS[token] = {
        'token': token,
        'server': ctx,
        'host': MULTIWORLD_HOST,
        'port': port,
        'admin': data.get('admin', None),
        'date': datetime.datetime.now(),
        'meta': data.get('meta', None),
        'players': multidata['names'],
    }
    response = APP.response_class(
        response=json.dumps(MULTIWORLDS[token], default=multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response


@APP.route('/game', methods=['GET'])
async def get_all_games():
    global MULTIWORLDS
    response = APP.response_class(
        response=json.dumps(MULTIWORLDS, default=multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response


@APP.route('/game/<string:token>', methods=['GET'])
async def get_game(token):
    global MULTIWORLDS

    if token not in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    response = APP.response_class(
        response=json.dumps(MULTIWORLDS[token], default=multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response


@APP.route('/game/<string:token>/msg', methods=['PUT'])
async def update_game(token):
    data = await request.get_json()

    global MULTIWORLDS

    if token not in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    if 'msg' not in data:
        abort(400)

    resp = await console_message(MULTIWORLDS[token]['server'], data['msg'])
    return jsonify(resp=resp, success=True)


@APP.route('/game/<string:token>', methods=['DELETE'])
async def delete_game(token):
    global MULTIWORLDS

    if token not in MULTIWORLDS:
        abort(404, description=f'Game with token {token} was not found.')

    close_game(token)
    return jsonify(success=True)


@APP.route('/jobs/cleanup/<int:minutes>', methods=['POST'])
async def cleanup(minutes):
    global MULTIWORLDS
    tokens_to_clean = []
    for token in MULTIWORLDS:
        if MULTIWORLDS[token]['date'] < datetime.datetime.now() - datetime.timedelta(minutes=minutes):
            tokens_to_clean.append(token)
    for token in tokens_to_clean:
        close_game(token)
    return jsonify(success=True, count=len(tokens_to_clean), cleaned_tokens=tokens_to_clean)


@APP.errorhandler(400)
def bad_request(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.status_code)


@APP.errorhandler(404)
def game_not_found(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.status_code)


@APP.errorhandler(500)
def something_bad_happened(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.status_code)


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


def multiworld_converter(o):
    if isinstance(o, MultiServer.Client):
        return {
            'auth': o.auth,
            'name': o.name,
            'team': o.team,
            'slot': o.slot,
            'send_index': o.send_index
        }
    if isinstance(o, MultiServer.Context):
        return {
            'data_filename': o.data_filename,
            'save_filename': o.save_filename,
            'host': o.host,
            'clients': {
                'count': len(o.clients),
                'connected': o.clients
            }
        }
    if isinstance(o, tuple):
        return list([list(row) for row in o])
    if isinstance(o, datetime.datetime):
        return o.__str__()
    if isinstance(o, asyncio.subprocess.Process):
        return o.pid


async def create_multiserver(port, multidata_file, check_value=1, hint_cost=50, allow_cheats=False):
    args = argparse.Namespace(
        host='0.0.0.0',
        port=port,
        password=None,
        multidata=multidata_file,
        disable_save=False,
        loglevel="info",
        checkvalue=check_value,
        hintcost=hint_cost,
        itemcheat=allow_cheats
    )

    logging.basicConfig(format='[%(asctime)s] %(message)s', level=getattr(logging, args.loglevel.upper(), logging.INFO))

    ctx = MultiServer.Context(args.host, args.port, args.password, args.checkvalue, args.hintcost, args.itemcheat)

    ctx.data_filename = args.multidata

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

    logging.info('Hosting game at %s:%d (%s)' % (
        ctx.host, ctx.port, 'No password' if not ctx.password else 'Password: %s' % ctx.password))

    ctx.disable_save = args.disable_save
    if not ctx.disable_save:
        if not ctx.save_filename:
            ctx.save_filename = (ctx.data_filename[:-9] if ctx.data_filename[-9:] == 'multidata' else (
                    ctx.data_filename + '_')) + 'multisave'
        try:
            with open(ctx.save_filename, 'rb') as f:
                jsonobj = json.loads(zlib.decompress(f.read()).decode("utf-8"))
                rom_names = jsonobj[0]
                received_items = {tuple(k): [MultiClient.ReceivedItem(**i) for i in v] for k, v in jsonobj[1]}
                if not all([ctx.rom_names[tuple(rom)] == (team, slot) for rom, (team, slot) in rom_names]):
                    raise Exception('Save file mismatch, will start a new game')
                ctx.received_items = received_items
                logging.info('Loaded save file with %d received items for %d players' % (
                    sum([len(p) for p in received_items.values()]), len(received_items)))
        except FileNotFoundError:
            logging.error('No save data found, starting a new game')
        except Exception as e:
            logging.info(e)

    ctx.server = websockets.serve(functools.partial(MultiServer.server, ctx=ctx), ctx.host, ctx.port, ping_timeout=None,
                                  ping_interval=None)
    await ctx.server
    return ctx


# this is a modified version of MultiServer.console that can accept commands
async def console_message(ctx: MultiServer.Context, message):
    command = shlex.split(message)

    # if command[0] == '/exit':
    #     ctx.server.ws_server.close()
    #     break

    if command[0] == '/players':
        return MultiServer.get_connected_players_string(ctx)
    if command[0] == '/password':
        MultiServer.set_password(ctx, command[1] if len(command) > 1 else None)
    if command[0] == '/kick' and len(command) > 1:
        team = int(command[2]) - 1 if len(command) > 2 and command[2].isdigit() else None
        for client in ctx.clients:
            if client.auth and client.name.lower() == command[1].lower() and (team is None or team == client.team):
                if client.socket and not client.socket.closed:
                    await client.socket.close()

    if command[0] == '/forfeitslot' and len(command) > 1 and command[1].isdigit():
        if len(command) > 2 and command[2].isdigit():
            team = int(command[1]) - 1
            slot = int(command[2])
        else:
            team = 0
            slot = int(command[1])
        MultiServer.forfeit_player(ctx, team, slot)
    if command[0] == '/forfeitplayer' and len(command) > 1:
        team = int(command[2]) - 1 if len(command) > 2 and command[2].isdigit() else None
        for client in ctx.clients:
            if client.auth and client.name.lower() == command[1].lower() and (team is None or team == client.team):
                if client.socket and not client.socket.closed:
                    MultiServer.forfeit_player(ctx, client.team, client.slot)
    if command[0] == '/senditem' and len(command) > 2:
        [(player, item)] = re.findall(r'\S* (\S*) (.*)', message)
        if item in Items.item_table:
            for client in ctx.clients:
                if client.auth and client.name.lower() == player.lower():
                    new_item = MultiClient.ReceivedItem(Items.item_table[item][3], "cheat console", client.slot)
                    MultiServer.get_received_items(ctx, client.team, client.slot).append(new_item)
                    MultiServer.notify_all(ctx, 'Cheat console: sending "' + item + '" to ' + client.name)
            MultiServer.send_new_items(ctx)
            return f"Item sent: {item}"
        else:
            return f"Unknown item: {item}"

    if command[0][0] != '/':
        MultiServer.notify_all(ctx, '[Server]: ' + message)


if __name__ == '__main__':
    APP.run(host='127.0.0.1', port=5000, use_reloader=False)
