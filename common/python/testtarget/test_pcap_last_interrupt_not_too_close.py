#!/usr/bin/env python
import cocotb
import os

from cocotb.clock import Clock
from cocotb.triggers import ClockCycles
from pathlib import Path
import sys

sys.path.insert(1, str(Path(__file__).parent.resolve()))
from util import get_top, run_testtarget, PandaTestHarness


@cocotb.test()
async def pcap_last_interrupt_not_too_close(dut):
    test = PandaTestHarness(
        dut, Path(os.getenv('AUTOGEN_PATH')) / 'config_d')
    cocotb.start_soon(Clock(dut.clk_i, 1, 'ns').start(start_high=False))
    await test.reg_write('PCAP.ENABLE', 0x81)
    await test.reg_write('CLOCK.ENABLE', 0x81)
    clock_bitout = test.metadata.get_bitout('CLOCK0.OUT')
    await test.reg_write('PCAP.TRIG', clock_bitout)
    # Capture trigger timestamp
    await test.setup_capture([0x240])
    #test.queue_address(0x3000)
    await test.reg_write('CLOCK.PERIOD', 2)
    await ClockCycles(dut.clk_i, 64)
    await test.reg_write('CLOCK.PERIOD', 0)
    await ClockCycles(dut.clk_i, 2)
    await test.reg_write('PCAP.ENABLE', 0x80)
    # Allow some time for the data to be written in memory
    await ClockCycles(dut.clk_i, 32)
    #test.memory.assert_content(0x1000, [11 + i*2 for i in range(10)])


def test_pcap_last_interrupt_not_too_close(build_dir):
    run_testtarget('test_pcap_last_interrupt_not_too_close', get_top(), Path(build_dir))
