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
import urllib.parse
import zlib

import aiofiles
import aiohttp
import MultiServer
import shortuuid
import tortoise.exceptions
import websockets
from quart import Quart, abort, jsonify, request
from tortoise import Tortoise

import models
import settings

# MULTIWORLDS = {}

multiworld_servers = {}

APP = Quart(__name__)

@APP.route('/game', methods=['POST'])
async def create_game():
    data = await request.get_json()

    if 'token' in data:
        token = data['token']
        try:
            world = await models.Multiworlds.get(token=token)
        except tortoise.exceptions.DoesNotExist:
            abort(404, description=f'Game with token {token} was not found.')

        if token in multiworld_servers:
            abort(400, description=f'Game with token {token} is already active.')

        ctx = await resume_multiserver(world)
    else:
        token=shortuuid.ShortUUID().random(length=10)
        world = await models.Multiworlds.create(
            token=token,
            multidata_url=data['multidata_url'],
            admin=data['admin'],
            meta=data.get('meta', {}),
            race=data.get('racemode', False),
            noexpiry=data.get('noexpiry', False),
        )

        world.token = token
        await world.save()

        ctx = await init_multiserver(world)

    response = APP.response_class(
        response=json.dumps(get_multiworld_info(world), default=simple_multiworld_converter),
        status=200,
        mimetype='application/json'
    )

    return response


@APP.route('/game', methods=['GET'])
async def get_all_games():
    worlds = await models.Multiworlds.filter(active=True)
    response = APP.response_class(
        response=json.dumps(
            {
                'count': len(worlds),
                'games': [get_multiworld_info(w) for w in worlds]
            },
            default=simple_multiworld_converter),
        status=200,
        mimetype='application/json'
    )
    return response


@APP.route('/game/<string:token>', methods=['GET'])
async def get_game(token):
    world = await models.Multiworlds.get(token=token)

    response = APP.response_class(
        response=json.dumps(get_multiworld_info(world), default=simple_multiworld_converter),
        status=200,
        mimetype='application/json'
    )

    return response


@APP.route('/game/<string:token>/msg', methods=['PUT'])
async def update_game_message(token):
    data = await request.get_json()
    try:
        world = await models.Multiworlds.get(token=token)
    except tortoise.exceptions.DoesNotExist:
        abort(404, description=f'Game with token {token} was not found.')

    if token not in multiworld_servers:
        abort(404, description=f'Game with token {token} is not currently active, but has previously existed.')

    if not 'msg' in data:
        abort(400)

    # Specifically handle /exit command, though this should be handled by server_command_processor
    if data['msg'] == '/exit':
        await close_game(world)
        return jsonify(resp='Game closed.', success=True)

    try:
        resp = await server_command_processor(multiworld_servers[token], data['msg'])
        return jsonify(resp=resp, success=True)
    except Exception as e:
        logging.exception("Exception in server_command_processor")
        return jsonify(resp=str(e), success=False)


@APP.route('/game/<string:token>/<string:param>', methods=['PUT'])
async def update_game_parameter(token, param):
    data = await request.get_json()

    try:
        world = await models.Multiworlds.get(token=token)
    except tortoise.exceptions.DoesNotExist:
        abort(404, description=f'Game with token {token} was not found.')

    if token not in multiworld_servers:
        abort(404, description=f'Game with token {token} is not currently active, but has previously existed.  Please restart the game to update this parameter.')

    if not 'value' in data:
        abort(400)

    if param == 'noexpiry':
        world.noexpiry = data['value']
    elif param == 'admin':
        world.admin = data['value']
    elif param == 'meta':
        world.admin = data['value']
    elif param == 'racemode':
        world.race = data['value']

    await world.save()

    return jsonify(success=True)


@APP.route('/game/<string:token>', methods=['DELETE'])
async def delete_game(token):
    try:
        world = await models.Multiworlds.get(token=token)
    except tortoise.exceptions.DoesNotExist:
        abort(404, description=f'Game with token {token} was not found.')

    if token not in multiworld_servers:
        abort(404, description=f'Game with token {token} is not currently active, but has previously existed.')

    await close_game(world)
    return jsonify(success=True)


