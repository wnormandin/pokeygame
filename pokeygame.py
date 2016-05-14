#!/usr/bin/env python2.7
## -*- coding: utf-8 -*-

# Built-in modules
import logging
import time
import curses
import sqlite3
import os
from curses import panel

# Custom modules
import pokeyworks as fw
from resources.games import *
from resources.games.tiles import WorldTile
from pokeywins import PokeyMenu
from resources.games.world_generator import WorldGenerator

class PokeyGame(object):

    """ The PokeyGame class is intended to be a SuperClass
    for basic terminal games.  Functionality is not
    guaranteed """

    def __init__(self,game_name,conf_path='pokeygame.json'):

        # Game initialization 
        self.name = game_name
        self.conf = fw.PokeyConfig(conf_path,1,True)
        self.config_init()

        for item in [
                    ('test_mode',False),
                    ('turn',0),
                    ('time_paused',0),
                    ('paused',False)
                    ]:
            setattr(self,*item)

        try:
            log_path = 'tmp/game_log.txt'
            os.stat(log_path)
        except OSError:
            pokeyworks.mkdir('tmp')

        self.logger = fw.setup_logger(
                                      self.name,
                                      self.log_lvl,
                                      'tmp/game_log.txt'
                                      )

        self.world = PokeyWorld(self,self.conf,self.logger)

    def toggle_pause(self,opt=None):
        """ Toggles the game's pause status, opt will allow the status
        to be set, or left alone if already correctly set """

        if opt is not None:
            if opt!=self.paused:
                if self.paused:
                    self.time_paused+=(time.clock()-self.pause_start)
                else:
                    self.pause_start=time.clock()
                self.paused = opt
        else:
            if self.paused:
                self.time_paused+=(time.clock()-self.pause_start)
            else:
                self.pause_start=time.clock()
            self.paused = not self.paused

        self.logger.info('[*] Pause = {0}'.format(self.paused))

    def show_menu(self):
        """ Main menu control function to be run in the curses wrapper """
        curses.curs_set(0)
        self.main_menu.display()

    def start_game(self):
        self.time_game_start = time.clock()
        self.logger.info("[*] Starting Game")
        curses.wrapper(self.show_menu)

    def play(self,screen):
        self.main_menu = PokeyMenu(MenuConfig(self,0),scrn)
        self.world_menu = PokeyMenu(MenuConfig(self,1),scrn)
        self.map_size_menu = PokeyMenu(MenuConfig(self,2),scrn)
        self.stdscreen = screen
        self.show_menu()

    def config_init(self):
        """ Pulls certain values, if they exist, from the game config """

        game_opts = [

            # Execution Options
            ('debug',False),             # Toggle Debug Messaging
            ('log_path',False),          # Turn on logging (w/path)
            ('log_lvl',logging.DEBUG),   # Set log level

            # World Generation Options
            ('flex_limit',3)             # Sets the maximum variance

            ]

        # Attempts to pull each value from the configuration
        # if not in config, the default value defined above
        # is set instead
        for opt in game_opts:
            try:
                setattr(self,opt[0],self.conf.conf_dict[opt[0]])
            except:
                setattr(self,opt[0],opt[1])
                continue

    def handle_error(self,e):
        """ Basic exception handling,rollbacks, and etc """

        if self.mode=='debug':
            raise e
        else:
            if e is KeyboardInterrupt or e is SystemExit:
                if raw_input('Really quit? (y quits)').upper()=='Y':
                    self.failsafe()
                    sys.exit(0)
            else:
                e_string = '[*] Game Error {0}:{1}'.format(type(e),e)
                self.logger.error(e_string)
                self.failsafe()
                sys.exit(1)

    def curses_print_map(self):
        """ Prints the map grid (Starts on floor 1) """
        map_window = self.stdscreen.subwin(5,5)
        map_keypad = map_window.keypad(1)
        map_panel = panel.new_panel(map_window)

        map_panel.update_panels()
        map_panel.top()
        map_panel.show()
        map_window.clear()

        x = 0; y=0; z=0

        # Print map phase
        draw_map(self,[x,y,z])

        def draw_map(game,loc):
            grid = game.world.grid

            z = loc[2]      # Load the current floor (z)

            for x in range(game.conf.x_dim):
                for y in range(game.conf.y_dim):
                    # Draw a map here!
                    pass

