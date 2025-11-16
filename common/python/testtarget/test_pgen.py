#!/usr/bin/env python
import cocotb
import os

from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, ClockCycles
from pathlib import Path
import sys

sys.path.insert(1, str(Path(__file__).parent.resolve()))
from util import get_top, run_testtarget, PandaTestHarness


@cocotb.test()
async def pgen_run_one_table(dut):
    test = PandaTestHarness(dut, Path(os.getenv('AUTOGEN_PATH')) / 'config_d')
    pos_index = test.metadata.get_posout('PGEN.OUT')
    cocotb.start_soon(Clock(dut.clk_i, 1, 'ns').start(start_high=False))
    await test.reg_write('PGEN.ENABLE', 0x80)
    await test.reg_write('PGEN.TRIG', 0x80)
    await RisingEdge(dut.clk_i)
    await test.reg_write('PGEN.TABLE', 0x0, -2)
    await test.reg_write('PGEN.TABLE', 32, -1)
    await ClockCycles(dut.clk_i, 8)
    await test.reg_write('PGEN.ENABLE', 0x81)
    await RisingEdge(dut.clk_i)
    expected_val = 0
    for _ in range(16):
        await test.reg_write('PGEN.TRIG', 0x81)
        await RisingEdge(dut.clk_i)
        await test.reg_write('PGEN.TRIG', 0x80)
        await RisingEdge(dut.clk_i)
        # the simulated reads return the address that was requested as data
        assert dut.pos_bus[pos_index].value.to_unsigned() == expected_val
        expected_val += 4

    await test.reg_write('PGEN.ENABLE', 0x80)
    await RisingEdge(dut.clk_i)


def test_pgen(build_dir):
    run_testtarget('test_pgen', get_top(), Path(build_dir))
