# -*- coding: utf-8 -*-
# Support for display menu (v2.0)
#
# Copyright (C) 2019 Janar Sööt <janar.soot@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import os, logging, re
from string import Template


class error(Exception):
    pass


class sentinel:
    pass


# Experimental
class MenuRenderBuffer(object):
    """Helper class for callback view render buffer"""
    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows
        self.buffer = [" " * self.cols] * self.rows
        self.position = {
            'col': 0,
            'row': 0
        }
        self.dirty = False

    def is_dirty(self):
        return self.dirty

    def set_pos(self, col, row):
        if not (0 <= col < self.cols):
            raise IndexError
        if not (0 <= row < self.rows):
            raise IndexError
        self.position['col'] = col
        self.position['row'] = row

    def get_pos(self):
        return self.position

    def limit_pos(self):
        if self.position['col'] >= self.cols:
            self.position['col'] = 0
            self.position['row'] += 1
        if self.position['row'] >= self.rows:
            self.position['row'] = 0

    def write(self, text, col=None, row=None):
        if col is None:
            col = self.position['col']
        if row is None:
            row = self.position['row']

        if col >= self.cols:
            raise IndexError
        if row >= self.rows:
            raise IndexError

        old_line = self.buffer[row]
        new_line = old_line[:col] + text + old_line[col + len(text):]
        self.buffer[row] = new_line[:self.cols]
        self.position = {
            'col': col + len(text),
            'row': row
        }
        self.dirty = True

    def clear(self):
        self.set_pos(0, 0)
        self.buffer = [" " * self.cols] * self.rows
        self.dirty = False

    def get_buffer(self):
        return list(self.buffer)


class _MenuConfig(dict):
    """Wrapper for dict to emulate configfile get_name for namespace.
        __ns - item namespace key, used in item relative paths
        $__id - generated id text variable
    """
    def get_name(self):
        __id = '__menuitem_' + hex(id(self)).lstrip("0x").rstrip("L")
        return Template('menu ' + self.get(
            '__ns', __id)).safe_substitute(__id=__id)


class MenuItem(object):
    """Menu item abstract class.
    """
    def __init__(self, manager, config):
        if type(self) is MenuItem:
            raise Exception(
                'Abstract MenuItem cannot be instantiated directly')
        self._manager = manager
        self._use_blink = manager.asbool(config.get('use_blink', 'False'))
        self._blink_mask = manager.asint(config.get('blink_mask', '0'))
        self._use_cursor = manager.asbool(config.get('use_cursor', 'True'))
        self.cursor = config.get('cursor', '|')
        self._width = manager.asint(config.get('width', '0'))
        self._scroll = manager.asbool(config.get('scroll', 'False'))
        self._enable_tpl = manager.gcode_macro.load_template(
            config, 'enable', 'True')
        self._name_tpl = manager.gcode_macro.load_template(
            config, 'name')
        self._last_heartbeat = None
        self.__scroll_offs = 0
        self.__scroll_diff = 0
        self.__scroll_dir = None
        self.__last_state = True
        # item namespace - used in item relative paths
        self._ns = " ".join(config.get_name().split()[1:])
        # if scroll is enabled and width is not specified then
        # display width is used and adjusted by cursor size
        if self._scroll and not self._width:
            self._width = self.manager.cols - len(self._cursor)
        # clamp width
        self._width = min(
            self.manager.cols - len(self._cursor), max(0, self._width))
        self.init()

    # override
    def init(self):
        pass

    def _name(self):
        context = self.get_context()
        return self.manager.astext(self.manager.asflatline(
            self._name_tpl.render(context)))

    # override
    def _second_tick(self, eventtime):
        pass

    # override
    def is_editing(self):
        return False

    # override
    def is_scrollable(self):
        return True

    # override
    def is_enabled(self):
        return self.eval_enable()

    # override
    def start_editing(self):
        pass

    # override
    def stop_editing(self):
        pass

    def _action_error(self, name, msg, *args):
        logging.error("'{}' -> {}({}): {}".format(
            self.ns, name, ','.join(map(str, args[0:])), msg))

    # override
    def handle_action(self, name, *args, **kwargs):
        if name == 'emit':
            if len(args[0:]) > 0 and len(str(args[0])) > 0:
                self.manager.send_event(
                    "action:" + str(args[0]), self, *args[1:])
            else:
                self._action_error(name, "malformed action", *args)
        elif name == 'log':
            logging.info("item:{} -> {}".format(
                self.ns, ' '.join(map(str, args[0:]))))

    # override
    def get_context(self, cxt=None):
        # get default menu context
        context = self.manager.get_context(cxt)
        # add default 'me' props
        context.update({
            'me': {
                'is_editing': self.is_editing(),
                'width': self._width,
                'ns': self.ns
            }
        })
        return context

    def eval_enable(self):
        context = self.get_context()
        return self.manager.asbool(self._enable_tpl.render(context))

    # Called when a item is selected
    def select(self):
        self.__clear_scroll()

    def heartbeat(self, eventtime):
        self._last_heartbeat = eventtime
        state = bool(int(eventtime) & 1)
        if self.__last_state ^ state:
            self.__last_state = state
            if not self.is_editing():
                self._second_tick(eventtime)
                self.__update_scroll(eventtime)

    def __clear_scroll(self):
        self.__scroll_dir = None
        self.__scroll_diff = 0
        self.__scroll_offs = 0

    def __update_scroll(self, eventtime):
        if self.__scroll_dir == 0 and self.__scroll_diff > 0:
            self.__scroll_dir = 1
            self.__scroll_offs = 0
        elif self.__scroll_dir and self.__scroll_diff > 0:
            self.__scroll_offs += self.__scroll_dir
            if self.__scroll_offs >= self.__scroll_diff:
                self.__scroll_dir = -1
            elif self.__scroll_offs <= 0:
                self.__scroll_dir = 1
        else:
            self.__clear_scroll()

    def __name_scroll(self, s):
        if self.__scroll_dir is None:
            self.__scroll_dir = 0
            self.__scroll_offs = 0
        return s[
            self.__scroll_offs:self._width + self.__scroll_offs
        ].ljust(self._width)

    def render_name(self, selected=False):
        def _blink(_text, _bstate):
            if (self._use_blink or not self._use_cursor) and _bstate:
                s = ""
                for i in range(0, len(_text)):
                    s += _text[i] if int(self._blink_mask) & (1 << i) else ' '
                return s
            return _text
        s = str(self._name())
        # scroller
        if self._width > 0:
            self.__scroll_diff = len(s) - self._width
            if (selected and self._scroll is True and self.is_scrollable()
                    and self.__scroll_diff > 0):
                s = self.__name_scroll(s)
            else:
                self.__clear_scroll()
                s = s[:self._width].ljust(self._width)
        else:
            self.__clear_scroll()
        # blinker & cursor
        if selected and not self.is_editing():
            s = (self.cursor if self._use_cursor else '') + _blink(
                s, self.manager.blink_slow_state)
        elif selected and self.is_editing():
            s = ('*' if self._use_cursor else '') + _blink(
                s, self.manager.blink_fast_state)
        elif self._use_cursor:
            s = ' ' + s
        return s

    def ns_prefix(self, name):
        name = str(name).strip()
        if name.startswith('.'):
            name = ' '.join([self.ns, name[1:]])
        return name

    def send_event(self, event, *args):
        return self.manager.send_event(
            "item:%s:%s" % (self.ns, str(event)), *args)

    @property
    def cursor(self):
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        self._cursor = str(value)[:1]

    @property
    def manager(self):
        return self._manager

    @property
    def ns(self):
        return self._ns


