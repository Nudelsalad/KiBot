# -*- coding: utf-8 -*-
# Copyright (c) 2020-2021 Salvador E. Tropea
# Copyright (c) 2020-2021 Instituto Nacional de Tecnología Industrial
# License: GPL-3.0
# Project: KiBot (formerly KiPlot)
import os
from sys import (exit)
from .macros import macros, pre_class  # noqa: F401
from .gs import (GS)
from .optionable import Optionable
from .kiplot import check_eeschema_do, exec_with_retry, load_sch, add_extra_options
from .error import (KiPlotConfigurationError)
from .misc import (CMD_EESCHEMA_DO, ERC_ERROR)
from .log import (get_logger)

logger = get_logger(__name__)


@pre_class
class Run_ERC(BasePreFlight):  # noqa: F821
    """ [boolean=false] Runs the ERC (Electrical Rules Check). To ensure the schematic is electrically correct.
        The report file name is controlled by the global output pattern (%i=erc %x=txt) """
    def __init__(self, name, value):
        super().__init__(name, value)
        if not isinstance(value, bool):
            raise KiPlotConfigurationError('must be boolean')
        self._enabled = value
        self._sch_related = True
        self._expand_id = 'erc'
        self._expand_ext = 'txt'

    def get_targets(self):
        """ Returns a list of targets generated by this preflight """
        load_sch()
        out_pattern = GS.global_output if GS.global_output is not None else GS.def_global_output
        name = Optionable.expand_filename_sch(self, out_pattern)
        return [os.path.abspath(os.path.join(Optionable.expand_filename_sch(self, GS.out_dir), name))]

    def run(self):
        check_eeschema_do()
        # The schematic is loaded only before executing an output related to it.
        # But here we need data from it.
        output = self.get_targets()[0]
        logger.debug('ERC report: '+output)
        cmd = [CMD_EESCHEMA_DO, 'run_erc', '-o', output]
        if BasePreFlight.get_option('erc_warnings'):  # noqa: F821
            cmd.append('-w')
        if GS.filter_file:
            cmd.extend(['-f', GS.filter_file])
        cmd.extend([GS.sch_file, Optionable.expand_filename_sch(self, GS.out_dir)])
        # If we are in verbose mode enable debug in the child
        cmd, video_remove = add_extra_options(cmd)
        logger.info('- Running the ERC')
        ret = exec_with_retry(cmd)
        if video_remove:
            video_name = os.path.join(Optionable.expand_filename_sch(self, GS.out_dir), 'run_erc_eeschema_screencast.ogv')
            if os.path.isfile(video_name):
                os.remove(video_name)
        if ret:
            if ret > 127:
                ret = -(256-ret)
            if ret < 0:
                logger.error('ERC errors: %d', -ret)
            else:
                logger.error('ERC returned %d', ret)
                if GS.sch.annotation_error:
                    logger.error('Make sure your schematic is fully annotated')
            exit(ERC_ERROR)
