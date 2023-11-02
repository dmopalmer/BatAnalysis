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
import astropy.units as u
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

    def _set_local_pfile_dir(self, dir):
        """
        make the local pfile dir if it doesnt exist and set this value

        :return: None
        """
        #make sure that it is a Path object
        self._local_pfile_dir=Path(dir)

        self._local_pfile_dir.mkdir(parents=True, exist_ok=True)
        try:
            hsp.local_pfiles(pfiles_dir=str(self._local_pfile_dir))
        except AttributeError:
            hsp.utils.local_pfiles(par_dir=str(self._local_pfile_dir))

    def _get_local_pfile_dir(self):
        """
        Return the _local_pfile_dir attribute

        :return: Returns the _local_pfile_dir Path object
        """

        return self._local_pfile_dir


    def _call_bathotpix(self, input_dict):
        """
        Calls heasoftpy's bathotpix with an error wrapper

        :param input_dict: Dictionary of inputs that will be passed to heasoftpy's bathotpix
        :return: heasoftpy Result object from bathotpix
        """

        # directly calls bathotpix
        try:
            return hsp.bathotpix(**input_dict)
        except Exception as e:
            print(e)
            raise RuntimeError(f"The call to Heasoft bathotpix failed with inputs: {input_dict}.")

    def _call_batbinevt(self, input_dict):
        """
        Calls heasoftpy's batbinevt with an error wrapper

        :param input_dict: Dictionary of inputs that will be passed to heasoftpy's batbinevt
        :return: heasoftpy Result object from batbinevt
        """
        # directly calls bathotpix
        try:
            return hsp.batbinevt(**input_dict)
        except Exception as e:
            print(e)
            raise RuntimeError(f"The call to Heasoft batbinevt failed with inputs {input_dict}.")

    def _call_batmaskwtevt(self, input_dict):
        """
        Calls heasoftpy's batmaskwtevt with an error wrapper,
        TODO: apply keyword correction for spectrum file (using the auxfile) via batupdatephakw

        :param input_dict: Dictionary of inputs that will be passed to heasoftpy's batmaskwtevt
        :return: heasoftpy Result object from batmaskwtevt
        """
        # directly calls bathotpix
        try:
            return hsp.batmaskwtevt(**input_dict)
        except Exception as e:
            print(e)
            raise RuntimeError(f"The call to Heasoft batmaskwtevt failed with inputs {input_dict}.")

    def _call_bateconvert(self, input_dict):
        """
        Calls heasoftpy's bateconvert with an error wrapper

        :param input_dict: Dictionary of inputs that will be passed to heasoftpy's bateconvert
        :return: heasoftpy Result object from bateconvert
        """
        # directly calls bateconvert
        try:
            return hsp.bateconvert(**input_dict)
        except Exception as e:
            print(e)
            raise RuntimeError(f"The call to Heasoft batmaskwtevt failed with inputs {input_dict}.")