class MenuConfig(object):

    """ Curses Menu configuration class """

    main_menu = 0
    world_menu = 1
    map_size_menu = 2

    def __init__(self,game,menu_type):

        if menu_type==MenuConfig.main_menu:
            # Main menu options
            return_items = [
                ('start game',game.play),
                ('world generation menu',game.world_menu.display)
                ]

        elif menu_type==MenuConfig.world_menu:
            # World Generation Options
            return_items = [
                ('set map size',game.map_size_menu.display,None),
                ('generate_map',game.generate_map),
                ('print map',game.curses_print_map),
                ('main menu',game.main_menu.display)
                ]
        elif menu_type==MenuConfig.map_size_menu:
            # Set x / y / z Parameters
            return_items = [
                ('set x ({0})'.format(game.conf.dim_x),game.set_x),
                ('set y ({0})'.format(game.conf.dim_y),game.set_y),
                ('set z ({0})'.format(game.conf.dim_z),game.set_z),
                ('back',game.world_menu.display)
                ]
        else:
            game.handle_error(
                AssertionError('Invalid Menu Type!:{0}'.format(menu_type))
                )
            return_items = False

        self.menu_items = return_items

class PokeyWorld:
    """ The World object at the center of every game, contains a GameGrid """

    def __init__(self,game,conf,logger):
        self.logger = logger
        self.game = game
        self.conf = conf
        self.logger.info("[*] Beginning PokeyWorld Generation")
        self.set_dims(conf)
        self.world_gen = self.grid_init_check()

        self.logger.debug("\tChecking dimensions against template...")
        assert self.check_dimensions(), 'Dimension conflict! Check your conf'
        self.logger.debug("\tDimensions passed!")

        self.populate_tiles()

    def populate_tiles(self):
        """ Fills grid(x,y,z)[2] with WorldTile tiles """

        # grid format :
        # grid(x,y,z)[0]: A valid WorldTile type (i.e. WorldTile.door)
        # grid(x,y,z)[1]: A list of ASCII color or format codes for ColorIze
        # grid(x,y,z)[2]: The tile object

        self.t_count = 0    # Tile count, increment for each tile added
        self.build_start = time.clock()
        self.logger.info("[*] Starting world building script")

        script_list = [
                    self.build_boss_room,
                    self.build_rooms,
                    self.build_halls,
                    self.build_doors,
                    self.build_chests,
                    self.build_traps,
                    self.build_mobs,
                    self.build_npcs
                    ]
        for func in script_list:
            self.logger.debug("\tRunning {}".format(func.__name__))
            if not func():
                e_text = "Build script failed : {}".format(func.__name__)
                raise AssertionError(e_text)

        self.logger.info("[*] World building script completed")
        self.logger.debug("\tTiles Placed : {}".format(self.t_count))
        build_time = time.clock()-self.build_start
        self.logger.debug("\tTook {}s".format(build_time))
        self.logger.debug("\tTiles/s : {}".format(t_count/build_time))

    def build_rooms(self):
        return self.room_fill(WorldTile.dungeon,tiles.Dungeon)

    def room_fill(self,tile_type,tile,replace=None):
        try:
            for z in self.dim_z:
                for y in self.dim_y:
                    for x in self.dim_x:
                        if len(self.world_gen.grid[x,y,z])==2:
                            if self.world_gen.grid[x,y,z][0]==tile_type:
                                self.world_gen.grid[x,y,z][2]==tile()
                                if replace is not None:
                                    self.world_gen.grid[x,y,z][0]=replace
                                self.t_count += 1
            retval = True
        except:
            retval = False
            raise
        return retval

    def build_doors(self):
        return True

    def build_halls(self):
        return self.room_fill(WorldTile.hallway,tiles.Hallway)

    def build_boss_room(self):
        # Locate the exit waypoint
        center = self.world_gen.find_tile(self.dim_z,WorldTile.exit_point)
        # Build a door here and lock it
        self.place_door(center,True)
        # Fill the room with Boss Room tiles
        self.fill_room(center,WorldTile.boss)

    def build_traps():
        return True

    def build_chests():
        return True

    def build_mobs():
        return True

    def build_npcs():
        return True

    def place_door(self,position,locked=False):

        assert isinstance(position,tuple), 'Invalid pos: {}'.format(position)
        assert len(self.world_gen.grid[position])==2, 'Tile already filled!'

        if locked:
            door = tiles.LockedDoor
        else:
            door = tiles.Door
        self.world_gen.grid[position][2]=door()

    def fill_boss_room(self,center,tile):
        # Detects the room size and then loops, filling
        # a room in world_gen.grid[2] 

        c = center
        x,y,z = c

        for i in range(self.world_gen.room_variance):
            for t in [(-i,i,0),(i,i,0),(-i,-i,0),(i,-i,0)]:
                this_test = (c[0]+t[0],c[1]+t[1],c[2]+t[2])
                if self.world_gen.grid[this_test]==WorldTile.dungeon:
                    result = True
                else:
                    result = False
                if not result:
                    room_size = i-1
                    break
            if not result:
                break

        assert room_size > 0, 'Boss room size cannot be zero!'
        assert room_size <= self.world_gen.room_variance, \
                            'Boss room cannot be larger than room_variance'

        tile = tiles.BossRoom
        for y_offset in range(-room_size,room_size):
            for x_offset in range(-room_size,room_size):
                this_point = (
                            min(self.dim_x,x+x_offset),
                            min(self.dim_y,y+y_offset),
                            z
                            )
                if self.world_gen.grid[this_point][0]==WorldTile.dungeon:
                    self.world_gen.grid[this_point][2]=tile()
                    # Change the map char to avoid overwriting later
                    self.world_gen.grid[this_point][0]=WorldTile.boss
                    self.t_count += 1

    def set_dims(self,conf):
        self.logger.debug("\tGrabbing map dimensions")
        self.dim_x = int(conf.dim_x)
        self.dim_y = int(conf.dim_y)
        self.dim_z = int(conf.dim_z)


    def check_dimensions(self):
        c_z = int(self.conf.dim_z)
        c_y = int(self.conf.dim_y)
        c_x = int(self.conf.dim_x)
        x = self.dim_x
        y = self.dim_y
        z = self.dim_z

        if all((c_z==z,c_y==y,c_x==x)):
            return True
        else:
            for line in print_dimensions((z,c_z),(y,c_y),(z,c_x)):
                self.logger.debug(line)
            return False

    def print_dimensions(self,z,y,x):
        col_size = 10
        separator = "\t"
        separator += "=" * (col_size*4)
        separator += "\n"
        retval = "\t{1:{^{0}}|{2:^{0}}|{3:^{0}}\n".format(col_size,
                                            "DIM","CONFIG","WORLD")
        retval += separator
        for item in [x,y,z]:
            retval += "\t{1:{^{0}}|{2:^{0}}|{3:^{0}}\n".format(col_size,
                                            item.__name__,*item)
        retval += separator
        return retval

    def grid_insert(self,tile,loc):
        try:
            x,y,z = loc[0],loc[1],loc[2]
            self.grid[x,y,z][2]=tile
        except Exception as e:
            self.game.handle_error(e)
            return False
        else:
            return True

    def get_tile(self,loc):
        try:
            assert len(grid[loc[0],loc[1],loc[2]])==3, \
                        "Missing tile : {}".format(grid[loc[0],loc[1],loc[2]])
            return grid[loc[0],loc[1],loc[2]][2]

        except Exception as e:
            self.game.handle_error(e)
            return False

    def grid_init_check(self):
        """ Verifies the given dimensions & returns the WorldGenerator gird """
        #try:
            #assert isinstance(self.conf.dim_x,int),(
            #    'Bad dimension x:{0}'.format(self.conf.dim_x))
            #assert isinstance(self.conf.dim_y,int),(
            #    'Bad dimension y:{0}'.format(self.conf.dim_y))
            #assert isinstance(self.conf.dim_z,int),(
            #    'Bad dimension z:{0}'.format(self.conf.dim_z))
        #except AssertionError:
            #raise

        debug = True if self.conf.debug=='1' else False
        silent = True if self.conf.silent=='1' else False
        verbose = True if self.conf.verbose=='1' else False
        post_check = True if self.conf.auto_check=='1' else False

        max_trys = 3
        while True:
            try:
                world_gen=WorldGenerator(
                                        debug,silent,
                                        False,None,None,
                                        self.dim_x,
                                        self.dim_y,
                                        self.dim_z,
                                        0,verbose,self.logger,2,
                                        post_check,
                                        self.conf.path_alg
                                        )
            except:
                if max_trys > 0:
                    raise
                else:
                    continue
            else:
                print world_gen
                return world_gen

