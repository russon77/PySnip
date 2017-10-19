"""
bot_zombie.py

original script(https://dl.dropboxusercontent.com/u/31711941/aos/basicbot.py) by hompy
modified by Beige (Laon)

version : 20150721

requires adding the 'local' attribute to server.py's ServerConnection
 
*** 201,206 ****
--- 201,207 ----
      last_block = None
      map_data = None
      last_position_update = None
+     local = False
       
      def __init__(self, *arg, **kw):
          BaseConnection.__init__(self, *arg, **kw)
*** 211,216 ****
--- 212,219 ----
          self.rapids = SlidingWindow(RAPID_WINDOW_ENTRIES)
       
      def on_connect(self):
+         if self.local:
+             return
          if self.peer.eventData != self.protocol.version:
              self.disconnect(ERROR_WRONG_VERSION)
              return
 
<admin commands>

/addbot [amount] [green|blue]
/toggleai

"""


from math import cos, sin, floor
from enet import Address
from pyspades.protocol import BaseConnection
from pyspades.server import input_data, weapon_input, set_tool, grenade_packet, block_action, set_color
from pyspades.world import Grenade
from pyspades.common import Vertex3, make_color
from pyspades.collision import vector_collision, collision_3d
from pyspades.constants import *
from commands import admin, add, name, get_team
from pyspades.world import *
import random
from twisted.internet.task import LoopingCall
from math import modf
from pyspades.color import *

S_NO_RIGHTS = 'No administrator rights!'
S_TIME_OF_DAY = 'Time of day: {hours:02d}:{minutes:02d}'
S_SPEED = 'Day cycle speed is {multiplier}'
S_SPEED_SET = 'Day cycle speed changed to {multiplier}'
S_STOPPED = 'Day cycle stopped'

try:
    from preservecolor import destroy_block
except ImportError:
    def destroy_block(protocol, x, y, z):
        if not protocol.map.destroy_point(x, y, z):
            return False
        if protocol.map.get_solid(x, y, z) is None:
            return False
        block_action.value = DESTROY_BLOCK
        block_action.player_id = 32
        block_action.x = x
        block_action.y = y
        block_action.z = z
        protocol.send_contained(block_action, save = True)
        protocol.update_entities()
        return True

def unr(n):
    if n - floor(n) > 0:
        return n + 1
    if n - floor(n) < 0:
        return n - 1
    if n - floor(n) == 0:
        return False          

@admin
@name('addbot')
def add_bot(connection, amount = None, team = None):
    protocol = connection.protocol
    if team:
        bot_team = get_team(connection, team)
    blue, green = protocol.blue_team, protocol.green_team
    amount = int(amount or 1)
    for i in xrange(amount):
        if not team:
            bot_team = blue if blue.count() < green.count() else green
        bot = protocol.add_bot(bot_team)
        if not bot:
            return "Added %s bot(s)" % i
    return "Added %s bot(s)" % amount


@admin
@name('dayspeed')
def day_speed(connection, value = None):
    if value is None:
        return S_SPEED.format(multiplier = connection.protocol.time_multiplier)
    value = float(value)
    protocol = connection.protocol
    protocol.time_multiplier = value
    if value == 0.0:
        if protocol.daycycle_loop.running:
            protocol.daycycle_loop.stop()
        return S_STOPPED
    else:
        if not protocol.daycycle_loop.running:
            protocol.daycycle_loop.start(protocol.day_update_frequency)
        return S_SPEED_SET.format(multiplier = value)

@admin
@name('daytime')
def day_time(connection, value = None):
    if value is not None:
        if not connection.admin:
            return S_NO_RIGHTS
        value = float(value)
        if value < 0.0:
            raise ValueError()
        connection.protocol.current_time = value
        connection.protocol.update_day_color()
    f, i = modf(connection.protocol.current_time)
    return S_TIME_OF_DAY.format(hours = int(i), minutes = int(f * 60))

add(day_speed)
add(day_time)
add(add_bot)