@APP.route('/game/<string:token>/cmd', methods=['POST'])
async def kick_player(token, slot, team):
    data = await request.get_json()

    cmd = data.get('command', None)
    if cmd is None:
        abort(400, description='No command specified.')

    try:
        world = await models.Multiworlds.get(token=token)
    except tortoise.exceptions.DoesNotExist:
        abort(404, description=f'Game with token {token} was not found.')

    if token not in multiworld_servers:
        abort(404, description=f'Game with token {token} is not currently active, but has previously existed.')


    ctx = multiworld_servers[token]

    if cmd == 'kick':
        team = data.get('team', None)
        name = data.get('name', None)

        if name is None:
            return jsonify(resp="No player specified.", success=False)

        for client in ctx.clients:
            if client.auth and client.name.lower() == name.lower() and (team is None or team == client.team):
                if client.socket and not client.socket.closed:
                    await client.socket.close()
                    return jsonify(resp=f"Kicked player '{name}'.", success=True)

        return jsonify(resp=f"Player '{name}' not found.", success=False)

    elif cmd == 'senditem':
        player = data.get('player', None)
        item = data.get('item', None)

        if player is None:
            return jsonify(resp="No player specified.", success=False)
        if item is None:
            return jsonify(resp="No item specified.", success=False)

        if item in MultiServer.Items.item_table:
            for client in ctx.clients:
                if client.auth and client.name.lower() == player.lower():
                    new_item = MultiServer.ReceivedItem(MultiServer.Items.item_table[item][3], "cheat console", client.slot)
                    MultiServer.get_received_items(ctx, client.team, client.slot).append(new_item)
                    MultiServer.notify_all(ctx, 'Cheat console: sending "' + item + '" to ' + client.name)
            MultiServer.send_new_items(ctx)
            return jsonify(resp=f"Sent {item} to {player}.", success=True)
        else:
            logging.warning("Unknown item: " + item)
            return f"Unknown item: {item}"

    elif cmd == 'forfeitplayer':
        team = data.get('team', None)
        name = data.get('name', None)
        if name is None:
            return jsonify(resp="No name specified.", success=False)
        for client in ctx.clients:
            if client.auth and client.name.lower() == name and (team is None or team == client.team):
                if client.socket and not client.socket.closed:
                    MultiServer.forfeit_player(ctx, client.team, client.slot)
                    return jsonify(resp=f"Forfeited player '{name}'.", success=True)

    return jsonify(resp=f"Invalid command {cmd}", success=False)


@APP.route('/jobs/cleanup/<int:minutes>', methods=['POST'])
async def cleanup(minutes):
    worlds_cleaned = []
    worlds = await models.Multiworlds.filter(active=True)
    for world in worlds:
        if world.updated_at < datetime.datetime.now()-datetime.timedelta(minutes=minutes) and not world.noexpiry:
            worlds_cleaned.append(world.token)
            await close_game(world)

    return jsonify(success=True, count=len(worlds_cleaned), cleaned_worlds=worlds_cleaned)


@APP.errorhandler(400)
def bad_request(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.code)


@APP.errorhandler(404)
def game_not_found(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.code)


@APP.errorhandler(500)
def something_bad_happened(e):
    return jsonify(success=False, name=e.name, description=e.description, status_code=e.code)

def get_multiworld_info(world: models.Multiworlds):
    return {
        'id': world.id,
        'token': world.token,
        'port': get_server_port(world.token),
        'noexpiry': world.noexpiry,
        'admin': world.admin,
        'meta': world.meta,
        'created_at': world.created_at,
        'updated_at': world.updated_at,
        'active': world.active,
        'open': get_open_status(world.token),
        'players': get_player_list(world.token),
        'connected_clients': get_connected_clients(world.token),
    }

def get_open_status(token):
    if token in multiworld_servers:
        return True

    return False

def get_player_list(token):
    try:
        ctx = multiworld_servers[token]
    except KeyError:
        return None

    teams = [team for (team, slot), name in ctx.player_names.items()]
    teams = list(set(teams))

    return [
        [name for (team, slot), name in ctx.player_names.items() if team == t] for t in teams
    ]

