"""
This file contains the batobservation class which contains information pertaining to a given bat observation.

Tyler Parsotan Jan 24 2022
"""
import os
import shutil
import sys
from .batlib import datadir, dirtest, met2mjd, met2utc
import glob
from astropy.io import fits
import numpy as np
import subprocess
import pickle
import sys
import re
from pathlib import Path
from astropy.time import Time
from datetime import datetime, timedelta
import re
import warnings

# for python>3.6
try:
    import heasoftpy as hsp
except ModuleNotFoundError as err:
    # Error handling
    print(err)

#try:
    #import xspec as xsp
#except ModuleNotFoundError as err:
    # Error handling
    #print(err)



class BatObservation(object):
    """
    A general Bat Observation object that holds information about the observation ID and the directory of the observation
    ID. This class ensures that the observation ID directory exists and throws an error if it does not.
    """
    def __init__(self, obs_id, obs_dir=None):
        """
        Constructor for the BatObservation object.

        :param obs_id: string of the observation id number
        :param obs_dir: string of the directory that the observation id folder resides within
        """

        self.obs_id = str(obs_id)
        if obs_dir is not None:
            obs_dir = Path(obs_dir).expanduser().resolve()
            # the use has provided a directory to where the bat observation id folder is kept
            # test to see if the folder exists there
            if  obs_dir.joinpath(self.obs_id).is_dir():
                self.obs_dir = obs_dir.joinpath(self.obs_id) # os.path.join(obs_dir , self.obs_id)
            else:
                raise FileNotFoundError(
                    'The directory %s does not contain the observation data corresponding to ID: %s' % (obs_dir, self.obs_id))
        else:
            obs_dir = datadir()  #Path.cwd()

            if obs_dir.joinpath(self.obs_id).is_dir():
                #os.path.isdir(os.path.join(obs_dir , self.obs_id)):
                self.obs_dir = obs_dir.joinpath(self.obs_id) #self.obs_dir = os.path.join(obs_dir , self.obs_id)
            else:
                raise FileNotFoundError('The directory %s does not contain the observation data correponding to ID: %s' % (obs_dir, self.obs_id))


class Lightcurve(object):
    """
    This is a general light curve class that contains typical information that a user may want from their lightcurve.
    This object is a wrapper around a light curve created from BAT event data.
    """

    def __init__(self, eventfile,  ):
        """
        This constructor reads in a fits file that contains light curve data for a given BAT event dataset. The fits file
        should have been created by a call to

        :param lightcurve_file:
        """


    def set_timebins(self):
        """
        This method allows for the dynamic rebinning of a light curve in time.

        :return:
        """

    def set_energy_bins(self):
        """
        This method allows for the dynamic rebinning of a light curve in energy

        :return:
        """

    def plot(self):
        """
        This convenience funciton plots the light curve for the specified timebinning and/or energy binning

        :return:
        """