class Lightcurve(BatObservation):
    """
    This is a general light curve class that contains typical information that a user may want from their lightcurve.
    This object is a wrapper around a light curve created from BAT event data.
    """

    def __init__(self, event_file,  lightcurve_file, detector_quality_mask, ra=None, dec=None, lc_input_dict=None, recalc=False):
        """
        This constructor reads in a fits file that contains light curve data for a given BAT event dataset. The fits file
        should have been created by a call to

        :param lightcurve_file:
        """

        #save these variables
        self.event_file = event_file
        self.lightcurve_file = lightcurve_file
        self.detector_quality_mask = detector_quality_mask

        #need to see if we have to construct the lightcurve if the file doesnt exist
        if not self.lightcurve_file.exists() or recalc:
            #see if the input dict is None so we can set these defaults, otherwise save the requested inputs for use later
            if lc_input_dict is None:
                self.lc_input_dict = dict(infile=str(self.event_file), outfile=str(self.lightcurve_file), outtype="LC",
                              energybins="15-350", weighted="YES", timedel=0.064,
                              detmask=str(self.detector_quality_mask),
                              tstart="INDEF", tstop="INDEF", clobber="YES", timebinalg="uniform")
            else:
                self.lc_input_dict = lc_input_dict

            #create the lightcurve
            self.bat_lc_result = self._call_batbinevt(self.lc_input_dict)

            #make sure that this calculation ran successfully
            if self.bat_lc_result.returncode != 0:
                raise RuntimeError('The creation of the lightcurve failed with message: {lc.bat_lc_result.stderr}')

        else:
            #set the self.lc_input_dict = None so the parsing of the lightcurve tries to also load in the
            #parameters passed into batbinevt to create the lightcurve
            #try to parse the existing lightcurve file to see what parameters were passed to batbinevt to construct the file
            self.lc_input_dict = None

        #set default RA/DEC coordinates correcpondent to the LC file which will be filled in later if it is set to None
        self.lc_ra = ra
        self.lc_dec = dec

        #read info from the lightcurve file
        self._parse_lightcurve_file()

        #read in the information about the weights
        self._get_event_weights()

        #were done getting all the info that we need. From here, the user can rebin the timebins and the energy bins


    def rebin_timebins(self):
        """
        This method allows for the dynamic rebinning of a light curve in time.

        :return:
        """

    def rebin_energybins(self, energybins=["15-25", "25-50", "50-100", "100-350", "15-350"], emin=None, emax=None):
        """
        This method allows for the dynamic rebinning of a light curve in energy

        :return:
        """

        # see if the user specified either the energy bins directly or emin/emax separately
        if emin is None and emax is None:
            # make sure that energybins is a list
            if type(energybins) is not list:
                energybins = [energybins]

            # verify that all elements are strings
            for i in energybins:
                if type(i) is not str:
                    raise ValueError(
                        'All elements of the passed in energybins variable must be a string. Please make sure this condition is met.')

            #need to get emin and emax values, assume that these are in keV already when converting to astropy quantities
            emin=[]
            emax=[]
            for i in energybins:
                energies=i.split('-')
                emin.append(energies[0])
                emax.append(energies[1])
            emin = u.Quantity(emin, u.keV)
            emax = u.Quantity(emax, u.keV)

        else:
            # make sure that both emin and emax are defined and have the same number of elements
            if (emin is None and emax is not None) or (emax is None and emin is not None):
                raise ValueError('Both emin and emax must be defined.')

            if len(emin) != len(emax):
                raise ValueError('Both emin and emax must have the same length.')

            # see if they are astropy quantity items with units
            if type(emin) is not u.Quantity:
                emin = u.Quantity(emin, u.keV)
            if type(emax) is not u.Quantity:
                emax = u.Quantity(emax, u.keV)

            # create our energybins input to batbinevt
            energybins = []
            for min, max in zip(emin.to(u.keV), emax.to(u.keV)):
                energybins.append(f"{min.value}-{max.value}")

        # create the full string
        ebins = ','.join(energybins)

        # need to see if the energybins are different (and even need to be calculated), if so do the recalculation
        if np.intersect1d(emin, self.ebins['E_MIN']).size != self.ebins['E_MIN'].size or np.intersect1d(emax, self.ebins['E_MAX']).size != self.ebins['E_MAX'].size:
            #the lc_input_dict wil need to be modified with new Energybins
            #self.lc_input_dict=dict()

            lc_return = self._call_batbinevt(self.lc_input_dict)

            #make sure that the lc_return was successful
            stop

    def _parse_lightcurve_file(self):
        """
        This method parses through a light curve file that has been created by batbinevent

        NOTE: A special value of timepixr=-1 (the default used when constructing light curves) specifies that
              timepixr=0.0 for uniformly binned light curves and
              timepixr=0.5 for non-unformly binned light curves. We recommend using the unambiguous TIME_CENT in the
              tbins attribute to prevent any confusion instead of the data["TIME"] values

        :return:
        """

        with fits.open(self.lightcurve_file) as f:
            header=f[1].header
            data=f[1].data
            energies=f["EBOUNDS"].data
            energies_header=f["EBOUNDS"].header

        if self.lc_ra is None and self.lc_dec is None:
            self.lc_ra = header["RA_OBJ"]
            self.lc_dec = header["DEC_OBJ"]
        else:
            #test if the passed in coordinates are what they should be for the light curve file
            #TODO: see if we are ~? arcmin close to one another
            assert (np.isclose(self.lc_ra, header["RA_OBJ"]) and np.isclose(self.lc_dec, header["DEC_OBJ"])), \
                   f"The passed in RA/DEC values ({self.lc_ra},{self.lc_dec}) do not match the values used to produce the lightcurve which are ({header['RA_OBJ']},{header['DEC_OBJ']})"

        #read in the data and save to data attribute which is a dictionary of the column names as keys and the numpy arrays as values
        self.data={}
        for i in data.columns:
            self.data[i.name] = u.Quantity(data[i.name], i.unit)

        #fill in the energy bin info
        self.ebins={}
        for i in energies.columns:
            if "CHANNEL" in i.name:
                self.ebins["INDEX"] = energies[i.name]
            elif "E" in i.name:
                self.ebins[i.name]=u.Quantity(energies[i.name], i.unit)

        #fill in the time info separately
        timepixr=header["TIMEPIXR"]
        #see if there is a time delta column exists for variable time bin widths
        if "TIMEDEL" not in self.data.keys():
            dt=header["TIMEDEL"]*u.s
        else:
            dt=self.data["TIMEDEL"]


        self.tbins = {}
        #see https://heasarc.gsfc.nasa.gov/ftools/caldb/help/batbinevt.html
        self.tbins["TIME_CENT"] = self.data["TIME"] + (0.5-timepixr)*dt
        self.tbins["TIME_START"] = self.data["TIME"] - timepixr*dt
        self.tbins["TIME_STOP"] = self.data["TIME"] + (1-timepixr)*dt

        #if self.lc_input_dict ==None, then we will need to try to read in the hisotry of parameters passed into batbinevt
        # to create the lightcurve file. thsi usually is needed when we first parse a file so we know what things are if we need to
        # do some sort of rebinning.

        #were looking for something like:
        # START PARAMETER list for batbinevt_1.48 at 2023-11-01T20:38:05
        #
        # P1 infile = /Users/tparsota/Documents/01116441000_eventresult/events/sw0
        # P1 1116441000bevshsp_uf.evt
        # P2 outfile = 01116441000_eventresult/lc/lightcurve_0.lc
        # P3 outtype = LC
        # P4 timedel = 0.064
        # P5 timebinalg = uniform
        # P6 energybins = 15-350
        # P7 gtifile = NONE
        # P8 ecol = ENERGY
        # P9 weighted = YES
        # P10 outunits = INDEF
        # P11 timepixr = -1.0
        # P12 maskwt = NONE
        # P13 tstart = INDEF
        # P14 tstop = INDEF
        # P15 snrthresh = 6.0
        # P16 detmask = /Users/tparsota/Documents/01116441000_eventresult/auxil/sw
        # P16 01116441000bdqcb.hk.gz
        # P17 tcol = TIME
        # P18 countscol = DPH_COUNTS
        # P19 xcol = DETX
        # P20 ycol = DETY
        # P21 maskwtcol = MASK_WEIGHT
        # P22 ebinquant = 0.1
        # P23 delzeroes = no
        # P24 minfracexp = 0.1
        # P25 min_dph_frac_overlap = 0.999
        # P26 min_dph_time_overlap = 0.0
        # P27 max_dph_time_nonoverlap = 0.5
        # P28 buffersize = 16384
        # P29 clobber = yes
        # P30 chatter = 2
        # P31 history = yes
        # P32 mode = ql
        # END PARAMETER list for batbinevt_1.48

        if self.lc_input_dict is None:
            #get the default names of the parameters for batbinevt including its name 9which should never change)
            test = hsp.HSPTask('batbinevt')
            default_params_dict=test.default_params.copy()
            taskname=test.taskname
            start_processing=None

            for i in header["HISTORY"]:
                if taskname in i and start_processing is None:
                    #then set a switch for us to start looking at things
                    start_processing = True
                elif taskname in i and start_processing is True:
                    #we want to stop processing things
                    start_processing = False

                if start_processing and "START" not in i and len(i)>0:
                    values=i.split(" ")
                    print(i, values, "=" in values)

                    parameter_num=values[0]
                    parameter=values[1]
                    if "=" not in values:
                        #this belongs with the previous parameter and is a line continuation
                        default_params_dict[old_parameter] = default_params_dict[old_parameter] + values[-1]
                    else:
                        default_params_dict[parameter] = values[-1]

                    old_parameter=parameter

            self.lc_input_dict = default_params_dict.copy()


    def _get_event_weights(self):
        """
        This method reads in the appropriate weights for event data once it has been applied to a event file, for a
        given RA/DEC position
        :return:
        """

        #read in all the info for the weights and save it such that we can use these weights in the future for
        #redoing lightcurve calculation
        with fits.open(self.event_file) as file:
            self._event_weights=file[1].data["MASK_WEIGHT"]



    def _set_event_weights(self):
        """
        This method sets the appropriate weights for event data, for a
        given RA/DEC position. This may be necessary if a user is analyzing multiple sources for which event data has been
        obtained.

        Note: event weightings need to be set if the RA/DEC of the light curve doesnt match what is in the event file

        :return:
        """

        if not self._same_event_lc_coords():
            #read in the event file and replace the values in the MASK_WEIGHT with the appropriate values in self._event_weights
            with fits.open(self.event_file, mode="update") as file:
                file[1].data["MASK_WEIGHT"]=self._event_weights

    def _same_event_lc_coords(self):
        """
        This simple program reads in the event data coordinates and compares it to what is obained from the lightcurve
        file that has been loaded in.

        :return: Boolean
        """

        with fits.open(self.event_file) as file:
            event_ra = file[0].header["RA_OBJ"]
            event_dec = file[0].header["DEC_OBJ"]
            coord_match = (event_ra == self.lc_ra) and (event_dec == self.lc_dec)

        return coord_match

    def _call_batbinevt(self, input_dict):
        """
        Calls heasoftpy's batbinevt with an error wrapper, ensures that this bins the event data to produce a lightcurve

        :param input_dict: Dictionary of inputs that will be passed to heasoftpy's batbinevt
        :return: heasoftpy Result object from batbinevt
        """
        # directly calls bathotpix
        try:
            return hsp.batbinevt(**input_dict)
        except Exception as e:
            print(e)
            raise RuntimeError(f"The call to Heasoft batbinevt failed with inputs {input_dict}.")