class MenuContainer(MenuItem):
    """Menu container abstract class.
    """
    def __init__(self, manager, config):
        if type(self) is MenuContainer:
            raise Exception(
                'Abstract MenuContainer cannot be instantiated directly')
        super(MenuContainer, self).__init__(manager, config)
        self.cursor = config.get('cursor', '>')
        self._autorun = manager.asbool(config.get('autorun', 'False'))
        self._allitems = []
        self._names = []
        self._items = []

    def init(self):
        super(MenuContainer, self).init()
        # recursive guard
        self._parents = []

    # overload
    def _names_aslist(self):
        return []

    # overload
    def is_homed(self):
        return True

    # overload
    def is_accepted(self, item):
        return isinstance(item, MenuItem)

    def is_editing(self):
        return any([item.is_editing() for item in self._items])

    def stop_editing(self, run_script=True):
        for item in self._items:
            if item.is_editing():
                item.stop_editing(run_script)

    def lookup_item(self, item):
        if isinstance(item, str):
            name = item.strip()
            ns = self.ns_prefix(name)
            return (self.manager.lookup_menuitem(ns), name)
        elif isinstance(item, MenuItem):
            return (item, item.ns)
        return (None, item)

    # overload
    def _lookup_item(self, item):
        return self.lookup_item(item)

    def _index_of(self, item):
        try:
            index = None
            if isinstance(item, str):
                s = item.strip()
                index = self._names.index(s)
            elif isinstance(item, MenuItem):
                index = self._items.index(item)
            return index
        except ValueError:
            return None

    def index_of(self, item, look_inside=False):
        index = self._index_of(item)
        if index is None and look_inside is True:
            for con in self:
                if isinstance(con, MenuContainer) and con._index_of(item):
                    index = self._index_of(con)
        return index

    def add_parents(self, parents):
        if isinstance(parents, list):
            self._parents.extend(parents)
        else:
            self._parents.append(parents)

    def assert_recursive_relation(self, parents=None):
        assert self not in (parents or self._parents), \
            "Recursive relation of '%s' container" % (self.ns,)

    def insert_item(self, s, index=None):
        self._insert_item(s, index)

    def _insert_item(self, s, index=None):
        item, name = self._lookup_item(s)
        if item is not None:
            if not self.is_accepted(item):
                raise error("Menu item '%s'is not accepted!" % str(type(item)))
            if isinstance(item, (MenuItem)):
                item.init()
            if isinstance(item, (MenuContainer)):
                item.add_parents(self._parents)
                item.add_parents(self)
                item.assert_recursive_relation()
                item.populate_items()
            if index is None:
                self._allitems.append((item, name))
            else:
                self._allitems.insert(index, (item, name))

    # overload
    def _populate_items(self):
        pass

    def populate_items(self):
        self._allitems = []  # empty list
        for name in self._names_aslist():
            self._insert_item(name)
        # populate successor items
        self._populate_items()
        # send populate event
        self.send_event('populate', self)
        self.update_items()

    def update_items(self):
        _a = [(item, name) for item, name in self._allitems
              if item.is_enabled()]
        self._items, self._names = zip(*_a) or ([], [])

    # override
    def render_content(self, eventtime):
        return ("", None)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)

    def __getitem__(self, key):
        return self._items[key]

    @property
    def autorun(self):
        return self._autorun


class MenuSelector(MenuContainer):
    """Menu selector abstract class.
    """
    def __init__(self, manager, config):
        if type(self) is MenuSelector:
            raise Exception(
                'Abstract MenuSelector cannot be instantiated directly')
        super(MenuSelector, self).__init__(manager, config)
        self.__initial = manager.asint(config.get('initial', 0), None)
        self.__selected = None

    # selector methods
    def init_selection(self):
        self.select_at(self.initial)

    def select_at(self, index):
        self.__selected = index
        # select element
        item = self.selected_item()
        if isinstance(item, MenuItem):
            item.select()
        return item

    def select_item(self, needle):
        if isinstance(needle, MenuItem):
            if self.selected_item() is not needle:
                index = self.index_of(needle)
                if index is not None:
                    self.select_at(index)
        else:
            logging.error("Cannot select non menuitem")
        return self.selected

    def selected_item(self):
        if isinstance(self.selected, int) and 0 <= self.selected < len(self):
            return self[self.selected]
        else:
            return None

    def select_next(self):
        if not isinstance(self.selected, int):
            index = 0 if len(self) else None
        elif 0 <= self.selected < len(self) - 1:
            index = self.selected + 1
        else:
            index = self.selected
        return self.select_at(index)

    def select_prev(self):
        if not isinstance(self.selected, int):
            index = 0 if len(self) else None
        elif 0 < self.selected < len(self):
            index = self.selected - 1
        else:
            index = self.selected
        return self.select_at(index)

    def is_homed(self):
        return self.initial == self.selected

    @property
    def initial(self):
        return self.__initial

    @property
    def selected(self):
        return self.__selected


