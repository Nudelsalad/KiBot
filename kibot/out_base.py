# -*- coding: utf-8 -*-
# Copyright (c) 2020-2021 Salvador E. Tropea
# Copyright (c) 2020-2021 Instituto Nacional de Tecnología Industrial
# License: GPL-3.0
# Project: KiBot (formerly KiPlot)
import os
from .gs import GS
from .kiplot import load_sch, get_board_comps_data
from .misc import Rect, KICAD_VERSION_5_99, W_WRONGPASTE
if GS.kicad_version_n >= KICAD_VERSION_5_99:  # pragma: no cover (Ki6)
    # New name, no alias ...
    from pcbnew import FP_SHAPE, wxPoint, LSET
else:
    from pcbnew import EDGE_MODULE, wxPoint, LSET
from .registrable import RegOutput
from .optionable import Optionable, BaseOptions
from .fil_base import BaseFilter, apply_fitted_filter, reset_filters
from .macros import macros, document  # noqa: F401
from . import log

logger = log.get_logger(__name__)


class BaseOutput(RegOutput):
    def __init__(self):
        super().__init__()
        with document:
            self.name = ''
            """ Used to identify this particular output definition """
            self.type = ''
            """ Type of output """
            self.dir = '.'
            """ Output directory for the generated files """
            self.comment = ''
            """ A comment for documentation purposes """
        self._sch_related = False
        self._unkown_is_error = True
        self._done = False

    @staticmethod
    def attr2longopt(attr):
        return '--'+attr.replace('_', '-')

    def is_sch(self):
        """ True for outputs that works on the schematic """
        return self._sch_related

    def is_pcb(self):
        """ True for outputs that works on the PCB """
        return not self._sch_related

    def get_targets(self, out_dir):
        """ Returns a list of targets generated by this output """
        if not (hasattr(self, "options") and hasattr(self.options, "get_targets")):
            logger.error("Output {} doesn't implement get_targets(), plese report it".format(self))
            return []
        return self.options.get_targets(out_dir)

    def get_dependencies(self):
        """ Returns a list of files needed to create this output """
        if self._sch_related:
            if GS.sch:
                return GS.sch.get_files()
            return [GS.sch_file]
        return [GS.pcb_file]

    def config(self, parent):
        super().config(parent)
        if getattr(self, 'options', None) and isinstance(self.options, type):
            # No options, get the defaults
            self.options = self.options()
            # Configure them using an empty tree
            self.options.config(self)

    def expand_dirname(self, out_dir):
        if self._sch_related:
            return self.options.expand_filename_sch(out_dir)
        return self.options.expand_filename_pcb(out_dir)

    def expand_filename(self, out_dir, name):
        if self._sch_related:
            name = self.options.expand_filename_sch(name)
        else:
            name = self.options.expand_filename_pcb(name)
        return os.path.abspath(os.path.join(out_dir, name))

    def run(self, output_dir):
        self.options.run(self.expand_filename(output_dir, self.options.output))


class BoMRegex(Optionable):
    """ Implements the pair column/regex """
    def __init__(self):
        super().__init__()
        self._unkown_is_error = True
        with document:
            self.column = ''
            """ Name of the column to apply the regular expression """
            self.regex = ''
            """ Regular expression to match """
            self.field = None
            """ {column} """
            self.regexp = None
            """ {regex} """
            self.skip_if_no_field = False
            """ Skip this test if the field doesn't exist """
            self.invert = False
            """ Invert the regex match result """