class Skill(object):

    """ Generic Skill Class """

    general_type=0
    combat_type=1
    stealth_type=2
    magic_type=3

    def __init__(self,name,skill_type):

        self.name = name
        self.skill_type = skill_type
        self.level = 1

    def assign(self,player,hcp):
        """ Assigns the skill an initial value based on the
        player class archetype chosen (by the hcp parameter)
        Invoked in the PlayerClass init phase """

        # Higher hcp = higher bonus potention (max 100)
        assert hcp <= 100, 'Skill handicap cannot be >100 hcp : {0}'.format(
                                                                        hcp)

        if self.level is not None:
            base,bonus = RandomRoll(player,self,hcp)

            if base and bonus:
                self.level += random.randint(3)+1
            elif base:
                self.level += random.randint(2)

    def increase(self,player):
        """ Chance of bonus skill point """

        if self.level is not None:
            increase_roll = (random.randint(0,player.level))

            if skill.level < (player.level/2):
                bonus_threshold = .5
            else:
                bonus_threshold = .75

            if increase_roll/player.level >= bonus_threshold:
                skill.level +=2
            else:
                skill.level +=1

            return skill.level

        else:
            return None

class RandomRoll(object):

    """ Performs various skill rolls involved in gameplay, lvl
    and player generation, and other generated attributes """

    def __init__(self,player,skill,difficulty):
        """ Takes attributes from the passed skill and difficulty
        to perform a roll and return an action """

        # Lowest possible skill roll == skill lvl - player lvl (or 0)
        lower_bound = max(0,skill.level - player.level)

        # Highest possible skill roll == skill lvl + 2*player level
        upper_bound = skill.level + (2*player.level)

        # Sets critical range (upper percentile to be considered crit)
        crit_range = player.crit_level / 100

        self.roll = random.randint(lower_bound,upper_bound)
        if (self.roll/upper_bound) > (1-crit_range):
            self.crit=True
        else:
            self.crit=False

        if self.roll >= difficulty:
            self.hit=True
        else:
            self.hit=False

        return self.hit, self.crit