class MenuCommand(MenuItem):
    def __init__(self, manager, config):
        super(MenuCommand, self).__init__(manager, config)
        self._press_script_tpl = manager.gcode_macro.load_template(
            config, 'press_script', '')

    def get_press_script(self, cxt=None):
        context = self.get_context(cxt)
        return self._press_script_tpl.render(context)


class MenuInput(MenuCommand):
    def __init__(self, manager, config,):
        super(MenuInput, self).__init__(manager, config)
        self._reverse = manager.asbool(config.get('reverse', 'false'))
        self._input_tpl = manager.gcode_macro.load_template(config, 'input')
        self._input_min_tpl = manager.gcode_macro.load_template(
            config, 'input_min', '-999999.0')
        self._input_max_tpl = manager.gcode_macro.load_template(
            config, 'input_max', '999999.0')
        self._input_step = config.getfloat('input_step', above=0.)
        self._input_step2 = config.getfloat('input_step2', 0, minval=0.)
        self._input_script_tpl = manager.gcode_macro.load_template(
            config, 'input_script', '')

    def init(self):
        super(MenuInput, self).init()
        self._is_dirty = False
        self.__last_change = None
        self._input_value = None

    def is_scrollable(self):
        return False

    def get_input_script(self, cxt=None):
        context = self.get_context(cxt)
        return self._input_script_tpl.render(context)

    def is_editing(self):
        return self._input_value is not None

    def stop_editing(self):
        if not self.is_editing():
            return
        self._reset_value()

    def start_editing(self):
        if self.is_editing():
            return
        self._init_value()

    def get_value(self):
        return self._input_value

    def heartbeat(self, eventtime):
        super(MenuInput, self).heartbeat(eventtime)
        if (self._is_dirty is True
                and self.__last_change is not None
                and self._input_value is not None
                and (eventtime - self.__last_change) > 0.250):
            self.manager.queue_gcode(self.get_input_script())
            self._is_dirty = False

    def eval_enable(self):
        context = super(MenuInput, self).get_context()
        return self.manager.asbool(self._enable_tpl.render(context))

    def get_context(self, cxt=None):
        context = super(MenuInput, self).get_context(cxt)
        context['me'].update({
            'input': self.manager.asfloat(
                self._eval_value() if self._input_value is None
                else self._input_value)
        })
        return context

    def _eval_min(self):
        context = super(MenuInput, self).get_context()
        return self._input_min_tpl.render(context)

    def _eval_max(self):
        context = super(MenuInput, self).get_context()
        return self._input_max_tpl.render(context)

    def _eval_value(self):
        context = super(MenuInput, self).get_context()
        return self._input_tpl.render(context)

    def _value_changed(self):
        self.__last_change = self._last_heartbeat
        self._is_dirty = True

    def _init_value(self):
        self._input_value = None
        self._input_min = self.manager.asfloat(self._eval_min())
        self._input_max = self.manager.asfloat(self._eval_max())
        value = self._eval_value()
        if self.manager.isfloat(value):
            self._input_value = min(self._input_max, max(
                self._input_min, self.manager.asfloat(value)))
            self._value_changed()
        else:
            logging.error("Cannot init input value")

    def _reset_value(self):
        self._input_value = None

    def inc_value(self, fast_rate=False):
        last_value = self._input_value
        input_step = (self._input_step2 if fast_rate and self._input_step2 > 0
                      else self._input_step)
        if self._input_value is None:
            return

        if(self._reverse is True):
            self._input_value -= abs(input_step)
        else:
            self._input_value += abs(input_step)
        self._input_value = min(self._input_max, max(
            self._input_min, self._input_value))

        if last_value != self._input_value:
            self._value_changed()

    def dec_value(self, fast_rate=False):
        last_value = self._input_value
        input_step = (self._input_step2 if fast_rate and self._input_step2 > 0
                      else self._input_step)
        if self._input_value is None:
            return

        if(self._reverse is True):
            self._input_value += abs(input_step)
        else:
            self._input_value -= abs(input_step)
        self._input_value = min(self._input_max, max(
            self._input_min, self._input_value))

        if last_value != self._input_value:
            self._value_changed()

    # override
    def handle_action(self, name, *args, **kwargs):
        super(MenuInput, self).handle_action(name, *args, **kwargs)
        if name == 'start_editing':
            self.start_editing(*args)
        elif name == 'stop_editing':
            self.stop_editing(*args)


# Experimental
class MenuCallback(MenuContainer):
    def __init__(self, manager, config):
        super(MenuCallback, self).__init__(manager, config)
        self._press_callback = None
        self._back_callback = None
        self._up_callback = None
        self._down_callback = None
        self._render_callback = None
        self._enter_callback = None
        self._leave_callback = None

    # buffer factory
    def create_buffer(self, cols=None, rows=None):
        if cols is None:
            cols = self.manager.cols
        if rows is None:
            rows = self.manager.rows
        return MenuRenderBuffer(cols, rows)

    # register callbacks
    def register_press_callback(self, callback):
        self._press_callback = callback

    def register_back_callback(self, callback):
        self._back_callback = callback

    def register_up_callback(self, callback):
        self._up_callback = callback

    def register_down_callback(self, callback):
        self._down_callback = callback

    # render callback must return tuple of rendered content, active row
    def register_render_callback(self, callback):
        self._render_callback = callback

    def register_enter_callback(self, callback):
        self._enter_callback = callback

    def register_leave_callback(self, callback):
        self._leave_callback = callback

    def render_content(self, eventtime):
        if callable(self._render_callback):
            return self._render_callback(eventtime)
        super(MenuCallback, self).render_content(eventtime)

    # handle callback calls
    def handle_press(self, event):
        if callable(self._press_callback):
            self._press_callback(event)

    def handle_back(self, force=False):
        if callable(self._back_callback):
            self._back_callback(force)

    def handle_up(self, fast_rate=False):
        if callable(self._up_callback):
            self._up_callback(fast_rate)

    def handle_down(self, fast_rate=False):
        if callable(self._down_callback):
            self._down_callback(fast_rate)

    def handle_enter(self):
        if callable(self._enter_callback):
            self._enter_callback()

    def handle_leave(self):
        if callable(self._leave_callback):
            self._leave_callback()