class VariantOptions(BaseOptions):
    """ BaseOptions plus generic support for variants. """
    def __init__(self):
        with document:
            self.variant = ''
            """ Board variant to apply """
            self.dnf_filter = Optionable
            """ [string|list(string)=''] Name of the filter to mark components as not fitted.
                A short-cut to use for simple cases where a variant is an overkill """
        super().__init__()
        self._comps = None

    def config(self, parent):
        super().config(parent)
        self.variant = RegOutput.check_variant(self.variant)
        self.dnf_filter = BaseFilter.solve_filter(self.dnf_filter, 'dnf_filter')

    def get_refs_hash(self):
        if not self._comps:
            return None
        return {c.ref: c for c in self._comps}

    def get_fitted_refs(self):
        """ List of fitted and included components """
        if not self._comps:
            return []
        return [c.ref for c in self._comps if c.fitted and c.included]

    def get_not_fitted_refs(self):
        """ List of 'not fitted' components, also includes 'not included' """
        if not self._comps:
            return []
        return [c.ref for c in self._comps if not c.fitted or not c.included]

    @staticmethod
    def create_module_element(m):
        if GS.kicad_version_n >= KICAD_VERSION_5_99:
            return FP_SHAPE(m)  # pragma: no cover (Ki6)
        return EDGE_MODULE(m)

    @staticmethod
    def cross_module(m, rect, layer):
        """ Draw a cross over a module.
            The rect is a Rect object with the size.
            The layer is which layer id will be used. """
        seg1 = VariantOptions.create_module_element(m)
        seg1.SetWidth(120000)
        seg1.SetStart(wxPoint(rect.x1, rect.y1))
        seg1.SetEnd(wxPoint(rect.x2, rect.y2))
        seg1.SetLayer(layer)
        seg1.SetLocalCoord()  # Update the local coordinates
        m.Add(seg1)
        seg2 = VariantOptions.create_module_element(m)
        seg2.SetWidth(120000)
        seg2.SetStart(wxPoint(rect.x1, rect.y2))
        seg2.SetEnd(wxPoint(rect.x2, rect.y1))
        seg2.SetLayer(layer)
        seg2.SetLocalCoord()  # Update the local coordinates
        m.Add(seg2)
        return [seg1, seg2]

    def cross_modules(self, board, comps_hash):
        """ Draw a cross in all 'not fitted' modules using *.Fab layer """
        # Cross the affected components
        ffab = board.GetLayerID('F.Fab')
        bfab = board.GetLayerID('B.Fab')
        extra_ffab_lines = []
        extra_bfab_lines = []
        for m in board.GetModules():
            ref = m.GetReference()
            # Rectangle containing the drawings, no text
            frect = Rect()
            brect = Rect()
            c = comps_hash.get(ref, None)
            if c and c.included and not c.fitted:
                # Meassure the component BBox (only graphics)
                for gi in m.GraphicalItems():
                    if gi.GetClass() == 'MGRAPHIC':
                        l_gi = gi.GetLayer()
                        if l_gi == ffab:
                            frect.Union(gi.GetBoundingBox().getWxRect())
                        if l_gi == bfab:
                            brect.Union(gi.GetBoundingBox().getWxRect())
                # Cross the graphics in *.Fab
                if frect.x1 is not None:
                    extra_ffab_lines.append(self.cross_module(m, frect, ffab))
                else:
                    extra_ffab_lines.append(None)
                if brect.x1 is not None:
                    extra_bfab_lines.append(self.cross_module(m, brect, bfab))
                else:
                    extra_bfab_lines.append(None)
        # Remmember the data used to undo it
        self.extra_ffab_lines = extra_ffab_lines
        self.extra_bfab_lines = extra_bfab_lines

    def uncross_modules(self, board, comps_hash):
        """ Undo the crosses in *.Fab layer """
        # Undo the drawings
        for m in board.GetModules():
            ref = m.GetReference()
            c = comps_hash.get(ref, None)
            if c and c.included and not c.fitted:
                restore = self.extra_ffab_lines.pop(0)
                if restore:
                    for line in restore:
                        m.Remove(line)
                restore = self.extra_bfab_lines.pop(0)
                if restore:
                    for line in restore:
                        m.Remove(line)

    def remove_paste_and_glue(self, board, comps_hash):
        """ Remove from solder paste layers the filtered components. """
        exclude = LSET()
        fpaste = board.GetLayerID('F.Paste')
        bpaste = board.GetLayerID('B.Paste')
        exclude.addLayer(fpaste)
        exclude.addLayer(bpaste)
        old_layers = []
        fadhes = board.GetLayerID('F.Adhes')
        badhes = board.GetLayerID('B.Adhes')
        old_fadhes = []
        old_badhes = []
        rescue = board.GetLayerID('Rescue')
        fmask = board.GetLayerID('F.Mask')
        bmask = board.GetLayerID('B.Mask')
        for m in board.GetModules():
            ref = m.GetReference()
            c = comps_hash.get(ref, None)
            if c and c.included and not c.fitted:
                # Remove all pads from *.Paste
                old_c_layers = []
                for p in m.Pads():
                    pad_layers = p.GetLayerSet()
                    is_front = fpaste in pad_layers.Seq()
                    old_c_layers.append(pad_layers.FmtHex())
                    pad_layers.removeLayerSet(exclude)
                    if len(pad_layers.Seq()) == 0:
                        # No layers at all. Ridiculous, but happends.
                        # At least add an F.Mask
                        pad_layers.addLayer(fmask if is_front else bmask)
                        logger.warning(W_WRONGPASTE+'Pad with solder paste, but no copper or solder mask aperture in '+ref)
                    p.SetLayerSet(pad_layers)
                old_layers.append(old_c_layers)
                # Remove any graphical item in the *.Adhes layers
                for gi in m.GraphicalItems():
                    l_gi = gi.GetLayer()
                    if l_gi == fadhes:
                        gi.SetLayer(rescue)
                        old_fadhes.append(gi)
                    if l_gi == badhes:
                        gi.SetLayer(rescue)
                        old_badhes.append(gi)
        # Store the data to undo the above actions
        self.old_layers = old_layers
        self.old_fadhes = old_fadhes
        self.old_badhes = old_badhes
        self.fadhes = fadhes
        self.badhes = badhes
        return exclude

    def restore_paste_and_glue(self, board, comps_hash):
        for m in board.GetModules():
            ref = m.GetReference()
            c = comps_hash.get(ref, None)
            if c and c.included and not c.fitted:
                restore = self.old_layers.pop(0)
                for p in m.Pads():
                    pad_layers = p.GetLayerSet()
                    res = restore.pop(0)
                    pad_layers.ParseHex(res, len(res))
                    p.SetLayerSet(pad_layers)
        for gi in self.old_fadhes:
            gi.SetLayer(self.fadhes)
        for gi in self.old_badhes:
            gi.SetLayer(self.badhes)

    def remove_fab(self, board, comps_hash):
        """ Remove from Fab the excluded components. """
        ffab = board.GetLayerID('F.Fab')
        bfab = board.GetLayerID('B.Fab')
        old_ffab = []
        old_bfab = []
        rescue = board.GetLayerID('Rescue')
        for m in board.GetModules():
            ref = m.GetReference()
            c = comps_hash.get(ref, None)
            if not c.included:
                # Remove any graphical item in the *.Fab layers
                for gi in m.GraphicalItems():
                    l_gi = gi.GetLayer()
                    if l_gi == ffab:
                        gi.SetLayer(rescue)
                        old_ffab.append(gi)
                    if l_gi == bfab:
                        gi.SetLayer(rescue)
                        old_bfab.append(gi)
        # Store the data to undo the above actions
        self.old_ffab = old_ffab
        self.old_bfab = old_bfab
        self.ffab = ffab
        self.bfab = bfab

    def restore_fab(self, board, comps_hash):
        for gi in self.old_ffab:
            gi.SetLayer(self.ffab)
        for gi in self.old_bfab:
            gi.SetLayer(self.bfab)

    def run(self, output_dir):
        """ Makes the list of components available """
        if not self.dnf_filter and not self.variant:
            return
        load_sch()
        # Get the components list from the schematic
        comps = GS.sch.get_components()
        get_board_comps_data(comps)
        # Apply the filter
        reset_filters(comps)
        apply_fitted_filter(comps, self.dnf_filter)
        # Apply the variant
        if self.variant:
            # Apply the variant
            comps = self.variant.filter(comps)
        self._comps = comps