class LocalPeer:
    address = Address('255.255.255.255', 0)
    roundTripTime = 0.0
    
    def send(self, *arg, **kw):
        pass
    
    def reset(self):
        pass

def apply_script(protocol, connection, config):
    class BotProtocol(protocol):
        bots = None
        ai_enabled = True
        strong = False

        current_color = None
        current_time = None
        daycycle_loop = None
        day_duration = None
        day_update_frequency = None
        time_multiplier = None
        day_colors = [
            ( 0.00, (0.05,   0.05, 0.05), False),
            ( 4.00, (0.05,   0.77, 0.05), False),
            ( 5.00, (0.0694, 0.77, 0.78), True),
            ( 5.30, (0.0361, 0.25, 0.95), False),
            ( 6.00, (0.56,   0.18, 0.94), False),
            ( 9.00, (0.5527, 0.24, 0.94), False),
            (12.00, (0.5527, 0.41, 0.95), False),
            (19.50, (0.56,   0.28, 0.96), False),
            (20.00, (0.15,   0.33, 0.87), False),
            (20.25, (0.11,   0.49, 0.94), False),
            (20.50, (0.1056, 0.69, 1.00), False),
            (22.50, (0.1,    0.69, 0.1 ), True),
            (23.00, (0.05,   0.05, 0.05), False)]

        messages_sent = {'night': False, 'day': False}

        def __init__(self, *arg, **kw):
            protocol.__init__(self, *arg, **kw)
            self.daycycle_loop = LoopingCall(self.update_day_color)
            self.reset_daycycle()

            # default to 28 bots, leaving room for 4 humans
            [self.add_bot(self.green_team) for _ in xrange(28)]

        def add_bot(self, team):
            if len(self.connections) + len(self.bots) >= 32:
                return None
            bot = self.connection_class(self, None)
            bot.join_game(team)
            self.bots.append(bot)
            return bot

        def on_world_update(self):
            if self.bots and self.ai_enabled and \
               (self.current_time > 20.00 or self.current_time < 8.00):
                for bot in self.bots:
                    bot.update()
            else:
                for bot in self.bots:
                    bot.flush_input()
                    
            protocol.on_world_update(self)
        
        def on_map_change(self, map):
            self.reset_daycycle()
            self.bots = []
            protocol.on_map_change(self, map)
        
        def on_map_leave(self):
            for bot in self.bots[:]:
                bot.disconnect()
            self.bots = None
            protocol.on_map_leave(self)
            
        def reset_daycycle(self):
            if not self.daycycle_loop:
                return
            self.current_color = None
            self.current_time = 7.00
            self.day_duration = 24 * 60 * 60.00
            self.day_update_frequency = 0.1
            self.time_multiplier = 250.0 # this controls how fast the day/night cycle changes
            self.time_step = 24.00 / (self.day_duration /
                self.day_update_frequency)
            self.target_color_index = 0
            self.next_color()
            if not self.daycycle_loop.running:
                self.daycycle_loop.start(self.day_update_frequency)
        
        def update_day_color(self):
            if self.current_time >= 24.00:
                self.current_time = wrap(0.00, 24.00, self.current_time)

            while (self.current_time < self.start_time or
                self.current_time >= self.target_time):
                self.next_color()
                self.target_time = self.target_time or 24.00
            t = ((self.current_time - self.start_time) /
                (self.target_time - self.start_time))
            if self.hsv_transition:
                new_color = interpolate_hsb(self.start_color, 
                    self.target_color, t)
                new_color = hsb_to_rgb(*new_color)
            else:
                new_color = interpolate_rgb(self.start_color, 
                    self.target_color, t)
            if (self.current_color is None or
                rgb_distance(self.current_color, new_color) > 3):
                self.current_color = new_color
                self.set_fog_color(self.current_color)
            self.current_time += self.time_step * self.time_multiplier
        
        def next_color(self):
            self.start_time, self.start_color, _ = (
                self.day_colors[self.target_color_index])
            self.target_color_index = ((self.target_color_index + 1) %
                len(self.day_colors))
            self.target_time, self.target_color, self.hsv_transition = (
                self.day_colors[self.target_color_index])
            if not self.hsv_transition:
                self.start_color = hsb_to_rgb(*self.start_color)
                self.target_color = hsb_to_rgb(*self.target_color)
                
    class BotConnection(connection):
        aim = None
        last_aim = None
        aim_at = None
        input = None
        grenade_call = None
        ticks_stumped = 0
        ticks_stumped2 = 0
        ticks_stumped3 = 0
        last_pos = None
        distance_to_aim = None
        jump_count = 0
        spade_count = 0
        sec = 15
        sec2 = 15
        discar = 0
        knock = 4
        
        _turn_speed = None
        _turn_vector = None
        def _get_turn_speed(self):
            return self._turn_speed
        def _set_turn_speed(self, value):
            self._turn_speed = value
            self._turn_vector = Vertex3(cos(value), sin(value), 0.0)
        turn_speed = property(_get_turn_speed, _set_turn_speed)
        
        def __init__(self, protocol, peer):
            if peer is not None:
                return connection.__init__(self, protocol, peer)
            self.local = True
            connection.__init__(self, protocol, LocalPeer())
            self.on_connect()
            #~ self.saved_loaders = None
            self._send_connection_data()
            self.send_map()
            
            self.aim = Vertex3()
            self.target_orientation = Vertex3()
            self.last_pos = Vertex3()
            self.turn_speed = 0.15 # rads per tick
            self.input = set()
            
        def join_game(self, team):
            self.name = 'ZOMBIE%s' % str(self.player_id)
            self.team = team
            self.set_weapon(RIFLE_WEAPON, True)
            self.protocol.players[(self.name, self.player_id)] = self
            self.on_login(self.name)
            self.spawn()
        
        def update(self):
            obj = self.world_object
            ori = obj.orientation
            pos = obj.position
            
            if self.world_object.dead:
                return

            for i in self.team.other.get_players():
                if (i.world_object) and (not i.world_object.dead) and (not i.god): 
                    some = Vertex3()
                    some.set_vector(i.world_object.position)
                    some -= pos
                    distance_to_new_aim = some.normalize()
                    if distance_to_new_aim < self.distance_to_aim:
                        self.aim_at = i
                        self.last_aim = None
                        
            if self.aim_at and self.aim_at.world_object:
                real_aim_at_pos = self.aim_at.world_object.position
                if obj.can_see(
                    self.aim_at.world_object.position.x, self.aim_at.world_object.position.y, self.aim_at.world_object.position.z):
                    aim_at_pos = self.aim_at.world_object.position
                    self.last_aim = Vertex3()
                    self.last_aim.set_vector(aim_at_pos)
                else:
                    if self.last_aim is None:
                        aim_at_pos = self.aim_at.world_object.position
                    else:
                        aim_at_pos = self.last_aim
                self.aim.set_vector(aim_at_pos)
                self.aim -= pos
                self.distance_to_aim = self.aim.normalize()
                self.input.add('up')
                self.input.add('sprint')
                self.last_pos -= pos
                moved = Vertex3()
                moved.set_vector(self.last_pos)
                distance_moved = self.last_pos.length_sqr()
                self.last_pos.set_vector(pos)
                
                if self.distance_to_aim <= 2.0:
                    self.target_orientation.set_vector(self.aim)
                    self.input.discard('sprint')
                    self.input.add('primary_fire')  
                    self.left_spade()
                else:
                    some = Vertex3()
                    some.x, some.y, some.z = self.aim.x, self.aim.y, 0
                    self.target_orientation.set_vector(some)
                    
                if (self.world_object.velocity.z != 0 and abs(floor(aim_at_pos.x) - floor(pos.x)) <= 10 and abs(floor(aim_at_pos.y) - floor(pos.y)) <= 10) or (
				abs(floor(aim_at_pos.x) - floor(pos.x)) <= 1 and abs(floor(aim_at_pos.y) - floor(pos.y)) <= 1):
                    try:
                        if aim_at_pos == self.aim_at.world_object.position:
                            if pos.z > aim_at_pos.z:
                                self.input.add('jump')
                                self.ticks_stumped3 += 1
                                self.sec = 15
                                self.ticks_stumped = 0  
                                self.ticks_stumped2 = 0
                                if self.ticks_stumped3 >= self.sec2:
                                    self.sec2 += 15
                                    self.input.add('primary_fire')
                                    self.dig(0)
                            elif pos.z < aim_at_pos.z and abs(floor(aim_at_pos.x) - floor(pos.x) <= 1) and abs(floor(aim_at_pos.y) - floor(pos.y)) <= 1:
                                self.ticks_stumped3 += 1
                                if self.ticks_stumped3 >= self.sec2:
                                    self.input.add('primary_fire')
                                    self.sec2 += 15
                                    self.dig(2)
                        else:
                            self.last_aim = None  
                    except AttributeError:
                        self.last_aim = None
                else:
                    self.sec2 = 15
                    self.ticks_stumped3 = 0
                    if (moved.x == 0) or (moved.y == 0):
                        self.input.discard('sprint')
                        self.ticks_stumped += 1 
                        #if (self.nature == 0):
                        self.input.add('jump')
                        if (self.ticks_stumped >= self.sec):
                            self.input.add('primary_fire')                      
                            if self.sec % 30 == 0:
                                i = 1
                            else:
                                if floor(aim_at_pos.z) < floor(pos.z): # up
                                    i = 0
                                elif floor(aim_at_pos.z) > floor(pos.z): # down
                                    i = 2
                                elif floor(aim_at_pos.z) == floor(pos.z):
                                    i = 1
                            self.sec += 15
                            self.input.add('primary_fire')
                            self.dig(i)
                    #elif distance_moved < 0.05:
                      #  self.ticks_stumped2 += 1
                        #if self.ticks_stumped2 >= 600:
                          #  self.kill()
                    # elif (moved.x + moved.y) / 2 < 0.0066
                    else:
                        self.sec = 15
                        #else:
                            #self.sec = 300
                        self.ticks_stumped = 0  
                        self.ticks_stumped2 = 0
            else:
                self.last_aim = None
                self.distance_to_aim = float('inf')               
                
            # orientate towards target
            diff = ori - self.target_orientation
            diff.z = 0.0
            diff = diff.length_sqr()
            if diff > 0.001:
                p_dot = ori.perp_dot(self.target_orientation)
                if p_dot > 0.0:
                    ori.rotate(self._turn_vector)
                else:
                    ori.unrotate(self._turn_vector)
                new_p_dot = ori.perp_dot(self.target_orientation)
                if new_p_dot * p_dot < 0.0:
                    ori.set_vector(self.target_orientation)
            else:
                ori.set_vector(self.target_orientation)

            obj.set_orientation(*ori.get())
            self.flush_input()

        def flush_input(self):
            input = self.input
            world_object = self.world_object
            pos = world_object.position
            #self.overlap = False
           # if self.knock < 4:
             #   self.knock += 1
              #  input.discard('sprint')
            if not self.world_object.dead:
                if self.local:
                    for i in self.team.get_players():
                        if (i.world_object) and (not i.world_object.dead) and (not i == self):
                            pos2 = i.world_object.position
                            if floor(pos2.x) == floor(pos.x) and floor(pos2.y) == floor(pos.y):
                                if self.protocol.loop_count % 30 == 0:
                                    self.discar = random.randint(-3, 10)
                                elif self.discar == 3 or self.discar == 4 or self.discar == 5:
                                    input.add('left')
                                elif self.discar == 6 or self.discar == 7 or self.discar == 8:
                                    input.add('right')
                                elif self.discar == 9:
                                    input.add('right')
                                    input.discard('up')
                                elif self.discar == 10:
                                    input.add('left')
                                    input.discard('up')
                                break
                    if self.protocol.strong:
                        jump_delay = 20
                    else:
                        jump_delay = 30
                    if self.protocol.loop_count - self.jump_count < jump_delay:
                        input.discard('jump')
                    else:
                        self.jump_count = self.protocol.loop_count

                input_changed = not (
                    ('up' in input) == world_object.up and
                    ('down' in input) == world_object.down and
                    ('left' in input) == world_object.left and
                    ('right' in input) == world_object.right and
                    ('jump' in input) == world_object.jump and
                    ('crouch' in input) == world_object.crouch and
                    ('sneak' in input) == world_object.sneak and
                    ('sprint' in input) == world_object.sprint)
                if input_changed:
                    if not self.freeze_animation:
                        if ('sprint' in input) and (not 'jump' in input):
                            if self.protocol.strong:
                                if not self.protocol.map.get_solid(self.aim.x + pos.x, self.aim.y + pos.y, pos.z):
                                    self.set_location((self.aim.x + pos.x, self.aim.y + pos.y, pos.z))
                            
                        world_object.set_walk('up' in input, 'down' in input,
                            'left' in input, 'right' in input)
                        world_object.set_animation('jump' in input, 'crouch' in input,
                            'sneak' in input, 'sprint' in input)
                    if (not self.filter_visibility_data and
                        not self.filter_animation_data):
                        input_data.player_id = self.player_id
                        input_data.up = world_object.up
                        input_data.down = world_object.down
                        input_data.left = world_object.left
                        input_data.right = world_object.right
                        input_data.jump = world_object.jump
                        input_data.crouch = world_object.crouch
                        input_data.sneak = world_object.sneak
                        input_data.sprint = world_object.sprint
                        self.protocol.send_contained(input_data)
                primary = 'primary_fire' in input
                secondary = 'secondary_fire' in input
                shoot_changed = not (
                    primary == world_object.primary_fire and
                secondary == world_object.secondary_fire)
                if shoot_changed:
                    if primary != world_object.primary_fire:
                        if self.tool == WEAPON_TOOL:
                            self.weapon_object.set_shoot(primary)
                        if self.tool == WEAPON_TOOL or self.tool == SPADE_TOOL:
                            self.on_shoot_set(primary)
                    world_object.primary_fire = primary
                    world_object.secondary_fire = secondary
                    if not self.filter_visibility_data:
                        weapon_input.player_id = self.player_id
                        weapon_input.primary = primary
                        weapon_input.secondary = secondary
                        self.protocol.send_contained(weapon_input)
                # hit = 'value' in input
                # if hit_changed:
                input.clear()
        
        def set_tool(self, tool):
            if self.on_tool_set_attempt(tool) == False:
                return
            self.tool = tool
            if self.tool == WEAPON_TOOL:
                self.on_shoot_set(self.world_object.fire)
                self.weapon_object.set_shoot(self.world_object.fire)
            self.on_tool_changed(self.tool)
            if self.filter_visibility_data:
                return
            set_tool.player_id = self.player_id
            set_tool.value = self.tool
            self.protocol.send_contained(set_tool)
        
        def throw_grenade(self, time_left):
            return False

        def left_spade(self):
            obj = self.world_object
            pos = obj.position
            ori = obj.orientation
            
            if self.world_object.dead: 
                return
            if self.protocol.loop_count - self.spade_count < 24:
                return
            else:
                self.spade_count = self.protocol.loop_count
            # self.spade_delay = True
            for player in self.team.other.get_players():
                if (player.world_object) and (not player.world_object.dead):
                   if (vector_collision(pos, player.world_object.position, 3)) and (obj.validate_hit(player.world_object, MELEE, 5)):
                       hit_amount = 10
                       type = MELEE_KILL
                       self.on_hit(hit_amount, player, type, None)
                       player.hit(hit_amount, self, type)

                           
        def dig(self, i):
            if not self.protocol.strong:
                bindo = 10
            else:
                bindo = 40
            obj = self.world_object
            ori = obj.orientation
            pos = obj.position
            map = self.protocol.map

            if self.world_object.dead:
                return
            ix = int(floor(pos.x))
            iy = int(floor(pos.y))
            iz = int(floor(pos.z))
            # self.create_explosion_effect()
            for x in xrange(ix - 1, ix + 2):
                for y in xrange(iy - 1, iy + 2):
                    for z in xrange(iz - 1 + i, iz + 2 + i):
                        rough = random.randint(0, bindo)
                        if rough == 0:
                            if z > 61 or not destroy_block(self.protocol, x, y, z):
                                return
                            if map.get_solid(x, y, z):
                                map.remove_point(x, y, z)
                                map.check_node(x, y, z, True)
                            self.on_block_removed(x, y, z)
                        else:
                            continue

        def create_explosion_effect(self):
            self.protocol.world.create_object(Grenade, 0.0, self.world_object.position, None, Vertex3(), None)
            grenade_packet.value = 0.0
            grenade_packet.player_id = 32
            grenade_packet.position = self.world_object.position.get()
            grenade_packet.velocity = (0.0, 0.0, 0.0)
            self.protocol.send_contained(grenade_packet)
        
        def on_spawn(self, pos):
            if not self.local:
                # self.chaser = 0
                return connection.on_spawn(self, pos)
            self.world_object.set_orientation(1.0, 0.0, 0.0)
            self.set_tool(SPADE_TOOL)
            self.aim_at = None
            self.spade_count = 0
            self.jump_count = 0
            self.sec = 15
            self.sec2 = 15
            self.ticks_stumped = 0
            self.ticks_stumped2 = 0
            self.ticks_stumped3 = 0
            self.last_pos.set(*pos)
            connection.on_spawn(self, pos)
            
        def on_connect(self):
            if self.local:
                return connection.on_connect(self)
            max_players = min(32, self.protocol.max_players)
            protocol = self.protocol
