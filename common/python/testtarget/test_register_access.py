#!/usr/bin/env python
import cocotb
import os

from cocotb.clock import Clock
from cocotb.triggers import RisingEdge
from pathlib import Path
import sys

sys.path.insert(1, str(Path(__file__).parent.resolve()))
from util import get_top, run_testtarget, PandaTestHarness


@cocotb.test()
async def write_register(dut):
    test = PandaTestHarness(dut, Path(os.getenv('AUTOGEN_PATH')) / 'config_d')
    outa_index = test.metadata.get_bitout('BITS.OUTA')
    cocotb.start_soon(Clock(dut.clk_i, 1, 'ns').start(start_high=False))
    await RisingEdge(dut.clk_i)
    a = (dut.bit_bus.value.to_unsigned() >> outa_index) & 0x1
    assert a == 0, 'Initial value of BITS.OUTA_o is not 0'
    await test.reg_write('BITS.A', 1)
    await RisingEdge(dut.clk_i)
    a = (dut.bit_bus.value.to_unsigned() >> outa_index) & 0x1
    assert a == 1, 'BITS.OUTA_o did not change to 1'


@cocotb.test()
async def read_register(dut):
    test = PandaTestHarness(dut, Path(os.getenv('AUTOGEN_PATH')) / 'config_d')
    cocotb.start_soon(Clock(dut.clk_i, 1, 'ns').start(start_high=False))
    await RisingEdge(dut.clk_i)
    dummy_ticks = await test.reg_read('*REG.PCAP_TS_TICKS', -1)
    assert dummy_ticks == 0x11223344


def test_register_access(build_dir):
    run_testtarget('test_register_access', get_top(), Path(build_dir))