class Entity(object):

    """ General attributes/methods for Player/NPC Entities """

    def __init__(self):
        self.trigger_seal = False    # Set to true for Player types
        self.lootable = True
        self.living = True

        # Numeric attributes
        for item in [
                    'attack',
                    'defense',
                    'focus',
                    'resist_fire',
                    'resist_frost',
                    'resist_magic',
                    'resist_poison',
                    'resist_death'
                    ]:
            setattr(self,item,0)

        self.turn_initialize()

    def apply_damage(self,dmg_dict):

        assert dmg_dict['range'] is not None, 'Invalid damage range'

        if dmg_dict['type']=='combat':
            pass
        elif dmg_dict['type']=='magic':
            if dmg_dict['element'] is not None:
                succ,crit = self.resist_roll(dmg_dict['element'])
        else:
            raise AssertionError("Invalid dmg type : {}".format(dmg_dict))

    def apply_spell_damage(elem=None,dmg_rng=None):

        if elem is not None:

            assert dmg_rng is not None, 'Invalid damage range'
            succ,crit = self.resist_roll(elem)

        else:
            succ = crit = False

        if succ and crit:
            return False
        elif succ or crit:
            dmg = dmg_rng[0]
        else:
            dmg = random.randint(dmg_rng)

        self.health -= dmg
        self.living_check()

    def resist_roll(self,elem):
        resist = getattr(self,'resist_{}'.format(elem.__name__))

        return  RandomRoll(self, resist)

    def status_effect(self,effect):

        if effect.value is None:
            setattr(self,effect.name,False)
        else:
            setattr(self,effect.name,True)


    def turn_initialize(self):
        # Boolean status effect attributes
        for bool_item in [
                    'blind',
                    'paralyzed',
                    'slow',
                    'haste',
                    'berzerk',
                    'protected',
                    'immune',
                    'invincible',
                    'stunned'
                    ]:
            setattr(self,bool_item,False)

    def turn_upkeep(self):
        for effect in self.active_effects:
            effect = effect.cast()

        self.active_effects = [e for e in self.active_effects \
                    if e is not None]

    def living_check(self):
        if self.health <= 0:
            self.living = False

    def dead(self):
        assert self.living is not None, 'Invalid living state : None'
        return not self.living

    def process_effects(self):
        """ Processes assigned effects """

        for eff in self.effects:
            if eff.expires < self.turn:
                eff.expired = True
            else:
                args = {
                        'dmg':eff.apply_effect(self)+eff.delta,
                        'resist':eff.resist,
                        'dmg_attr':eff.attr
                        }

                self.proc_dmg_effect(**args)

        self.effects = [e for e in self.effects if not e.expired]

    def proc_dmg_effect(
                        self,
                        dmg_attr='health',
                        resist=None,
                        dmg=0,
                        percent=False
                        ):
        """ Processes entity damage effects and resists """

        # If a resist attribute is passed, the player
        # will attempt to resist the damage
        if resist is not None:
            succ,bonus = RandomRoll(
                                    self,
                                    getattr(self,resist),
                                    75
                                    )
        else:
            succ = bonus = False

        # If the resist roll hits the bonus criteria, no damage
        if succ and bonus:
            dmg = 0

        # If the resist is successful but does not bonus
        # the damage is reduced by 50%
        elif succ:
                dmg = dmg/2

        att_value = getattr(self,dmg_att)

        if percent:
            # Convert dmg to a percentage and deduct from attribute
            p = dmg/100
            setattr(self,dmg_att,att_value-(p*att_value))
        else:
            setattr(self,dmg_att,getattr(self,dmg_att)-dmg)

    def proc_status_effect(
                            self,
                            status_att=None,
                            status_val=False,
                            resist=None
                            ):
        """ Processes entity status effects and resists """

        # If a resist attribute is passed, the player
        # will attempt to resist the status change

        if resist is not None:
            succ,bonus = RandomRoll(
                                    self,
                                    getattr(self,resist),
                                    75
                                    )
        else:
            succ = False

        if succ:
            pass
        else:
            setattr(self,status_att,status_val)

