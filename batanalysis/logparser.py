"""
Code to parse BAT log files.

These files are human readable running commentary that the BAT
software produces to describe its activities.  This is an unreliable
but convenient record of what the instrument saw and did.
Logging is often turned off to save bandwidth (especially
during TDRSS passes) and if the  logging system is
overloaded, text may be dropped.

Most (but not all) of its contents are duplicated in widely-scattered
telemetry types.
"""

from .batobservation import *
from .bat_survey import *
from .bat_tte import *
from .batlib import *
from .plotting import *
from .mosaic import *


from typing import Optional, Iterable
from dataclasses import dataclass
import swifttools.swift_too as stoo

import re
import datetime

dtype_ratchet = np.dtype([("met", np.float64), ("region", int), ("erange", int),
                             ("duration", np.float32), ("counts", int), ("score", float)])
dtype_counts = np.dtype([("met", np.uint32), ("counts", np.uint16)])

class LogParser:
    
    def __init__(self, timerange:Optional[Iterable[datetime.datetime]]=None,
                 files:Optional[list[str]]=None):
        self.files = []
        self.counts = np.zeros(0, dtype=dtype_counts)
        if timerange is not None:
            self.addtimes(timerange)
        if files is not None:
            self.addfiles(files)
        self.parsefiles()
        
    def addtimes(self, timerange):
        # queryargs = dict(time=f"{timerange[0]:%Y-%m-%d} .. {timerange[-1]:%Y-%m-%d}", fields='All', resultmax=0)
        # table_obs = from_heasarc(**queryargs)
        obstable = stoo.ObsQuery(begin=timerange[0], end=timerange[1])
        # allobsids = set([entry.obsid for entry in obstable])
        raise NotImplementedError("Log data is not yet downloadable by time")
        #TODO
        datadown = download_swiftdata(obstable, trend=True, match="*bshtb*", jobs=1)
        files = [down['data'][0].localpath for down in datadown.values() if len(down)]
        pass
        
        
        

@dataclass
class Detection:
    met: np.float64
    duration: float
    peak: float     # image peak
    sigma: float    # 1-sigma
    theta: float    # radians
    phi: float      # radians
    
    def from_lines(self, sourceline: str, responseline: str) -> "Detection":
        pass
        
@dataclass
class Ratchet:
    met: float
    duration: float
    region: int
    counts: int
    score: float
    
    def from_lines(self, ratchetline: str) -> Optional["Ratchet" ]:
        pass

@dataclass
class Trigger:
    trignum: int
    ratchets: np.ndarray
    detections: list[Detection]
    
