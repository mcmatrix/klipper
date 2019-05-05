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

# static class for helper functions
class Jinja2Helper:
    @staticmethod
    def interpolate(value, from_min, from_max, to_min, to_max):
        """Linear Interpolation, re-maps a number from one range to another"""
        from_span = from_max - from_min
        to_span = to_max - to_min
        scale_factor = float(to_span) / float(from_span)
        return to_min + (value - from_min) * scale_factor

    @staticmethod
    def seconds2(key):
        """Convert seconds to minutes, hours, days"""
        time = {}

        def time_fn(value):
            try:
                seconds = int(abs(value))
            except Exception:
                logging.exception("Seconds parsing error")
                seconds = 0
            time['days'], time['seconds'] = divmod(seconds, 86400)
            time['hours'], time['seconds'] = divmod(time['seconds'], 3600)
            time['minutes'], time['seconds'] = divmod(time['seconds'], 60)
            if key in time:
                return time[key]
            else:
                return 0
        return time_fn


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

    def __contains__(self, val):
        sval = str(val).strip()
        if sval not in self.cache:
            po = self.printer.lookup_object(sval, None)
            if po is None or not hasattr(po, 'get_status'):
                return False
        return True

    def __iter__(self):
        return iter(self.printer.lookup_objects())



# Wrapper around a Jinja2 environment
class EnvironmentWrapper(object):
    def __init__(self, printer, env, name, script):
        self.printer = printer
        self.name = name
        self.script = script
        self.env = env
        self.gcode = self.printer.lookup_object('gcode')

    def create_status_wrapper(self, eventtime=None):
        return StatusWrapper(self.printer, eventtime)

    def create_default_context(self, ctx=None, eventtime=None):
        context = {
            'status': self.create_status_wrapper(),
            'lerp': Jinja2Helper.interpolate,
            's2days': Jinja2Helper.seconds2('days'),
            's2hours': Jinja2Helper.seconds2('hours'),
            's2mins': Jinja2Helper.seconds2('minutes'),
            's2secs': Jinja2Helper.seconds2('seconds'),
            'bool': bool,
            'info': logging.info
        }
        if isinstance(ctx, dict):
            context.update(ctx)
        return context

    def extract_functions(self):
        """Extract function names and its arguments (only constants)
           from the given template."""
        try:
            ast = self.env.parse(self.script)
        except Exception as e:
            msg = "Error parsing template '%s': %s" % (
                self.name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise self.gcode.error(msg)

        for node in ast.find_all(jinja2.nodes.Call):
            if not isinstance(node.node, jinja2.nodes.Name):
                continue
            args = []
            for arg in node.args:
                if isinstance(arg, jinja2.nodes.Const):
                    args.append(arg.value)
                else:
                    args.append(None)
            for arg in node.kwargs:
                args.append(None)
            if node.dyn_args is not None:
                args.append(None)
            if node.dyn_kwargs is not None:
                args.append(None)
            args = tuple(x for x in args if x is not None)
            yield node.node.name, args


# Wrapper around a Jinja2 template
class TemplateWrapper(EnvironmentWrapper):
    def __init__(self, printer, env, name, script):
        super(TemplateWrapper, self).__init__(printer, env, name, script)
        try:
            self.template = env.from_string(script)
        except Exception as e:
            msg = "Error loading template '%s': %s" % (
                name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise printer.config_error(msg)

    def render(self, context=None):
        context = self.create_default_context(context)
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
        super(ExpressionWrapper, self).__init__(printer, env, name, script)
        try:
            self.expression = env.compile_expression(script)
        except Exception as e:
            msg = "Error loading expression '%s': %s" % (
                name, traceback.format_exception_only(type(e), e)[-1])
            logging.exception(msg)
            raise printer.config_error(msg)

    def evaluate(self, context=None):
        context = self.create_default_context(context)
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
        self.env = jinja2.Environment(
            '{%', '%}', '{', '}', line_statement_prefix='%%')

    def _strip_enclosed_quotes(self, value):
        if isinstance(value, str):
            value = value.strip()
            if ((value.startswith('"') and value.endswith('"')) or
                    (value.startswith("'") and value.endswith("'"))):
                value = value[1:-1]
        return value

    def load_template(self, config, option, default='', enclosed_quotes=False):
        if isinstance(config, dict):
            name = "<dict>:%s" % (option,)
        else:
            name = "%s:%s" % (config.get_name(), option)
        script = config.get(option, default)
        if enclosed_quotes:
            script = self._strip_enclosed_quotes(script)
        return TemplateWrapper(self.printer, self.env, name, script)

    def load_expression(self, config, option, default=None):
        if isinstance(config, dict):
            name = "<dict>:%s" % (option,)
        else:
            name = "%s:%s" % (config.get_name(), option)
        script = config.get(option, default)
        return ExpressionWrapper(self.printer, self.env, name, script)

    def create_status_wrapper(self, eventtime=None):
        return StatusWrapper(self.printer, eventtime)

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
        kwparams['params'] = params
        self.in_script = True
        try:
            self.template.run_gcode_from_command(kwparams)
        finally:
            self.in_script = False


def load_config_prefix(config):
    return GCodeMacro(config)
