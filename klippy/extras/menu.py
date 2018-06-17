# Basic LCD menu support
#
# Based on the RaspberryPiLcdMenu from Alan Aufderheide, February 2013
# Copyright (C) 2018  Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

class error(Exception):
    pass

class MenuActionBack:
    def __init__(self, name, parent):
        self.name = name
        self.parent = parent

class MenuItem:
    def __init__(self, config):
        self.name = config.get('name')
        self.gcode = config.get('gcode', None)

class MenuInput:
    def __init__(self, config):
        self.name = config.get('name')
        self.gcode = config.get('gcode', None)
        self.input = config.get('input', '')
        self.value = 0.
        self.min = config.getfloat('min', 0.)
        self.max = config.getfloat('max', 0.)
        self.step = config.getfloat('step', 0.)

class MenuGroup:
    def __init__(self, config = None, parent = None):
        self.parent = parent
        self.items = []
        self.name = config.get('name')
        self.enter_gcode = config.get('enter_gcode', None)
        self.leave_gcode = config.get('leave_gcode', None)

def processMenu(config, item, currentItem):
    thisGroup = None
    section_name = "menu " + item.strip()

    if config.has_section(section_name):
        menuConfig = config.getsection(section_name)
    else:
        raise config.error("Unable to parse menu '%s'" % (section_name))

    # first item (root)
    if currentItem is None:
        currentItem = MenuGroup(menuConfig, None)
        thisGroup = currentItem

    if isinstance(currentItem, MenuGroup):
        if(menuConfig.get('items', None) is not None):
            if thisGroup is None:
                thisGroup = MenuGroup(menuConfig, currentItem)
                currentItem.items.append(thisGroup)
            
            items =  menuConfig.get('items', '').split(',')
            if len(items) > 0:
                thisGroup.items.append(MenuActionBack(thisGroup.name, thisGroup.parent))
                for name in items:
                    processMenu(config, name, thisGroup)

        elif menuConfig.get('input', None) is not None and menuConfig.getfloat('step', 0.) != 0:
            thisInput = MenuInput(menuConfig)
            currentItem.items.append(thisInput)

        else:
            thisItem = MenuItem(menuConfig)
            currentItem.items.append(thisItem)
    return currentItem