class MenuView(MenuSelector):
    def __init__(self, manager, config):
        super(MenuView, self).__init__(manager, config)
        self._enter_gcode = config.get('enter_gcode', None)
        self._leave_gcode = config.get('leave_gcode', None)
        self._press_script_tpl = manager.gcode_macro.load_template(
            config, 'press_script', '')
        prfx = 'popup_'
        self.popup_menus = {o[len(prfx):]: config.get(o)
                            for o in config.get_prefix_options(prfx)}
        self._popup_menus = {}
        self.runtime_items = config.get('items', '')  # mutable list of items
        self.immutable_items = []  # immutable list of items
        self._runtime_index_start = 0
        self.content = re.sub(
            r"<\?(\w*):\s*([a-zA-Z0-9_. ]+?)\s*\?>", self._preproc_content,
            config.get('content'), 0, re.MULTILINE)
        self._content_tpl = manager.gcode_macro.create_template(
            '%s:content' % (self.ns,), self.content)

    def _placeholder(self, s):
        return "<?name:{}?>".format(s)

    def _preproc_content(self, matched):
        full = matched.group(0)  # The entire match
        m = matched.group(1)
        name = matched.group(2)
        if m == "back":
            item = self.manager.menuitem_from({
                'type': 'command',
                'name': self.manager.asliteral(name),
                'cursor': '>',
                'press_script': '{menu.back()}'
            })
            # add item from content to immutable list of items
            self.immutable_items.append(item)
            return self._placeholder(item.ns)
        elif m == "item":
            # add item from content to immutable list of items
            self.immutable_items.append(name)
            return self._placeholder(name)
        else:
            logging.error(
                "Unknown placeholder {} in {}:content".format(full, self.ns))
            return ""

    def _names_aslist(self):
        return self.immutable_items

    def _lookup_item(self, item):
        if isinstance(item, dict):
            item = self.manager.menuitem_from(item)
        return super(MenuView, self)._lookup_item(item)

    def _populate_extra_items(self):
        # popup menu item
        self._popup_menus = dict()
        for key in self.popup_menus:
            menu = self.manager.lookup_menuitem(self.popup_menus[key])
            if isinstance(menu, MenuContainer):
                menu.assert_recursive_relation(self._parents)
                menu.populate_items()
                self._popup_menus[key] = menu

    def _populate_items(self):
        super(MenuView, self)._populate_items()
        # mark the end of immutable list of items
        # and start of runtime mutable list of items
        self._runtime_index_start = len(self._allitems)
        # populate runtime list of items
        for name in self.manager.lines_aslist(self.runtime_items):
            self._insert_item(name)
        # populate extra menu items
        self._populate_extra_items()

    def insert_item(self, s, index=None):
        # allow runtime items only after immutable list of items
        if index is None:
            super(MenuView, self).insert_item(s)
        else:
            super(MenuView, self).insert_item(self._runtime_index_start+index)

    def get_context(self, cxt=None):
        context = super(MenuView, self).get_context(cxt)
        context['me'].update({
            'popup_names': self._popup_menus.keys()
        })
        return context

    def render_content(self, eventtime):
        content = ""
        rows = []
        selected_row = None
        try:
            context = self.get_context()
            context['me'].update({
                'runtime_items': [
                    self._placeholder(n) for i, n in self._allitems[
                        self._runtime_index_start:] if i.is_enabled()
                ]
            })
            content = self._content_tpl.render(context)
            # postprocess content
            for line in self.manager.lines_aslist(content):
                s = ""
                for i, text in enumerate(re.split(
                        r"<\?name:\s*([a-zA-Z0-9_. ]+?)\s*\?>", line)):
                    if i & 1 == 0:
                        s += text
                    else:
                        idx = self.index_of(text)
                        if idx is not None:
                            current = self[idx]
                            selected = (idx == self.selected)
                            if selected:
                                current.heartbeat(eventtime)
                                selected_row = len(rows)
                            s += str(current.render_name(selected))
                if s.strip():
                    rows.append(s)
                    # logging.info("{}".format(s))
        except Exception:
            logging.exception('View rendering error')
        return ("\n".join(rows), selected_row)

    def run_enter_gcode(self):
        self.manager.queue_gcode(self._enter_gcode)

    def run_leave_gcode(self):
        self.manager.queue_gcode(self._leave_gcode)

    def get_press_script(self, cxt=None):
        context = self.get_context(cxt)
        return self._press_script_tpl.render(context)

    # override
    def handle_action(self, name, *args, **kwargs):
        super(MenuView, self).handle_action(name, *args, **kwargs)
        if name == 'popup':
            if len(args[0:]) == 1:
                key = str(args[0])
                if key in self._popup_menus:
                    self.manager.push_container(self._popup_menus[key])
                else:
                    self._action_error(
                        name, "menu '{}' not found".format(key), *args)
            else:
                self._action_error(name, "takes exactly one argument", *args)


class MenuVSDView(MenuView):
    def __init__(self, manager, config):
        super(MenuVSDView, self).__init__(manager, config)

    def _populate_items(self):
        super(MenuVSDView, self)._populate_items()
        sdcard = self.manager.objs.get('virtual_sdcard')
        if sdcard is not None:
            files = sdcard.get_file_list()
            for fname, fsize in files:
                gcode = [
                    'M23 /%s' % str(fname)
                ]
                self.insert_item(self.manager.menuitem_from({
                    'type': 'command',
                    'name': self.manager.asliteral(fname),
                    'cursor': '+',
                    'press_script': "\n".join(gcode),
                    'scroll': True
                }))


menu_items = {
    'command': MenuCommand,
    'input': MenuInput,
    'callback': MenuCallback,
    'view': MenuView,
    'vsdview': MenuVSDView
}

