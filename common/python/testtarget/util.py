#!/usr/bin/env python
import cocotb
import logging
import numpy as np

from axi import AxiLiteMaster, AxiWriteSlave, AxiReadSlave
from block_metadata import BlockMetadata
from cocotb.triggers import RisingEdge, ClockCycles
from cocotb_tools.runner import get_runner
from collections import deque
from pathlib import Path


class PandaTestHarness(object):
    def __init__(self, dut, configd_path, mem_size=0x10000):
        self.log = logging.getLogger(__class__.__name__)
        self.dut = dut
        self.clock = dut.clk_i
        self.metadata = BlockMetadata(configd_path)
        self.reg_axi = AxiLiteMaster(dut, 's_reg_axil', self.clock)
        self.init_signals(dut)
        self.pcap_axi = AxiWriteSlave(dut, 'm_pcap_axi', self.clock)
        self.memory = Memory(mem_size)
        self.pcap_axi.add_callback(self.handle_pcap_write)
        self.table_axi = AxiReadSlave(dut, 'm_table_axi', self.clock,
                                      self.pattern_mem_read)
        self.address_queue = deque()
        self.want_quit = False
        self.pcap_irq_count = 0
        #self._addr_thread = cocotb.start_soon(self.address_pushing_func())

    def queue_address(self, addr):
        self.address_queue.appendleft(addr)

    async def address_pushing_func(self):
        pcap_dma = self.dut.pcap_inst.pcap_dma_inst
        while not self.want_quit:
            await RisingEdge(pcap_dma.irq_o)
            self.pcap_irq_count += 1
            await RisingEdge(self.clock)
            status = pcap_dma.IRQ_STATUS.value.to_unsigned()
            self.log.debug(f'PCAP IRQ STATUS  {status:08x}')
            # Check if a new buffer is required
            if status & 0x61:
                if not self.address_queue:
                    self.log.info('No more queued addresses for PCAP DMA!')
                else:
                    addr = self.address_queue.pop()
                    self.log.debug(f'Providing new PCAP DMA buffer at '
                                   f'address 0x{addr:08X}')
                    await self.reg_write('*DRV.PCAP_DMA_ADDR', addr)

    # Data returned on reads of a table
    def pattern_mem_read(self, addr):
        return addr & 0xFFFFFFFF

    def handle_pcap_write(self, transaction):
        addr, data_list = transaction
        self.memory.add_burst(addr, data_list)

    async def reg_write(self, field, value, reg_arg_index=0):
        await self.reg_axi.write(
            self.metadata.reg_addr_from_field(field, reg_arg_index), value)

    async def reg_read(self, field, reg_arg_index=0):
        return await self.reg_axi.read(
            self.metadata.reg_addr_from_field(field, reg_arg_index))

    def init_signals(self, dut):
        for sig in ('clk_i', 'reset_i'):
            dut[sig].value = 0

    async def setup_capture(self, masks,
                            # First 2 DMA buffers
                            addr1=0x1000, addr2=0x2000,
                            buffer_size=80):
        await self.reg_write('*DRV.PCAP_DMA_RESET', 0)
        await self.reg_write('*DRV.PCAP_BLOCK_SIZE', buffer_size)
        await RisingEdge(self.clock)
        await self.reg_write('*DRV.PCAP_DMA_ADDR', addr1)
        await RisingEdge(self.clock)
        await self.reg_write('*DRV.PCAP_DMA_START', 0)
        await self.reg_write('*DRV.PCAP_DMA_ADDR', addr2)
        await RisingEdge(self.clock)
        await self.reg_write('*REG.PCAP_START_WRITE', 0)
        await RisingEdge(self.clock)
        for mask in masks:
            await self.reg_write('*REG.PCAP_WRITE', mask)
            await RisingEdge(self.clock)

        await self.reg_write('*REG.PCAP_ARM', 0x0)
        await ClockCycles(self.clock, 2)
        await RisingEdge(self.clock)


def get_top():
    current = Path(__file__).parent.resolve()
    while not (current / '.git').exists():
        current = current.parent

    return current


def run_testtarget(test_module, fpga_path,  build_path):
    autogen_path = build_path / 'apps' / 'testtarget' / 'autogen'
    sources = get_dependencies(fpga_path, autogen_path)
    runner = get_runner('ghdl')
    runner.build(sources=sources,
                 build_args=[
                     '--std=08',
                     '-fsynopsys',
                     '-Wno-hide',
                 ],
                 build_dir=f'{str(build_path)}/sim_{test_module}',
                 hdl_toplevel='testtarget_top',
                 always=True,
                 clean=True,
                 )
    runner.test(hdl_toplevel='testtarget_top',
                test_args=[
                    '--std=08',
                    '-fsynopsys',
                    '-Wno-hide',
                ],
                extra_env={
                    'FPGA_PATH': str(fpga_path),
                    'AUTOGEN_PATH': str(autogen_path),
                },
                plusargs=['--fst=wave.fst'],
                test_module=test_module)


def get_dependencies(fpga_path, autogen_path):
    sources = \
        [
            fpga_path / 'common' / 'hdl' / 'defines' / name for name in
                ('top_defines.vhd', 'support.vhd', 'operator.vhd')
        ] + \
        [
            fpga_path / 'common' / 'hdl' / name for name in
                ('reg_top.vhd', 'reg.vhd', 'axi_lite_slave.vhd',
                 'axi_read_master.vhd', 'delay_line.vhd', 'bitmux.vhd',
                 'posmux.vhd', 'spbram.vhd', 'fifo.vhd')
        ] + \
        list(fpga_path.glob('common/hdl/table_read_engine*.vhd')) + \
        list(autogen_path.glob('hdl/*.vhd')) + \
        list(fpga_path.glob('modules/pcap/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/bits/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/calc/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/clock/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/counter/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/div/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/filter/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/lut/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/pcomp/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/pulse/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/seq/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/pgen/hdl/*.vhd')) + \
        list(fpga_path.glob('modules/srgate/hdl/*.vhd')) + \
        list(fpga_path.glob('targets/testtarget/hdl/*.vhd'))

    return sources


class Memory(object):
    def __init__(self, size):
        self.log = logging.getLogger(__class__.__name__)
        self.size = size
        self.mem = bytearray(size)
        self.word_view = np.frombuffer(self.mem, dtype=np.uint32)

    def clear(self):
        self.word_view.fill(0)

    def add_burst(self, addr, data_list):
        assert addr % 4 == 0, "Address must be word-aligned"
        index = addr // 4
        for data in data_list:
            self.word_view[index] = data
            index += 1

    def assert_content(self, addr, data_list):
        assert addr % 4 == 0, "Address must be word-aligned"
        index = addr // 4
        self.log.debug('Checking memory region - addr: 0x%08X, size: %d',
                       addr, len(data_list)*4)
        for expected in data_list:
            data = self.word_view[index]
            assert data == expected, \
                f'Memory mismatch at address 0x{index*4:08X}: ' + \
                f'expected 0x{expected:08X}, got 0x{data:08X}'
            index += 1