class LCDMenu:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.display = self.printer.lookup_object('display')
        self.lcd = self.display.lcd_chip
        self.rows = 4 # should come from display config
        self.cols = 20 # should come from display config
        self.info = {}
        # Load printer objects        
        self.gcode = self.printer.lookup_object('gcode')
        self.toolhead = self.printer.lookup_object('toolhead')
        self.fan = self.printer.lookup_object('fan', None)
        self.extruder0 = self.printer.lookup_object('extruder0', None)
        self.extruder1 = self.printer.lookup_object('extruder1', None)
        self.heater_bed = self.printer.lookup_object('heater_bed', None)

        self.prepare()

    def isRunning(self):
        return self.running

    def updateInfo(self, eventtime):
        self.info = {
            'gcode': self.gcode.get_status(eventtime),
            'toolhead': self.toolhead.get_status(eventtime)
        }
        if self.extruder0 is not None:
            self.info['extruder0'] = self.extruder0.get_status(eventtime)
        
        if self.extruder1 is not None:
            self.info['extruder1'] = self.extruder1.get_status(eventtime)
        
        if self.heater_bed is not None:
            self.info['heater_bed'] = self.heater_bed.get_status(eventtime)

        if self.fan is not None:
            self.info['fan'] = self.fan.get_status(eventtime)

    def prepare(self,  root = None):
        self.firstEntry = True
        self.running = True
        self.curGroup = root
        self.curInput = None
        self.curTopItem = 0
        self.curSelectedItem = 0

    def update(self, eventtime):        

        if not isinstance(self.curGroup, MenuGroup):
	        raise ValueError('Expected resource of type MenuGroup')

        if self.firstEntry is True and self.curGroup.enter_gcode is not None:
            print "enter gcode:" + self.curGroup.enter_gcode
            self.firstEntry = False

        if self.curTopItem > len(self.curGroup.items) - self.rows:
            self.curTopItem = len(self.curGroup.items) - self.rows
        if self.curTopItem < 0:
            self.curTopItem = 0

        y = 0
        for row in range(self.curTopItem, self.curTopItem + self.rows):
            str = ""
            if row < len(self.curGroup.items):
                if row == self.curSelectedItem:
                    if isinstance(self.curGroup.items[row], MenuInput) and isinstance(self.curInput, MenuInput):
                        str += '*'
                    else:
                        str += '>'
                else:
                    str += ' '

                try:
                    if isinstance(self.curGroup.items[row], MenuInput) and isinstance(self.curInput, MenuInput):
                        name = self.curInput.name.format(self.curInput.value)
                    elif isinstance(self.curGroup.items[row], MenuInput):
                        value = self.parseInputFloat(self.curGroup.items[row].input)
                        name = self.curGroup.items[row].name.format(value)
                    else:
                        name = self.curGroup.items[row].name.format(**self.info)
                except:
                    name = '-----'
                finally:
                    str += name[:self.cols-2].ljust(self.cols-2)
                            
                if isinstance(self.curGroup.items[row], MenuActionBack):
                    str += '^'
                elif isinstance(self.curGroup.items[row], MenuGroup):
                    str += '>'
                else:
                    str += ' '

            self.lcd.write(0, y, str.ljust(self.cols))
            y += 1

        #self.lcd.update()

    def up(self):
        if not isinstance(self.curGroup, MenuGroup):
	        raise ValueError('Expected resource of type MenuGroup')

        if isinstance(self.curInput, MenuInput):
            self.curInput.value += abs(self.curInput.step) 
            self.curInput.value = min(self.curInput.max, max(self.curInput.min, self.curInput.value))
        else:
            if self.curSelectedItem == 0:
                return
            elif self.curSelectedItem > self.curTopItem:
                self.curSelectedItem -= 1
            else:
                self.curTopItem -= 1
                self.curSelectedItem -= 1

    def down(self):
        if not isinstance(self.curGroup, MenuGroup):
	        raise ValueError('Expected resource of type MenuGroup')

        if isinstance(self.curInput, MenuInput):
            self.curInput.value -= abs(self.curInput.step) 
            self.curInput.value = min(self.curInput.max, max(self.curInput.min, self.curInput.value))
        else:
            if self.curSelectedItem + 1 == len(self.curGroup.items):
                return
            elif self.curSelectedItem < self.curTopItem + self.rows - 1:
                self.curSelectedItem += 1
            else:
                self.curTopItem += 1
                self.curSelectedItem += 1

    def back(self):
        if not isinstance(self.curGroup, MenuGroup):
	        raise ValueError('Expected resource of type MenuGroup')
        
        if isinstance(self.curInput, MenuInput):
            return

        if isinstance(self.curGroup.parent, MenuGroup):
            # find the current in the parent
            itemno = 0
            index = 0
            for item in self.curGroup.parent.items:
                if self.curGroup == item:
                    index = itemno
                else:
                    itemno += 1

            if self.curGroup.leave_gcode is not None:
                print "leave gcode:" + self.curGroup.leave_gcode

            if index < len(self.curGroup.parent.items):
                self.curGroup = self.curGroup.parent
                self.curTopItem = index
                self.curSelectedItem = index
            else:
                self.curGroup = self.curGroup.parent
                self.curTopItem = 0
                self.curSelectedItem = 0
            
            if self.curGroup.enter_gcode is not None:
                print "enter gcode:" + self.curGroup.enter_gcode
        else:
            if self.curGroup.leave_gcode is not None:
                print "leave gcode:" + self.curGroup.leave_gcode
            self.running = False

    def select(self):
        if not isinstance(self.curGroup, MenuGroup):
	        raise ValueError('Expected resource of type MenuGroup')

        if isinstance(self.curGroup.items[self.curSelectedItem], MenuGroup):
            if self.curGroup.leave_gcode is not None:
                print "leave gcode:" + self.curGroup.leave_gcode
            self.curGroup = self.curGroup.items[self.curSelectedItem]
            self.curTopItem = 0
            self.curSelectedItem = 0
            if self.curGroup.enter_gcode is not None:
                print "enter gcode:" + self.curGroup.enter_gcode

        elif isinstance(self.curGroup.items[self.curSelectedItem], MenuInput):
            if isinstance(self.curInput, MenuInput):
                if self.curInput.gcode is not None:
                    print "gcode:" + self.curInput.gcode.format(self.curInput.value)
                self.curInput.value = 0.
                self.curInput = None                
            else:
                self.curInput = self.curGroup.items[self.curSelectedItem]
                self.curInput.value = self.parseInputFloat(self.curInput.input)

        elif isinstance(self.curGroup.items[self.curSelectedItem], MenuItem):
            item = self.curGroup.items[self.curSelectedItem]
            if item.gcode is not None:
                print "gcode:" + item.gcode

        elif isinstance(self.curGroup.items[self.curSelectedItem], MenuActionBack):
            self.back()

    def parseInputFloat(self, input):
        value = 0.
        try:
            value = float(input)
        except ValueError:
            k1,k2 = input.split('.')[:2]
            if self.info[k1] and self.info[k1][k2]:
                if type(self.info[k1][k2]) != str:
                    value = float( self.info[k1][k2] )
        return value

def load_config(config):
    return LCDMenu(config)