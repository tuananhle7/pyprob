#
# pyprob
# PyTorch-based library for probabilistic programming and inference compilation
# https://github.com/probprog/pyprob
#

import pyprob
from pyprob import util
from pyprob.trace import Sample, Trace
import traceback
import sys
import torch
import enum

current_trace = None
trace_mode = 'inference'
artifact = None
_current_function_name = None

class TraceMode(enum.Enum):
    INFERENCE = 1
    COMPILATION = 2
    COMPILED_INFERENCE = 3

def set_mode(mode):
    global trace_mode
    if isinstance(mode, TraceMode):
        trace_mode = mode
    #if mode in ['inference', 'compilation', 'compiled_inference']:
    #    trace_mode = mode
    else:
        #raise Exception('Unknown mode: {}. Use one of (inference, compilation, compiled_inference).'.format(mode))
        raise Exception('Unknown mode: {}. Use a value of TraceMode.'.format(mode))

def set_artifact(art):
    global artifact
    artifact = art

def begin_trace(f):
    global current_trace
    global _current_function_name
    current_trace = Trace()
    _current_function_name = f.__code__.co_name

def end_trace():
    global current_trace
    global _current_function_name
    current_trace.pack_observes_to_tensor()
    ret = current_trace
    current_trace = None
    _current_function_name = None
    return ret

def extract_address():
    #tb = traceback.extract_stack()
    # print()
    # for t in tb:
    #     print(t[0], t[1], t[2], t[3])
    #frame = tb[-3]
    # return '{0}/{1}/{2}'.format(frame[1], frame[2], frame[3])
    #return '{0}/{1}'.format(frame[1], frame[2])
    # Retun an address in the format:
    # 'instruction pointer' / 'qualified function name'
    frame = sys._getframe(2)
    ip = frame.f_lasti
    names = []
    var_name = _extract_target_of_assignment()
    if var_name is not None:
        names.append(var_name)
    while frame is not None:
        n = frame.f_code.co_name
        if n.startswith('<'): break
        names.append(n)
        if n == _current_function_name: break
        frame = frame.f_back
    return "{}/{}".format(ip, '.'.join(reversed(names)))


def _extract_target_of_assignment():
    import opcode
    frame = sys._getframe(3)
    code = frame.f_code
    next_instruction = code.co_code[frame.f_lasti+2]
    instruction_arg = code.co_code[frame.f_lasti+3]
    instruction_name = opcode.opname[next_instruction]
    if instruction_name == 'STORE_FAST':
        return code.co_varnames[instruction_arg]

    elif instruction_name in ['STORE_NAME', 'STORE_GLOBAL']:
        return code.co_names[instruction_arg]

    elif instruction_name in ['LOAD_FAST', 'LOAD_NAME', 'LOAD_GLOBAL'] and \
            opcode.opname[code.co_code[frame.f_lasti+4]] in ['LOAD_CONST', 'LOAD_FAST'] and \
            opcode.opname[code.co_code[frame.f_lasti+6]] == 'STORE_SUBSCR':
        base_name = (code.co_varnames if instruction_name == 'LOAD_FAST' else code.co_names)[instruction_arg]
        second_instruction = opcode.opname[code.co_code[frame.f_lasti+4]]
        second_arg = code.co_code[frame.f_lasti+5]
        if second_instruction == 'LOAD_CONST':
            value = code.co_consts[second_arg]
        elif second_instruction == 'LOAD_FAST':
            var_name = code.co_varnames[second_arg]
            value = frame.f_locals[var_name]
        else:
            value = None
        if type(value) is int:
            index_name = str(value)
            return base_name + '[' + index_name + ']'
        else:
            return None

    else:
        return None

def sample(distribution):
    global current_trace
    value = distribution.sample()
    if current_trace is not None:
        address = extract_address()
        current_sample = Sample(address, distribution, value)
        if trace_mode == TraceMode.COMPILED_INFERENCE:
            previous_sample = None
            if current_trace.length > 0:
                previous_sample = current_trace.samples[-1]
            proposal_distribution = artifact.forward(previous_sample, current_sample, volatile=True)
            proposal_distribution = pyprob.distributions.Normal(proposal_distribution.proposal_mean, proposal_distribution.proposal_std)
            value = proposal_distribution.sample()
            current_sample = Sample(address, distribution, value)
            current_trace.add_log_p(distribution.log_pdf(value) - proposal_distribution.log_pdf(value))
        current_trace.add_sample(current_sample)
        # current_trace.add_log_p(distribution.log_pdf(value))
        # print('Added sample {}'.format(sample))
    return value

def observe(distribution, value):
    global current_trace
    if current_trace is not None:
        if trace_mode == TraceMode.COMPILATION:
            current_trace.add_observe(distribution.sample())
        else:
            current_trace.add_observe(value)
        current_trace.add_log_p(distribution.log_pdf(value))
        # print('Added observe {}'.format(value))
    return