def get_connected_clients(token):
    try:
        ctx: MultiServer.Context = multiworld_servers[token]
    except KeyError:
        return None

    auth_clients = [c for c in ctx.clients if c.auth]
    auth_clients.sort(key=lambda c: (c.team, c.slot))

    return [
        {
            'team': c.team,
            'slot': c.slot,
            'name': c.name,
            'send_index': c.send_index,
            'auth': c.auth,
        } for c in auth_clients
    ]

def get_server_port(token):
    try:
        ctx = multiworld_servers[token]
    except KeyError:
        return None

    try:
        _, port = ctx.server.ws_server.sockets[0].getsockname()
    except IndexError:
        return None

    return port

async def close_game(world: models.Multiworlds):
    world.active = False
    await world.save()
    ctx: MultiServer.Context = multiworld_servers[world.token]
    ctx.server.ws_server.close()
    del multiworld_servers[world.token]


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


# async def save_worlds():
#     async with aiofiles.open('data/saved_worlds.json', 'w') as save:
#         await save.write(json.dumps(MULTIWORLDS, default=simple_multiworld_converter))
#         await save.flush()


@APP.before_serving
async def load_worlds():
    # try:
    #     async with aiofiles.open('data/saved_worlds.json', 'r') as save:
    #         saved_worlds = json.loads(await save.read())
    # except FileNotFoundError:
    #     saved_worlds = []
    #     print('saved_worlds.json not found, continuing...')

    worlds = await models.Multiworlds.filter(active=True)

    for world in worlds:
        print(f"Restoring {world.token}")
        try:
            await resume_multiserver(world)
        except FileNotFoundError:
            print(f"Failed to restore {world.token}, marking this server is inactive and continuing...")
            world.active = False
            await world.save()

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


async def init_multiserver(world: models.Multiworlds):
    port = get_valid_multiworld_port()

    token = world.token

    async with aiohttp.request(method='get', url=world.multidata_url, headers={'User-Agent': 'SahasrahBot Multiworld Service'}) as resp:
        binary = await resp.read()

    async with aiofiles.open(f"data/{token}_multidata", "wb") as multidata_file:
        await multidata_file.write(binary)

    # crude check that it's a valid multidata file
    json.loads(zlib.decompress(binary).decode("utf-8"))

    ctx = await open_multiserver(
        port,
        f"data/{token}_multidata",
        racemode=world.race
    )

    multiworld_servers[token] = ctx

    world.active = True
    world.port = port
    await world.save()

    return ctx

async def resume_multiserver(world: models.Multiworlds):
    port = get_valid_multiworld_port(world.port)

    token = world.token
    if token in multiworld_servers:
        raise Exception(f'Game with token {token} already exists.')

    async with aiofiles.open(f"data/{token}_multidata", "rb") as multidata_file:
        binary = await multidata_file.read()

    # crude check that it's a valid multidata file
    json.loads(zlib.decompress(binary).decode("utf-8"))

    ctx = await open_multiserver(
        port,
        f"data/{token}_multidata",
        racemode=world.race
    )

    multiworld_servers[token] = ctx

    world.active = True
    world.port = port
    await world.save()

    return ctx

def get_valid_multiworld_port(port=None):
    if port is None:
        port = random.randint(30000, 35000)

    attempts = 0
    while is_port_in_use(port):
        port = random.randint(30000, 35000)
        attempts += 1
        if attempts > 20:
            raise Exception("Could not find open port for multiserver.")

    return port

async def open_multiserver(port: int, multidatafile: str, racemode: bool=False):
    logging.basicConfig(format='[%(asctime)s] %(message)s', level=getattr(logging, "INFO", logging.INFO))

    ctx = MultiServer.Context('0.0.0.0', port, None)
    MultiServer.init_lookups(ctx)
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

async def database():
    await Tortoise.init(
        db_url=f'mysql://{settings.DB_USER}:{urllib.parse.quote_plus(settings.DB_PASS)}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}',
        modules={'models': ['models']}
    )

if __name__ == '__main__':
    loop = asyncio.get_event_loop()

    dbtask = loop.create_task(database())
    loop.run_until_complete(dbtask)
    APP.run(host='127.0.0.1', port=5002, use_reloader=False)