#            if len(protocol.connections) + len(protocol.bots) > max_players:
#                protocol.bots[-1].disconnect()
            connection.on_connect(self)
        
        def on_disconnect(self):
            if self.team == self.protocol.blue_team:  
                # self.chaser = []            
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            connection.on_disconnect(self)
            
        def on_team_changed(self, old_team):
            if old_team == self.protocol.blue_team:  
                # self.chaser = 0         
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None   
            connection.on_team_changed(self, old_team)                         
        
        def on_kill(self, killer, type, grenade): 
            pos = self.world_object.position
            # if self.grenade_call is not None:
                # self.grenade_call.cancel()
                # self.grenade_call = None 
            if not self.local and type == MELEE_KILL:
                # self.chaser = 0
                if killer.local:
                    for bot in self.protocol.bots:
                        if (bot.world_object) and (not bot.world_object.dead) and (not bot == killer):
                            bot.set_location((pos.x, pos.y, pos.z))
                            break
                for bot in self.protocol.bots:
                    if bot.aim_at is self:
                        bot.aim_at = None
            connection.on_kill(self, killer, type, grenade)            
            
        def on_hit(self, hit_amount, hit_player, type, grenade):
            if not self.local and not hit_player.local:
                return False
#            if hit_player.local:
#                return False
            connection.on_hit(self, hit_amount, hit_player, type, grenade)
            
        def on_fall(self, damage):
            return False

        def take_flag(self):
            return
            
        def on_block_destroy(self, x, y, z, mode):  
            if self.tool != SPADE_TOOL or mode == GRENADE_DESTROY:
                return False
        
        def _send_connection_data(self):
            if self.local:
                if self.player_id is None:
                    self.player_id = self.protocol.player_ids.pop()
                return
            connection._send_connection_data(self)
        
        def send_map(self, data = None):
            if self.local:
                self.on_join()
                return
            connection.send_map(self, data)
        
        def timer_received(self, value):
            if self.local:
                return
            connection.timer_received(self, value)
        
        def send_loader(self, loader, acyk = False, byte = 0):
            if self.local:
                return
            return connection.send_loader(self, loader, ack, byte)
    
    return BotProtocol, BotConnection
0
