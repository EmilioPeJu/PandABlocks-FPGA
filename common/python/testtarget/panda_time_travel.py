import cocotb
import logging
import time

from cocotb.handle import HierarchyObject, HierarchyArrayObject
from cocotb.triggers import ClockCycles, RisingEdge
from enum import Enum, auto


class ClockTimerState(Enum):
    IDLE = auto()
    WAIT_FOR_LOW = auto()
    WAIT_FOR_ZERO = auto()


class PrescaledTimerState(Enum):
    IDLE = auto()
    WAIT_FOR_COUNTER = auto()


class PandaTimeTravel:
    # we jump only if jump is bigger than this value
    JUMP_THRES = 1024
    # we run at least this many ticks before we jump
    MIN_TICKS = 16

    def __init__(self, dut, fpga_clock_freq=125000000):
        self.log = logging.getLogger(__class__.__name__)
        self.dut = dut
        self.fpga_clock_freq = fpga_clock_freq
        self.discover_timers()
        for timer in self.clock_timers:
            cocotb.start_soon(self.handle_clock_timer(timer))
        for timer in self.prescaled_timers:
            cocotb.start_soon(self.handle_prescaled_timer(timer))

    def discover_timers(self):
        self.clock_timers = []
        self.prescaled_timers = []
        frontier = [self.dut]
        while frontier:
            current = frontier.pop()
            if current._def_name.lower() == 'timer_for_clock':
                print(f'Found timer: {current._name}')
                self.clock_timers.append(current)
            elif current._def_name.lower() == 'prescaled_timer':
                print(f'Found timer: {current._name}')
                self.prescaled_timers.append(current)
            elif isinstance(current, HierarchyObject):
                for name in dir(current):
                    if not name.startswith('_'):
                        frontier.append(getattr(current, name))
            elif isinstance(current, HierarchyArrayObject):
                for i in range(len(current)):
                    frontier.append(current[i])

    async def handle_clock_timer(self, timer):
        state = ClockTimerState.IDLE
        end_time = 0
        cycle_counter = 0
        low = 0
        await ClockCycles(timer.clk_i, 2)  # wait for the timer to be stable
        while True:
            await RisingEdge(timer.clk_i)
            match state:
                case ClockTimerState.IDLE:
                    if timer.enable_i.value == 0:
                        continue
                    auto_reload = timer.auto_reload_i.value.to_unsigned()
                    if auto_reload >= self.JUMP_THRES:
                        state = ClockTimerState.WAIT_FOR_LOW
                        low = timer.low_i.value.to_unsigned()
                        end_time = time.time() + \
                            (auto_reload - low) / self.fpga_clock_freq
                        cycle_counter = 0

                case ClockTimerState.WAIT_FOR_LOW:
                    cycle_counter += 1
                    if timer.enable_i.value == 0:
                        state = ClockTimerState.IDLE
                    elif timer.counter.value.to_unsigned() == low:
                        cycle_counter = 0
                        end_time = time.time() + low / self.fpga_clock_freq
                        state = ClockTimerState.WAIT_FOR_ZERO
                    elif cycle_counter >= self.MIN_TICKS \
                            and time.time() >= end_time:
                        # see you in the future
                        timer.counter.value = low

                case ClockTimerState.WAIT_FOR_ZERO:
                    cycle_counter += 1
                    if timer.enable_i.value == 0:
                        state = ClockTimerState.IDLE
                    elif timer.counter.value == 0:
                        cycle_counter = 0
                        end_time = time.time() + \
                            (auto_reload - low) / self.fpga_clock_freq
                        state = ClockTimerState.WAIT_FOR_LOW
                    elif cycle_counter >= self.MIN_TICKS \
                            and time.time() >= end_time:
                        # see you in the future
                        timer.counter.value = 0

    async def handle_prescaled_timer(self, timer):
        state = PrescaledTimerState.IDLE
        cycle_counter = 0
        await ClockCycles(timer.clk_i, 2)  # wait for the timer to be stable
        while True:
            await RisingEdge(timer.clk_i)
            match state:
                case PrescaledTimerState.IDLE:
                    cycle_counter = 0
                    if timer.enable_i.value == 1:
                        ticks = \
                            (timer.prescaler_rollover_i.value.to_unsigned() + 1) \
                            * (timer.timer_rollover_i.value.to_unsigned() + 1)
                        if ticks >= self.JUMP_THRES:
                            end_time = time.time() + ticks / self.fpga_clock_freq
                            cycle_counter = 0
                            state = PrescaledTimerState.WAIT_FOR_COUNTER
                case PrescaledTimerState.WAIT_FOR_COUNTER:
                    cycle_counter += 1
                    if timer.enable_i.value == 0:
                        state = PrescaledTimerState.IDLE
                    elif cycle_counter >= self.MIN_TICKS \
                            and time.time() >= end_time:
                        timer.counter.value = timer.timer_rollover_i.value
                        timer.precounter.value = timer.prescaler_rollover_i.value
                        state = PrescaledTimerState.IDLE
