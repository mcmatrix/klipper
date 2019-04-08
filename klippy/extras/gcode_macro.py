# Add ability to define custom g-code macros
#
# Copyright (C) 2018-2019  Kevin O'Connor <kevin@koconnor.net>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import traceback, logging
import jinja2


######################################################################
# Template handling
######################################################################

# Wrapper for "status" access to printer object get_status() methods
class StatusWrapper:
    def __init__(self, printer, eventtime=None):
        self.printer = printer
        self.eventtime = eventtime
        self.cache = {}
    def __getitem__(self, val):
        sval = str(val).strip()
        if sval in self.cache:
            return self.cache[sval]
        po = self.printer.lookup_object(sval, None)
        if po is None or not hasattr(po, 'get_status'):
            raise KeyError(val)
        if self.eventtime is None:
            self.eventtime = self.printer.get_reactor().monotonic()
        self.cache[sval] = res = dict(po.get_status(self.eventtime))
        return res


# Wrapper around a Jinja2 environment
class EnvironmentWrapper(object):
    def __init__(self, printer, env, name):
        self.printer = printer
        self.name = name
        self.gcode = self.printer.lookup_object('gcode')

    def create_status_wrapper(self, eventtime=None):
        return StatusWrapper(self.printer, eventtime)


# Wrapper around a Jinja2 template
class TemplateWrapper(EnvironmentWrapper):
    def __init__(self, printer, env, name, script):
        super(TemplateWrapper, self).__init__(printer, env, name)
        try:
            self.template = env.from_string(script)
        except Exception as e:
            msg = "Error loading template '%s': %s" % (
                name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise printer.config_error(msg)
    def render(self, context=None):
        if context is None:
            context = {'status': self.create_status_wrapper()}
        try:
            return str(self.template.render(context))
        except Exception as e:
            msg = "Error evaluating '%s': %s" % (
                self.name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise self.gcode.error(msg)
    def run_gcode_from_command(self, context=None):
        self.gcode.run_script_from_command(self.render(context))


# Wrapper around a Jinja2 expression
class ExpressionWrapper(EnvironmentWrapper):
    def __init__(self, printer, env, name, script):
        super(ExpressionWrapper, self).__init__(printer, env, name)
        try:
            self.expression = env.compile_expression(script)
        except Exception as e:
            msg = "Error loading expression '%s': %s" % (
                name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise printer.config_error(msg)

    def run(self, context=None):
        if context is None:
            context = {'status': self.create_status_wrapper()}
        try:
            return self.expression(context)
        except Exception as e:
            msg = "Error evaluating '%s': %s" % (
                self.name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise self.gcode.error(msg)


# Main gcode macro template tracking
class PrinterGCodeMacro:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.env = jinja2.Environment('{%', '%}', '{', '}')
    def load_template(self, config, option):
        name = "%s:%s" % (config.get_name(), option)
        script = config.get(option, '')
        return TemplateWrapper(self.printer, self.env, name, script)
    def load_expression(self, config, option):
        name = "%s:%s" % (config.get_name(), option)
        script = config.get(option, '')
        return ExpressionWrapper(self.printer, self.env, name, script)

def load_config(config):
    return PrinterGCodeMacro(config)


######################################################################
# GCode macro
######################################################################

class GCodeMacro:
    def __init__(self, config):
        self.alias = config.get_name().split()[1].upper()
        printer = config.get_printer()
        config.get('gcode')
        gcode_macro = printer.try_load_module(config, 'gcode_macro')
        self.template = gcode_macro.load_template(config, 'gcode')
        self.gcode = printer.lookup_object('gcode')
        self.gcode.register_command(self.alias, self.cmd, desc=self.cmd_desc)
        self.in_script = False
        prefix = 'default_parameter_'
        self.kwparams = { o[len(prefix):].upper(): config.get(o)
                          for o in config.get_prefix_options(prefix) }
    cmd_desc = "G-Code macro"
    def cmd(self, params):
        if self.in_script:
            raise self.gcode.error(
                "Macro %s called recursively" % (self.alias,))
        kwparams = dict(self.kwparams)
        kwparams.update(params)
        kwparams['status'] = self.template.create_status_wrapper()
        kwparams['params'] = params
        self.in_script = True
        try:
            self.template.run_gcode_from_command(kwparams)
        finally:
            self.in_script = False

def load_config_prefix(config):
    return GCodeMacro(config)