MENU_UPDATE_DELAY = .100
TIMER_DELAY = .100
LONG_PRESS_DURATION = 0.800
DBL_PRESS_DURATION = 0.300
#  Blinking sequence per 0.100 ->  1 - on, 0 - off
BLINK_FAST_SEQUENCE = (1, 1, 1, 1, 0, 0, 0, 0)
BLINK_SLOW_SEQUENCE = (1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 0, 0, 0)


class MenuManager:
    def __init__(self, config, display):
        self.running = False
        self.menuitems = {}
        self.menustack = []
        self._autorun = False
        self.top_row = 0
        self.blink_fast_state = True
        self.blink_slow_state = True
        self._last_eventtime = 0
        self.blink_fast_idx = 0
        self.blink_slow_idx = 0
        self.timeout_idx = 0
        self.display = display
        self.lcd_chip = display.get_lcd_chip()
        self.printer = config.get_printer()
        self.pconfig = self.printer.lookup_object('configfile')
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode_queue = []
        self.context = {}
        self.objs = {}
        self.root = None
        self.root_names = config.get('menu_root', '__main')
        self.cols, self.rows = self.lcd_chip.get_dimensions()
        self.timeout = config.getint('menu_timeout', 0)
        self.timer = 0
        # queue for action calls
        self._action_queue = []
        self._action_params = {}
        # buttons
        self.encoder_pins = config.get('encoder_pins', None)
        self.click_pin = config.get('click_pin', None)
        self.back_pin = config.get('back_pin', None)
        self.up_pin = config.get('up_pin', None)
        self.down_pin = config.get('down_pin', None)
        self.kill_pin = config.get('kill_pin', None)
        # analog button ranges
        self.analog_range_click_pin = config.get(
            'analog_range_click_pin', None)
        self.analog_range_back_pin = config.get(
            'analog_range_back_pin', None)
        self.analog_range_up_pin = config.get(
            'analog_range_up_pin', None)
        self.analog_range_down_pin = config.get(
            'analog_range_down_pin', None)
        self.analog_range_kill_pin = config.get(
            'analog_range_kill_pin', None)
        self._last_click_press = 0
        self._click_counter = 0
        self.analog_pullup = config.getfloat(
            'analog_pullup_resistor', 4700., above=0.)
        self._encoder_fast_rate = config.getfloat(
            'encoder_fast_rate', .03, above=0.)
        self._last_encoder_cw_eventtime = 0
        self._last_encoder_ccw_eventtime = 0
        # printer objects
        self.buttons = self.printer.try_load_module(config, "buttons")
        self.gcode_macro = self.printer.try_load_module(config, 'gcode_macro')
        # register itself for printer callbacks
        self.printer.add_object('menu', self)
        self.printer.register_event_handler("klippy:ready", self.handle_ready)
        # register buttons & encoder
        if self.buttons:
            # digital buttons
            if self.encoder_pins:
                try:
                    pin1, pin2 = self.encoder_pins.split(',')
                except Exception:
                    raise config.error("Unable to parse encoder_pins")
                self.buttons.register_rotary_encoder(
                    pin1.strip(), pin2.strip(),
                    self.encoder_cw_callback, self.encoder_ccw_callback)
            if self.click_pin:
                if self.analog_range_click_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_click_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_click_pin")
                    self.buttons.register_adc_button(
                        self.click_pin, p_min, p_max, self.analog_pullup,
                        self.click_callback)
                else:
                    self.buttons.register_buttons(
                        [self.click_pin], self.click_callback)
            if self.back_pin:
                if self.analog_range_back_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_back_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_back_pin")
                    self.buttons.register_adc_button_push(
                        self.back_pin, p_min, p_max, self.analog_pullup,
                        self.back_callback)
                else:
                    self.buttons.register_button_push(
                        self.back_pin, self.back_callback)
            if self.up_pin:
                if self.analog_range_up_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_up_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_up_pin")
                    self.buttons.register_adc_button_push(
                        self.up_pin, p_min, p_max, self.analog_pullup,
                        self.up_callback)
                else:
                    self.buttons.register_button_push(
                        self.up_pin, self.up_callback)
            if self.down_pin:
                if self.analog_range_down_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_down_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_down_pin")
                    self.buttons.register_adc_button_push(
                        self.down_pin, p_min, p_max, self.analog_pullup,
                        self.down_callback)
                else:
                    self.buttons.register_button_push(
                        self.down_pin, self.down_callback)
            if self.kill_pin:
                if self.analog_range_kill_pin is not None:
                    try:
                        p_min, p_max = map(
                            float, self.analog_range_kill_pin.split(','))
                    except Exception:
                        raise config.error(
                            "Unable to parse analog_range_kill_pin")
                    self.buttons.register_adc_button_push(
                        self.kill_pin, p_min, p_max, self.analog_pullup,
                        self.kill_callback)
                else:
                    self.buttons.register_button_push(
                        self.kill_pin, self.kill_callback)

        # Load local config file in same directory as current module
        self.load_config(os.path.dirname(__file__), 'menu.cfg')
        # Load items from main config
        self.load_menuitems(config)
        # Load menu root
        self.load_root()
        # send init event
        self.send_event('init', self)

    def handle_ready(self):
        # start timer
        reactor = self.printer.get_reactor()
        reactor.register_timer(self.timer_event, reactor.NOW)

    def timer_event(self, eventtime):
        self._last_eventtime = eventtime
        # take next from sequence
        self.blink_fast_idx = (
            (self.blink_fast_idx + 1) % len(BLINK_FAST_SEQUENCE)
        )
        self.blink_slow_idx = (
            (self.blink_slow_idx + 1) % len(BLINK_SLOW_SEQUENCE)
        )
        self.timeout_idx = (self.timeout_idx + 1) % 10  # 0.1*10 = 1s
        self.blink_fast_state = (
            not not BLINK_FAST_SEQUENCE[self.blink_fast_idx]
        )
        self.blink_slow_state = (
            not not BLINK_SLOW_SEQUENCE[self.blink_slow_idx]
        )
        if self.timeout_idx == 0:
            self.timeout_check(eventtime)
        # check press
        if self._last_click_press > 0:
            diff = eventtime - self._last_click_press
            if self._click_counter > 1:
                # dbl click
                self._last_click_press = 0
                self._click_counter = 0
                self._click_callback(eventtime, 'double')
            elif self._click_counter == 0 and diff >= LONG_PRESS_DURATION:
                # long click
                self._last_click_press = 0
                self._click_counter = 0
                self._click_callback(eventtime, 'long')
            elif self._click_counter == 1 and diff >= DBL_PRESS_DURATION:
                # short click
                self._last_click_press = 0
                self._click_counter = 0
                self._click_callback(eventtime, 'short')
        return eventtime + TIMER_DELAY

    def timeout_check(self, eventtime):
        permit_check = False
        if (self.is_running()and self.timeout > 0
                and isinstance(self.root, MenuContainer)):
            container = self.stack_peek()
            if container is self.root:
                if not container.is_homed():
                    permit_check = True
                elif not self._autorun:
                    permit_check = True
            else:
                permit_check = True

        # check timeout
        if permit_check is True:
            if self.timer >= self.timeout:
                self.exit()
            else:
                self.timer += 1
        else:
            self.timer = 0

    def restart(self, root=None, force_exit=True):
        if self.is_running():
            self.exit(force_exit)
        self.load_root(root, True)

    def load_root(self, root=None, autorun=None):
        self.root = None
        if root is None:
            # find first enabled root from list
            for name in self.lines_aslist(self.root_names):
                item = self.lookup_menuitem(name)
                if item.is_enabled():
                    self.root = item
                    break
            if self.root is None:
                logging.error("No active root item found!")
        else:
            self.root = self.lookup_menuitem(root)

        if autorun is None and isinstance(self.root, MenuContainer):
            self._autorun = self.root.autorun
        else:
            self._autorun = not not autorun

    def register_object(self, obj, name=None, override=False):
        """Register an object with a "get_status" callback"""
        if obj is not None:
            if name is None:
                name = obj.__class__.__name__
            if override or name not in self.objs:
                self.objs[name] = obj

    def unregister_object(self, name):
        """Unregister an object from "get_status" callback list"""
        if name is not None:
            if not isinstance(name, str):
                name = name.__class__.__name__
            if name in self.objs:
                self.objs.pop(name)

    def after(self, starttime, callback, *args):
        """Helper method for reactor.register_callback.
        The callback will be executed once after the start time elapses.
        Starttime values less than 3600 are considered as timeout/delay seconds
        from current reactor time."""
        def callit(eventtime):
            callback(eventtime, *args)
        reactor = self.printer.get_reactor()
        starttime = max(0., float(starttime))
        if starttime < 3600.0:  # 1h
            starttime = reactor.monotonic() + starttime
        reactor.register_callback(callit, starttime)

    def send_event(self, event, *args):
        return self.printer.send_event("menu:" + str(event), *args)

    def is_running(self):
        return self.running

    def begin(self, eventtime):
        self.menustack = []
        self.top_row = 0
        self.timer = 0
        if isinstance(self.root, MenuContainer):
            # send begin event
            self.send_event('begin', self)
            self.update_context(eventtime)
            if isinstance(self.root, MenuSelector):
                self.root.init_selection()
            self.root.populate_items()
            self.stack_push(self.root)
            self.running = True
            return
        elif self.root is not None:
            logging.error("Invalid root, menu stopped!")
        self.running = False

    def get_status(self, eventtime):
        return {
            'eventtime': eventtime,
            'timeout': self.timeout,
            'autorun': self._autorun,
            'running': self.running,
            'blink_fast': self.blink_fast_state,
            'blink_slow': self.blink_slow_state,
            'rows': self.rows,
            'cols': self.cols
        }

    def get_context(self, cxt=None):
        context = dict(self.context)
        if isinstance(cxt, dict):
            context.update(cxt)
        return context

    def update_context(self, eventtime):
        # iterate menu objects
        objs = dict(self.objs)
        parameter = {}
        for name in objs.keys():
            try:
                if objs[name] is not None:
                    get_status = getattr(objs[name], "get_status", None)
                    if callable(get_status):
                        parameter[name] = get_status(eventtime)
                    else:
                        parameter[name] = {}
            except Exception:
                logging.exception("Parameter '%s' update error" % str(name))
        # menu default jinja2 context
        _tpl = self.gcode_macro.create_template("update_context", "")
        self.context = {
            'printer': _tpl.create_status_wrapper(eventtime),
            'menu_objects': parameter
        }

    def stack_push(self, container):
        if not isinstance(container, MenuContainer):
            raise error("Wrong type, expected MenuContainer")
        top = self.stack_peek()
        if top is not None:
            if isinstance(top, MenuView):
                top.run_leave_gcode()
            elif isinstance(top, MenuCallback):
                top.handle_leave()
        if isinstance(container, MenuView):
            container.run_enter_gcode()
        elif isinstance(container, MenuCallback):
            container.handle_enter()
        if not container.is_editing():
            container.update_items()
            if isinstance(container, MenuSelector):
                container.init_selection()
        self.menustack.append(container)

    def stack_pop(self):
        container = None
        if self.stack_size() > 0:
            container = self.menustack.pop()
            if not isinstance(container, MenuContainer):
                raise error("Wrong type, expected MenuContainer")
            top = self.stack_peek()
            if top is not None:
                if not isinstance(container, MenuContainer):
                    raise error("Wrong type, expected MenuContainer")
                if not top.is_editing():
                    top.update_items()
                    if isinstance(top, MenuSelector):
                        top.init_selection()
                if isinstance(container, MenuView):
                    container.run_leave_gcode()
                elif isinstance(container, MenuCallback):
                    container.handle_leave()
                if isinstance(top, MenuView):
                    top.run_enter_gcode()
                elif isinstance(top, MenuCallback):
                    top.handle_enter()
            else:
                if isinstance(container, MenuView):
                    container.run_leave_gcode()
                elif isinstance(container, MenuCallback):
                    container.handle_leave()
        return container

    def stack_size(self):
        return len(self.menustack)

    def stack_peek(self, lvl=0):
        container = None
        if self.stack_size() > lvl:
            container = self.menustack[self.stack_size() - lvl - 1]
        return container

    def render(self, eventtime):
        lines = []
        self.update_context(eventtime)
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            container.heartbeat(eventtime)
            content, viewport_row = container.render_content(eventtime)
            if viewport_row is not None:
                while viewport_row >= (self.top_row + self.rows):
                    self.top_row += 1
                while viewport_row < self.top_row and self.top_row > 0:
                    self.top_row -= 1
            else:
                self.top_row = 0
            for row, text in enumerate(
                    self.aslatin(content).splitlines()):
                if self.top_row <= row < self.top_row + self.rows:
                    text = self.astext(text)
                    lines.append(text.ljust(self.cols))
        return lines

    def screen_update_event(self, eventtime):
        if self.is_running():
            self.lcd_chip.clear()
            for y, line in enumerate(self.render(eventtime)):
                self.display.draw_text(0, y, line)
            self.lcd_chip.flush()
            return eventtime + MENU_UPDATE_DELAY
        elif not self.is_running() and self._autorun is True:
            # lets start and populate the menu items
            self.begin(eventtime)
            return eventtime + MENU_UPDATE_DELAY
        else:
            return 0

    def up(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuInput) and current.is_editing():
                    current.dec_value(fast_rate)
                else:
                    container.select_prev()
            elif isinstance(container, MenuCallback):
                container.handle_up(fast_rate)

    def down(self, fast_rate=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuInput) and current.is_editing():
                    current.inc_value(fast_rate)
                else:
                    container.select_next()
            elif isinstance(container, MenuCallback):
                container.handle_down(fast_rate)

    def back(self, force=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuInput) and current.is_editing():
                    if force is True:
                        current.stop_editing()
                    else:
                        return
            elif isinstance(container, MenuCallback):
                if container.handle_back(force) is True:
                    return
            parent = self.stack_peek(1)
            if isinstance(parent, MenuContainer):
                self.stack_pop()
                if isinstance(parent, MenuSelector):
                    index = parent.index_of(container, True)
                    parent.select_at(index)
            else:
                self.stack_pop()
                self.running = False

    def exit(self, force=False):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if (not force and isinstance(current, MenuInput)
                        and current.is_editing()):
                    return
            if isinstance(container, MenuView):
                container.run_leave_gcode()
            elif isinstance(container, MenuCallback):
                container.handle_leave()
            self.send_event('exit', self)
            self.running = False

    def handle_action(self, name, *args, **kwargs):
        if name == 'back':
            self.back(*args)
        elif name == 'exit':
            self.exit(*args)
        elif name == 'reset':
            # reset container selection
            container = self.stack_peek()
            if self.running:
                if isinstance(container, MenuContainer):
                    container.stop_editing()
                if isinstance(container, MenuSelector):
                    container.init_selection()

    def push_container(self, menu):
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            if (isinstance(menu, MenuContainer)
                    and not container.is_editing()
                    and menu is not container):
                self.stack_push(menu)
                return True
        return False

    def press(self, event='short'):
        # action context
        context = {'menu': self._get_action_context(press_event=event)}
        container = self.stack_peek()
        if self.running and isinstance(container, MenuContainer):
            self.timer = 0
            if isinstance(container, MenuSelector):
                current = container.selected_item()
                if isinstance(current, MenuContainer):
                    self.stack_push(current)
                elif isinstance(current, (MenuInput, MenuCommand)):
                    gcode = current.get_press_script(context)
                    self.queue_gcode(gcode)
                    if isinstance(current, MenuInput):
                        if not self._from_action_context('manual'):
                            if not current.is_editing() and event == 'short':
                                current.start_editing()
                            elif current.is_editing() and event == 'short':
                                current.stop_editing()
                        else:
                            self._handle_actions(
                                current, 'start_editing, stop_editing')
                # process general item actions
                if isinstance(current, MenuItem):
                    self._handle_actions(current, 'emit, log')
                else:  # current is None, no selection. pass click to container
                    if isinstance(container, MenuView):
                        gcode = container.get_press_script(context)
                        self.queue_gcode(gcode)
                # process container actions
                self._handle_actions(container, 'popup')
                # process manager actions
                self._handle_actions(self, 'back, exit, reset')
                # find leftovers
                for name, args in self._actions_iter_pop('*'):
                    logging.error("Unknown action: {}({})".format(
                        name, ','.join(map(str, args[0:]))))
            elif isinstance(container, MenuCallback):
                container.handle_press(event)

    def queue_gcode(self, script):
        if not script:
            return
        if not self.gcode_queue:
            reactor = self.printer.get_reactor()
            reactor.register_callback(self.dispatch_gcode)
        self.gcode_queue.append(script)

    def dispatch_gcode(self, eventtime):
        while self.gcode_queue:
            script = self.gcode_queue[0]
            try:
                self.gcode.run_script(script)
            except Exception:
                logging.exception("Script running error")
            self.gcode_queue.pop(0)

    def menuitem_from(self, config):
        if isinstance(config, dict):
            config = _MenuConfig(dict(config))
        return self.aschoice(
            config, 'type', menu_items)(self, config)

    def add_menuitem(self, name, menu):
        if name in self.menuitems:
            logging.info(
                "Declaration of '%s' hides "
                "previous menuitem declaration" % (name,))
        self.menuitems[name] = menu

    def lookup_menuitem(self, name, default=sentinel):
        if name is None:
            return None
        if name in self.menuitems:
            return self.menuitems[name]
        if default is sentinel:
            raise self.printer.config_error(
                "Unknown menuitem '%s'" % (name,))
        return default

    def lookup_menuitems(self, prefix=None):
        if prefix is None:
            return list(self.menuitems.items())
        items = [(n, self.menuitems[n])
                 for n in self.menuitems if n.startswith(prefix + ' ')]
        if prefix in self.menuitems:
            return [(prefix, self.menuitems[prefix])] + items
        return items

    def load_config(self, *args):
        cfg = None
        filename = os.path.join(*args)
        try:
            cfg = self.pconfig.read_config(filename)
        except Exception:
            raise self.printer.config_error(
                "Cannot load config '%s'" % (filename,))
        if cfg:
            self.load_menuitems(cfg)
        return cfg

    def load_menuitems(self, config):
        for cfg in config.get_prefix_sections('menu '):
            item = self.menuitem_from(cfg)
            self.add_menuitem(item.ns, item)

    # buttons & encoder callbacks
    def encoder_cw_callback(self, eventtime):
        fast_rate = ((eventtime - self._last_encoder_cw_eventtime)
                     <= self._encoder_fast_rate)
        self._last_encoder_cw_eventtime = eventtime
        self.up(fast_rate)

    def encoder_ccw_callback(self, eventtime):
        fast_rate = ((eventtime - self._last_encoder_ccw_eventtime)
                     <= self._encoder_fast_rate)
        self._last_encoder_ccw_eventtime = eventtime
        self.down(fast_rate)

    def click_callback(self, eventtime, state):
        if self.click_pin:
            if state:
                self._last_click_press = eventtime
            elif self._last_click_press > 0:
                diff = eventtime - self._last_click_press
                if diff < DBL_PRESS_DURATION:
                    self._click_counter += 1
                else:
                    self._click_counter = 1

    def _click_callback(self, eventtime, event):
        if self.is_running():
            self.press(event)
        else:
            # lets start and populate the menu items
            self.begin(eventtime)

    def back_callback(self, eventtime):
        if self.back_pin:
            self.back()

    def up_callback(self, eventtime):
        if self.up_pin:
            self.up()

    def down_callback(self, eventtime):
        if self.down_pin:
            self.down()

    def kill_callback(self, eventtime):
        if self.kill_pin:
            # Emergency Stop
            self.printer.invoke_shutdown("Shutdown due to kill button!")

    # action context methods
    def _handle_actions(self, item, n, **kwargs):
        _handle = getattr(item, "handle_action", None)
        if callable(_handle):
            for name, args in self._actions_iter_pop(n):
                _handle(name, *args, **kwargs)

    def _from_action_context(self, name):
        if name in self._action_params:
            return self._action_params[name]
        else:
            return None

    def _get_action_context(self, **kwargs):
        self._action_queue = []
        self._action_params = {}

        # wrapper for action context, encapsulate __getattr__
        class __ActionContext__(object):
            def __getattr__(me, name):
                def _set(key, val):
                    self._action_params[key] = val
                    return ''

                def _append(*args):
                    self._action_queue.append(
                        (len(self._action_queue), name, list(args)))
                    return ''

                if name in kwargs:
                    return kwargs[name]
                elif name == "set_param":
                    return _set
                else:
                    return _append
        return __ActionContext__()

    def _actions_iter_pop(self, n):
        names = self.words_aslist(n)
        # find matching actions
        if len(names) == 1 and names[0] == '*':
            matches = [t for t in self._action_queue]
        else:
            matches = [t for t in self._action_queue if t[1] in names]
        for match in matches:
            i, name, args = match
            # remove found match from action list
            self._action_queue.remove(match)
            # yield found action
            yield (name, args)
        else:
            raise StopIteration

    # manager helper methods
    @classmethod
    def astext(cls, s):
        """Literals are beginning or ending by the back-tick '`' (grave accent)
        character instead of double or single quotes. To escape a back-tick use
        a double back-tick."""
        s = str(s)
        if s.startswith('``') or s.startswith('`'):
            s = s[1:]
        if s.endswith('``') or s.endswith('`'):
            s = s[:-1]
        return s

    @classmethod
    def asliteral(cls, s):
        """Enclose text by the back-tick"""
        return '`' + str(s) + '`'

    @classmethod
    def aslatin(cls, s):
        if isinstance(s, str):
            return s
        elif isinstance(s, unicode):
            return unicode(s).encode('latin-1', 'ignore')
        else:
            return str(s)

    @classmethod
    def asflatline(cls, s):
        return ''.join(cls.aslatin(s).splitlines())

    @classmethod
    def asbool(cls, s):
        if isinstance(s, (bool, int, float)):
            return bool(s)
        elif cls.isfloat(s):
            return bool(cls.asfloat(s))
        s = str(s).strip()
        return s.lower() in ('y', 'yes', 't', 'true', 'on', '1')

    @classmethod
    def asint(cls, s, default=sentinel):
        if isinstance(s, (int, float)):
            return int(s)
        s = str(s).strip()
        prefix = s[0:2]
        try:
            if prefix == '0x':
                return int(s, 16)
            elif prefix == '0b':
                return int(s, 2)
            else:
                return int(float(s))
        except ValueError as e:
            if default is not sentinel:
                return default
            raise e

    @classmethod
    def asfloat(cls, s, default=sentinel):
        if isinstance(s, (int, float)):
            return float(s)
        s = str(s).strip()
        try:
            return float(s)
        except ValueError as e:
            if default is not sentinel:
                return default
            raise e

    @classmethod
    def isfloat(cls, value):
        try:
            float(value)
            return True
        except ValueError:
            return False

    @classmethod
    def lines_aslist(cls, value, default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.splitlines()])
        try:
            return list(value)
        except Exception:
            logging.exception("Lines as list parsing error")
            return list(default)

    @classmethod
    def words_aslist(cls, value, sep=',', default=[]):
        if isinstance(value, str):
            value = filter(None, [x.strip() for x in value.split(sep)])
        try:
            return list(value)
        except Exception:
            logging.exception("Words as list parsing error")
            return list(default)

    @classmethod
    def aslist(cls, value, flatten=True, default=[]):
        values = cls.lines_aslist(value)
        if not flatten:
            return values
        result = []
        for value in values:
            subvalues = cls.words_aslist(value, sep=',')
            result.extend(subvalues)
        return result

    @classmethod
    def aschoice(cls, config, option, choices, default=sentinel):
        if default is not sentinel:
            c = config.get(option, default)
        else:
            c = config.get(option)
        if c not in choices:
            raise error("Choice '%s' for option '%s'"
                        " is not a valid choice" % (c, option))
        return choices[c]