class Player(Entity):

    """ General Player Entity """

    male = 0
    female = 1

    def __init__(
                self,
                skill_list,
                p_name,
                p_age=27,
                p_sex=0
                ):

        Super(Player,self).__init__()

        self.trigger_seal = True

        self.name = p_name
        self.age = p_age
        self.sex = p_sex

        self.level=1
        self.crit_level=1
        self.turn = 0


        self.effects = []

        try:
            self.skills = [skill() for skill in skill_list]
        except:
            self.skills = skill_list

    def player_creation(self):
        """ Player creation script """

    def level_up(self):
        """ Levels up the player, increasing attributes """
        pass


class ColorIze(object):
    """ Allows colorizing (in available terminals)"""

    BLACK_ON_GREEN = '\x1b[1;30;42m'
    BLACK_ON_RED = '\x1b[0;30;41m'
    MAGENTA_ON_BLUE = '\x1b[1;35;44m'
    WHITE_ON_BLUE = '\x1b[5;37;44m'
    PURPLE = '\033[95m'
    CYAN = '\033[96m'
    DARKCYAN = '\033[36m'
    BLUE = '\033[94m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

    def __init__(self,val,opts):
        """ Takes the val, and wraps it in the passed opts """

        assert isinstance(opts,(list,tuple)), 'Invalid color option list!'

        retval = ''
        for opt in opts:
            retval += opt

        retval += '{}{}'.format(val,ColorIze.END)

        self.colorized = retval

        return

class StatusEffect(object):
    """ Temporary status effects on players """

    def __init__(
                self,
                se_name,
                se_attr,
                se_delta,
                expires=None,
                proc=None,
                proc_args={},
                rate=None
                ):

        self.name = se_name     # StatusEffect name
        self.attr = se_attr     # Attribute to be altered
        self.delta = se_delta   # Amount of damage(or bonus)
        self.proc = proc        # Additional proccessed effects
        self.expires = expires  # Sets expiration turn
        self.expired = False    # Expiration flag

    def apply_effect(self,player):
        self.level = player.level
        succ,crit = RandomRoll(player,self,rate)

        # If a status effect has an additional proc'ed effect,
        # a critical roll success is necessary to trigger it
        # The player might still resist
        if crit:
            if self.proc is not None:
                proc = self.proc
                proc(**self.proc_args)

        return self.process_apply(succ,crit)

    def process_apply(self,succ,crit):
        """ Takes the random roll output and returns the bonus amt """

        if succ and crit:
            bonus = 2
        elif succ:
            bonus = 1
        else:
            bonus = 0

        return bonus

class PlayerClass(object):

    """ Player class archetypes  """
    mage = 0
    fighter = 1
    rogue = 2

    def __init__(self,player,cl_type=1):
        self.type = cl_type

        # Assigns the skill an initial value based on
        # the selected archetype
        for skill in player.skills:
            if skill.skill_type==Skill.combat_type:
                skill.assign(player,100)
            elif skill.skill_type==Skill.magic_type:
                skill.assign(player,0)
            else:
                skill.assign(player,25)

