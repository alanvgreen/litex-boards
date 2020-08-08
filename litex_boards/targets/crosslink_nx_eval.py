#!/usr/bin/env python3

# This file is Copyright (c) 2018-2019 Florent Kermarrec <florent@enjoy-digital.fr>
# This file is Copyright (c) 2018-2019 David Shah <dave@ds0.me>
# License: BSD

import os
import argparse

from migen import *
from migen.genlib.resetsync import AsyncResetSynchronizer

from litex_boards.platforms import crosslink_nx_eval

from litex.soc.cores.lifclspram import LIFCLSPRAM
from litex.soc.cores.lifcllram import LIFCLLRAM
from litex.soc.cores.spi_flash import SpiFlash
from litex.build.io import CRG

from litex.soc.cores.clock import *
from litex.soc.integration.soc_core import *
from litex.soc.integration.builder import *
from litex.soc.cores.led import LedChaser

kB = 1024
mB = 1024*kB

# CRG ----------------------------------------------------------------------------------------------

class _CRG(Module):
    def __init__(self, platform, sys_clk_freq):
        self.clock_domains.cd_sys = ClockDomain()
        self.clock_domains.cd_por = ClockDomain()

        # Clocking
        self.submodules.sys_clk = sys_osc = CrossLinkNXOSCA()
        sys_osc.create_clkout(self.cd_sys, sys_clk_freq)

        rst_n = platform.request("gsrn")

        # Power On Reset
        por_cycles  = 4096
        por_counter = Signal(log2_int(por_cycles), reset=por_cycles-1)
        self.comb += self.cd_por.clk.eq(self.cd_sys.clk)
        platform.add_period_constraint(self.cd_por.clk, sys_clk_freq)
        self.sync.por += If(por_counter != 0, por_counter.eq(por_counter - 1))
        self.specials += AsyncResetSynchronizer(self.cd_por, ~rst_n)
        self.specials += AsyncResetSynchronizer(self.cd_sys, (por_counter != 0))

# BaseSoC ------------------------------------------------------------------------------------------

class BaseSoC(SoCCore):
    SoCCore.mem_map = {
        "sram":             0x10000000,
        "spiflash":         0x20000000,
        "csr":              0xf0000000,
    }
    def __init__(self, flash_offset, sys_clk_freq=int(125e6), **kwargs):
        platform = crosslink_nx_eval.Platform()

        # Disable Integrated ROM/SRAM since Crosslink has its own ROM and RAM
        kwargs["integrated_sram_size"] = 0
        kwargs["integrated_rom_size"]  = 0

        # Set CPU variant / reset address
        kwargs["cpu_reset_address"] = self.mem_map["spiflash"] + flash_offset

        # SoCCore -----------------------------------------_----------------------------------------
        SoCCore.__init__(self, platform, sys_clk_freq,
            ident          = "LiteX SoC on Crosslink-NX",
            ident_version  = True,
            **kwargs)

        # CRG --------------------------------------------------------------------------------------
        self.submodules.crg = _CRG(platform, sys_clk_freq, cpu_variant = "standard")

        # 128KB LRAM (used as SRAM) ---------------------------------------------------------------
        size = 128*kB
        self.submodules.spram = LIFCLLRAM(32, size)
        self.register_mem("sram", self.mem_map["sram"], self.spram.bus, size)

        # SPI Flash --------------------------------------------------------------------------------
        self.submodules.spiflash = SpiFlash(platform.request("spiflash"), dummy=9, endianness="little")
        self.register_mem("spiflash", self.mem_map["spiflash"], self.spiflash.bus, size=16*mB)
        self.add_csr("spiflash")

        # Add ROM linker region --------------------------------------------------------------------
        self.add_memory_region("rom", self.mem_map["spiflash"] + flash_offset, 32*kB, type="cached+linker")

        # Leds -------------------------------------------------------------------------------------
        self.submodules.leds = LedChaser(
            pads         = Cat(*[platform.request("user_led", i) for i in range(14)]),
            sys_clk_freq = sys_clk_freq)
        self.add_csr("leds")

# Build --------------------------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="LiteX SoC on Crosslink-NX Eval Board")
    parser.add_argument("--build", action="store_true", help="Build bitstream")
    parser.add_argument("--load",  action="store_true", help="Load bitstream")
    parser.add_argument("--flash-offset", default=0x000000, help="Boot offset in SPI Flash")
    parser.add_argument("--sys-clk-freq",  default=25e6, help="System clock frequency (default=75MHz)")
    builder_args(parser)
    soc_core_args(parser)
    args = parser.parse_args()

    soc = BaseSoC(flash_offset=args.flash_offset, sys_clk_freq=int(float(args.sys_clk_freq)),
        **soc_core_argdict(args))
    builder = Builder(soc, **builder_argdict(args))
    builder_kargs = {}
    builder.build(**builder_kargs, run=args.build)

    if args.load:
        prog = soc.platform.create_programmer()
        prog.load_bitstream(os.path.join(builder.gateware_dir, soc.build_name + ".svf"))

if __name__ == "__main__":
    main()
